import { createContext, useContext } from 'react'

// The signed-in person and their role, from /api/me. The server enforces every rule
// (src/access.py); this only decides what the UI shows, so nobody meets a button the
// server will refuse.
export const MeContext = createContext(null)
export const useMe = () => useContext(MeContext) || {}

export const isAdmin = (me) => me?.role === 'admin'
export const canSales = (me) => me?.role === 'admin' || me?.role === 'sales'
export const canMarketing = (me) => me?.role === 'admin' || me?.role === 'marketing'
