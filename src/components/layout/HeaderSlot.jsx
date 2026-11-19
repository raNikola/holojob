import { createContext, useContext } from 'react'
import { createPortal } from 'react-dom'

/** The page header's slot (set by AppShell). A screen puts its tabs and actions there with <HeaderPortal>; without a shell it renders inline. */
export const HeaderSlotContext = createContext(null)

export function HeaderPortal({ children }) {
  const slot = useContext(HeaderSlotContext)
  return slot ? createPortal(children, slot) : children
}
