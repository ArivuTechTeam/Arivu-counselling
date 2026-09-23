"use client";

import { useEffect, useState } from "react";

import { useDashboardIdentity } from "@/components/shared/dashboard-identity-context";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Building2, Check, Copy } from "@/components/ui/icons";
import { institutionLoginUrl } from "@/lib/institution-portal";

export function InstitutionAccessLinkCard() {
  const { institution } = useDashboardIdentity();
  const [portalUrl, setPortalUrl] = useState("");
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  useEffect(() => {
    setPortalUrl(
      institution?.subdomain
        ? institutionLoginUrl(institution.subdomain, window.location.origin)
        : "",
    );
  }, [institution?.subdomain]);

  if (!institution || !portalUrl) return null;

  async function copyPortalLink() {
    try {
      await navigator.clipboard.writeText(portalUrl);
      setCopied(true);
      setCopyError(null);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopyError("Could not copy the link. Select and copy it manually.");
    }
  }

  return (
    <Card className="border-primary/20 bg-primary/[0.035]">
      <CardContent className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
            <Building2 size={20} />
          </span>
          <div className="min-w-0">
            <h2 className="font-semibold text-foreground">
              {institution.name} access link
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Share this one link with teachers and students. Teachers sign in
              with assigned credentials; students can create their own account.
            </p>
            <a
              href={portalUrl}
              target="_blank"
              rel="noreferrer"
              className="mt-2 block break-all text-sm font-medium text-primary hover:underline"
            >
              {portalUrl}
            </a>
            {copyError && <p className="mt-2 text-xs text-destructive">{copyError}</p>}
          </div>
        </div>
        <Button type="button" variant="outline" onClick={copyPortalLink}>
          {copied ? <Check size={15} className="mr-1.5" /> : <Copy size={15} className="mr-1.5" />}
          {copied ? "Copied" : "Copy access link"}
        </Button>
      </CardContent>
    </Card>
  );
}
