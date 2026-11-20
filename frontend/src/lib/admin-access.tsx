"use client";
import { createContext, useContext } from "react";
import type { AdminAccess } from "@/lib/api";

/** Access resolved by the admin shell (super-admin or scoped staff role). Null outside the shell. */
export const AdminAccessContext = createContext<AdminAccess | null>(null);
export const useAdminShellAccess = () => useContext(AdminAccessContext);

/** True for a super-admin, or for staff inside the admin shell (the backend still scopes each endpoint). */
export function useCanUseAdmin(role: string | undefined): boolean {
  const access = useContext(AdminAccessContext);
  return role === "admin" || !!access?.is_staff;
}
