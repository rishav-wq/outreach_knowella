import { SignedIn, SignedOut, SignIn, SignUp, RedirectToSignIn, UserButton, useAuth } from '@clerk/clerk-react'

// Auth is opt-in: with no publishable key (local dev) the app renders exactly as
// before. Set VITE_CLERK_PUBLISHABLE_KEY and the app goes behind a sign-in wall.
export const clerkEnabled = !!import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

// Theme Clerk's components to the "Halo" identity so sign-in matches the app
// (bright card, indigo primary, our type) instead of Clerk's dark default.
export const clerkAppearance = {
  variables: {
    colorPrimary: '#0e8098',
    colorText: '#10222b',
    colorTextSecondary: '#77898f',
    colorBackground: '#ffffff',
    colorInputBackground: '#ffffff',
    colorInputText: '#10222b',
    colorNeutral: '#0b2530',
    colorDanger: '#c92a2a',
    colorSuccess: '#15803d',
    borderRadius: '10px',
    fontFamily: "'Instrument Sans', system-ui, sans-serif",
    fontFamilyButtons: "'Instrument Sans', system-ui, sans-serif",
  },
  elements: {
    card: { boxShadow: '0 4px 10px rgba(16,34,41,0.06), 0 32px 64px -24px rgba(16,34,41,0.24)', border: '1px solid #cbdadf' },
    formButtonPrimary: { background: '#0e8098', textTransform: 'none', fontSize: '14px' },
    footerActionLink: { color: '#0e8098' },
  },
}

// True when the browser is on our self-hosted sign-in/up path. Root renders the
// AuthPage for these so Clerk's sign-in lives IN our app, not the hosted portal.
export function isAuthPath() {
  return /^\/sign-(in|up)/.test(window.location.pathname)
}

// Full-page, branded sign-in/up rendered in-app. `routing="path"` + a matching
// ClerkProvider signInUrl is what stops the redirect to accounts.dev.
export function AuthPage() {
  const signUp = window.location.pathname.startsWith('/sign-up')
  const common = { appearance: clerkAppearance, fallbackRedirectUrl: '/#/app/overview' }
  return (
    <div className="auth-gate">
      <div className="auth-gate-head">
        <div className="auth-gate-brand"><span className="logo">K</span> Knowella <span className="auth-gate-brand-sub">Outreach</span></div>
        <p className="auth-gate-tag">Grounded, human-approved cold outreach. Sign in to continue.</p>
      </div>
      {signUp
        ? <SignUp routing="path" path="/sign-up" signInUrl="/sign-in" {...common} />
        : <SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" {...common} />}
    </div>
  )
}

// Gate the app: signed-in users get it; signed-out users are sent to our in-app
// /sign-in (RedirectToSignIn honors the provider's signInUrl, so it stays local).
export function Protected({ children }) {
  if (!clerkEnabled) return children
  return (
    <>
      <SignedIn>{children}</SignedIn>
      <SignedOut><RedirectToSignIn /></SignedOut>
    </>
  )
}

// The account / sign-out control for the sidebar. Renders nothing without Clerk.
export function UserMenu() {
  if (!clerkEnabled) return null
  return <UserButton afterSignOutUrl="/" appearance={clerkAppearance} />
}

// Bearer token for API calls, from the active Clerk session. '' when signed out
// or when Clerk isn't configured (backend auth is then also off).
export async function getAuthToken() {
  try {
    const t = await window.Clerk?.session?.getToken?.()
    return t || ''
  } catch {
    return ''
  }
}

export { useAuth }
