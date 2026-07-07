# Deploying Knowella Outreach to Render

Two services, defined in [`render.yaml`](render.yaml): the FastAPI **API** and the static **web** app. Auth is enforced by Clerk once the env vars are set.

## Prerequisites
- A GitHub repo with this code pushed (Render deploys from Git).
- A [Render](https://render.com) account.
- MongoDB Atlas connection string (`MONGO_URI`) — already in use locally.
- A Clerk application (you have the keys). For a public launch, create a **production** instance and use its `pk_live_…` / `sk_live_…` keys.

## 1. Push to GitHub
`.env` and `web/.env` are gitignored, so your secrets stay local. Commit and push everything else, then in Render: **New → Blueprint** and select the repo. Render reads `render.yaml` and creates both services.

## 2. Set env vars in Render
All are marked `sync: false`, so Render prompts for them. 

**outreach-api** (backend):
| var | value |
|-----|-------|
| `MONGO_URI` | your Atlas URI |
| `APOLLO_API_KEY` | Apollo key |
| `GOOGLE_API_KEY` | Gemini key |
| `TAVILY_API_KEY` | Tavily key |
| `CLERK_SECRET_KEY` | `sk_…` |
| `CLERK_PUBLISHABLE_KEY` | `pk_…` (used to derive the token issuer) |
| `ALLOWED_ORIGINS` | the web URL, e.g. `https://outreach-web.onrender.com` |

**outreach-web** (frontend):
| var | value |
|-----|-------|
| `VITE_CLERK_PUBLISHABLE_KEY` | `pk_…` |
| `VITE_API_BASE` | the API URL, e.g. `https://outreach-api.onrender.com` |

> You won't know the exact `.onrender.com` URLs until the services are created. Deploy once, copy the two URLs, set `ALLOWED_ORIGINS` + `VITE_API_BASE`, then trigger a redeploy of each.

## 3. Point Clerk at the production domain
In the Clerk dashboard → your instance → **Domains / Allowed origins**, add the web app URL (`https://outreach-web.onrender.com`). With a `pk_test_…` dev instance this is usually permissive; a `pk_live_…` instance requires the domain to be configured.

## 4. Verify
- Visit the web URL → you should hit the Clerk sign-in wall.
- Sign in → the app loads and API calls succeed (the session token is sent as a Bearer header and the API verifies it against Clerk's JWKS).
- `GET /api/health` on the API stays public (Render's health check).

## Notes
- **Auth is opt-in.** With no Clerk env set the API is open and the frontend skips the sign-in wall — that's why local dev works without keys. Setting the keys (locally or on Render) turns it on.
- **Single sign-in wall, not multi-tenant.** Every signed-in user sees the same campaigns/data. Per-user data isolation is a separate, larger change.
- **Free Render tier** spins services down when idle; the first request after idle is slow. Use a paid plan for always-on.
