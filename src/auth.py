"""Clerk authentication for the API.

Auth is OPT-IN: it activates only when Clerk env is configured. With nothing set
— e.g. local dev — the dependency is a no-op and the app runs without login. In
production (Render) set CLERK_SECRET_KEY + CLERK_PUBLISHABLE_KEY (or CLERK_ISSUER)
and every /api route then requires a valid, signed Clerk session token.

Verification is done against Clerk's public JWKS (no secret needed to verify a
token's signature), so the frontend just sends `Authorization: Bearer <token>`
where the token is `window.Clerk.session.getToken()`.
"""
from __future__ import annotations

import base64
import os

from fastapi import HTTPException, Request

_jwks_client = None  # cached PyJWKClient (network fetch of Clerk's public keys)

# Routes that must stay open even when auth is on (health check + CORS preflight).
_OPEN_PATHS = {"/api/health", "/", "/docs", "/openapi.json"}


def _issuer() -> str | None:
    """The Clerk token issuer URL, from CLERK_ISSUER or derived from the publishable key.

    A Clerk publishable key is `pk_<env>_<base64(frontend_api_domain + '$')>`, and
    the session-token issuer is exactly `https://<frontend_api_domain>`.
    """
    iss = os.environ.get("CLERK_ISSUER")
    if iss:
        return iss.rstrip("/")
    pk = (os.environ.get("CLERK_PUBLISHABLE_KEY")
          or os.environ.get("VITE_CLERK_PUBLISHABLE_KEY")
          or os.environ.get("NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY"))  # tolerate the Next.js name
    if pk and "_" in pk:
        try:
            b64 = pk.split("_", 2)[-1]
            domain = base64.b64decode(b64 + "===").decode().rstrip("$")
            if domain:
                return f"https://{domain}"
        except Exception:
            return None
    return None


def enabled() -> bool:
    """True when Clerk is configured; when False the API is open (local dev)."""
    return bool(os.environ.get("CLERK_SECRET_KEY") or _issuer())


_email_cache: dict[str, str] = {}  # clerk user id -> primary email (per process)


def _allowlist() -> tuple[set[str], set[str]]:
    """(allowed emails, allowed domains) from env. Empty => anyone signed in is allowed."""
    emails = {e.strip().lower() for e in os.environ.get("ALLOWED_EMAILS", "").split(",") if e.strip()}
    domains = {d.strip().lower().lstrip("@") for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()}
    return emails, domains


def _user_email(sub: str) -> str:
    """The user's primary email, fetched from Clerk's API (cached). '' if unavailable."""
    if sub in _email_cache:
        return _email_cache[sub]
    key = os.environ.get("CLERK_SECRET_KEY")
    email = ""
    if key and sub:
        try:
            import httpx
            r = httpx.get(f"https://api.clerk.com/v1/users/{sub}",
                          headers={"Authorization": f"Bearer {key}"}, timeout=15)
            if r.status_code < 400:
                d = r.json()
                pid = d.get("primary_email_address_id")
                addrs = d.get("email_addresses", []) or []
                email = next((a.get("email_address", "") for a in addrs if a.get("id") == pid),
                             addrs[0].get("email_address", "") if addrs else "")
        except Exception:
            email = ""
    _email_cache[sub] = email
    return email


def _check_allowed(claims: dict) -> None:
    """Enforce the email/domain allowlist. No-op when no allowlist is configured."""
    emails, domains = _allowlist()
    if not emails and not domains:
        return  # open to any signed-in user
    email = (claims.get("email") or _user_email(claims.get("sub", ""))).lower()
    dom = email.rsplit("@", 1)[-1] if "@" in email else ""
    if email in emails or (dom and dom in domains):
        return
    raise HTTPException(status_code=403, detail="this account is not authorized for this app")


def _jwks():
    global _jwks_client
    if _jwks_client is None:
        import jwt  # PyJWT[crypto]
        iss = _issuer()
        if not iss:
            raise RuntimeError("Clerk auth is enabled but no issuer/publishable key is configured")
        _jwks_client = jwt.PyJWKClient(f"{iss}/.well-known/jwks.json")
    return _jwks_client


def verify_token(token: str) -> dict:
    """Verify a Clerk session JWT's signature + issuer + expiry. Raises on failure."""
    import jwt
    signing_key = _jwks().get_signing_key_from_jwt(token).key
    return jwt.decode(
        token, signing_key, algorithms=["RS256"],
        issuer=_issuer(), options={"verify_aud": False},
    )


async def require_auth(request: Request):
    """FastAPI dependency applied to every route. No-op unless Clerk is configured."""
    if not enabled():
        return None
    if request.method == "OPTIONS" or request.url.path in _OPEN_PATHS:
        return None
    authz = request.headers.get("authorization") or ""
    if not authz.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authz.split(" ", 1)[1].strip()
    try:
        claims = verify_token(token)
    except Exception as e:  # signature/expiry/issuer mismatch → unauthenticated
        raise HTTPException(status_code=401, detail=f"invalid session: {e}")
    _check_allowed(claims)  # 403 if an allowlist is set and this user isn't on it
    request.state.user = claims.get("sub")
    return claims
