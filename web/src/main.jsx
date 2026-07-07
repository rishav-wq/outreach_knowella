import React from 'react'
import { createRoot } from 'react-dom/client'
import { ClerkProvider } from '@clerk/clerk-react'
import Root from './Root'
import { clerkAppearance } from './auth'
import './styles.css'

// Clerk wraps the app only when a publishable key is set; without one the app
// runs unauthenticated (local dev). Set VITE_CLERK_PUBLISHABLE_KEY to enable it.
const pk = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    {pk
      ? <ClerkProvider
          publishableKey={pk}
          afterSignOutUrl="/"
          signInUrl="/sign-in"
          signUpUrl="/sign-up"
          appearance={clerkAppearance}
        ><Root /></ClerkProvider>
      : <Root />}
  </React.StrictMode>
)
