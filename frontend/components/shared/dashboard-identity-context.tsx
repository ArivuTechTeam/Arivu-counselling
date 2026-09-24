"use client";

import { createContext, useContext } from "react";

import type { DashboardProfile } from "@/lib/api";
import type { DashboardRole } from "@/lib/dashboard-bootstrap";

type DashboardIdentity = {
  role: DashboardRole | null;
  email: string;
  institution: DashboardProfile["institution"];
  canChangePassword: boolean;
  features: DashboardProfile["features"];
};

const NO_FEATURES: DashboardProfile["features"] = {
  faculty_jobs: false,
  quiz_reuse: false,
  batches: false,
  scoring_policies: false,
  commerce_pack: false,
  figure_attach: false,
};

const DashboardIdentityContext = createContext<DashboardIdentity>({
  role: null,
  email: "",
  institution: null,
  canChangePassword: false,
  features: NO_FEATURES,
});

export function DashboardIdentityProvider({
  role,
  email,
  institution,
  canChangePassword,
  features,
  children,
}: DashboardIdentity & { children: React.ReactNode }) {
  return (
    <DashboardIdentityContext.Provider
      value={{ role, email, institution, canChangePassword, features }}
    >
      {children}
    </DashboardIdentityContext.Provider>
  );
}

export function useDashboardIdentity(): DashboardIdentity {
  return useContext(DashboardIdentityContext);
}
