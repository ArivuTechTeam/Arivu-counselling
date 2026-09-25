"use client";

import Image from "next/image";

import { Building2 } from "@/components/ui/icons";
import type { DashboardProfile } from "@/lib/api";
import { institutionThemeStyle } from "@/lib/institution-theme";

/** Keep the verified dashboard identity, but remove navigation distractions. */
export function ExamShell({
  institution,
  children,
}: {
  institution: DashboardProfile["institution"];
  children: React.ReactNode;
}) {
  return (
    <div
      className="flex min-h-screen flex-col bg-background"
      style={institutionThemeStyle(institution?.primary_color)}
    >
      <button
        type="button"
        onClick={() => document.getElementById("exam-main")?.focus()}
        className="fixed left-3 top-3 z-50 -translate-y-20 rounded-md bg-card px-4 py-2 text-sm font-semibold shadow-lg focus:translate-y-0"
      >
        Skip to questions
      </button>
      <header className="sticky top-0 z-10 border-b bg-card/95 px-4 py-3 backdrop-blur sm:px-6">
        <div className="mx-auto flex w-full max-w-[1440px] items-center justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            {institution?.logo_url ? (
              // Institution logos use short-lived private Storage URLs.
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={institution.logo_url}
                alt={`${institution.name} logo`}
                className="h-9 w-auto max-w-28 shrink-0 object-contain sm:max-w-44"
              />
            ) : institution ? (
              <Building2 size={28} className="shrink-0 text-primary" />
            ) : (
              <Image
                src="/arivu-logo.png"
                alt="ArivuPro"
                width={118}
                height={28}
                className="h-7 w-auto shrink-0"
              />
            )}
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-foreground">
                {institution?.name ?? "ArivuPro"}
              </p>
              <p className="text-xs text-muted-foreground">Exam room</p>
            </div>
          </div>
          <span className="hidden rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs font-medium text-primary sm:inline-flex">
            Focus mode
          </span>
        </div>
      </header>
      <div id="exam-main" className="min-w-0 flex-1 outline-none" tabIndex={-1}>
        {children}
      </div>
    </div>
  );
}
