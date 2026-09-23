"use client";

import { createContext, useContext } from "react";

import type { DashboardProfile } from "@/lib/api";
import type { DashboardRole } from "@/lib/dashboard-bootstrap";

type DashboardIdentity = {
  role: DashboardRole | null;
  institution: DashboardProfile["institution"];
};

const DashboardIdentityContext = createContext<DashboardIdentity>({
  role: null,
  institution: null,
});

export function DashboardIdentityProvider({
  role,
  institution,
  children,
}: DashboardIdentity & { children: React.ReactNode }) {
  return (
    <DashboardIdentityContext.Provider value={{ role, institution }}>
      {children}
    </DashboardIdentityContext.Provider>
  );
}

export function useDashboardIdentity(): DashboardIdentity {
  return useContext(DashboardIdentityContext);
}
