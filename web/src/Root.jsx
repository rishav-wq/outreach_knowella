import { useEffect, useState } from 'react'
import App from './App'
import Landing from './components/Landing'
import { Protected, AuthPage, isAuthPath, clerkEnabled } from './auth'

// Top-level switch: marketing landing page <-> the working app.
// The choice lives in the URL hash so a refresh keeps you where you were.
const isApp = () => window.location.hash.startsWith('#/app')

export default function Root() {
  const [view, setView] = useState(isApp() ? 'app' : 'landing')

  useEffect(() => {
    const onHash = () => setView(isApp() ? 'app' : 'landing')
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  // Going to the app lands on its default tab; App owns the sub-path from there.
  const go = (v) => { window.location.hash = v === 'app' ? '#/app/overview' : '#/'; setView(v) }

  // Clerk sends signed-out users to /sign-in (our self-hosted, branded page).
  if (clerkEnabled && isAuthPath()) return <AuthPage />

  return view === 'landing'
    ? <Landing onLaunch={() => go('app')} />
    : <Protected><App onHome={() => go('landing')} /></Protected>
}
