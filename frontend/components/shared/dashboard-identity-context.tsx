"use client";

import { createContext, useContext } from "react";

import type { DashboardProfile } from "@/lib/api";
import type { DashboardRole } from "@/lib/dashboard-bootstrap";

type DashboardIdentity = {
  role: DashboardRole | null;
  email: string;
  institution: DashboardProfile["institution"];
  canChangePassword: boolean;
};

const DashboardIdentityContext = createContext<DashboardIdentity>({
  role: null,
  email: "",
  institution: null,
  canChangePassword: false,
});

export function DashboardIdentityProvider({
  role,
  email,
  institution,
  canChangePassword,
  children,
}: DashboardIdentity & { children: React.ReactNode }) {
  return (
    <DashboardIdentityContext.Provider
      value={{ role, email, institution, canChangePassword }}
    >
      {children}
    </DashboardIdentityContext.Provider>
  );
}

export function useDashboardIdentity(): DashboardIdentity {
  return useContext(DashboardIdentityContext);
}
