"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Check, Copy, X } from "@/components/ui/icons";

export type TemporaryCredentials = {
  email: string;
  password: string;
  institution: string;
  loginUrl?: string;
};

export function TemporaryCredentialsDialog({
  credentials,
  onClose,
}: {
  credentials: TemporaryCredentials;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  async function copyCredentials() {
    const text = [
      `Institution: ${credentials.institution}`,
      ...(credentials.loginUrl ? [`Login link: ${credentials.loginUrl}`] : []),
      `Email: ${credentials.email}`,
      `Temporary password: ${credentials.password}`,
    ].join("\n");
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setCopyError(null);
    } catch {
      setCopyError("Could not access the clipboard. Copy the values manually.");
    }
  }

  return (
    <Dialog
      onClose={onClose}
      ariaLabelledBy="temporary-credentials-title"
      contentClassName="w-full max-w-lg rounded-2xl border bg-card p-6 shadow-xl"
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 id="temporary-credentials-title" className="text-lg font-semibold">
            Copy temporary credentials
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            This password is shown only now. Closing this window removes it from
            the page.
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <X size={18} />
        </button>
      </div>

      <dl className="mt-5 overflow-hidden rounded-lg border text-sm">
        <div className="grid grid-cols-[130px_1fr] gap-3 border-b px-4 py-3">
          <dt className="text-muted-foreground">Institution</dt>
          <dd className="font-medium">{credentials.institution}</dd>
        </div>
        {credentials.loginUrl && (
          <div className="grid grid-cols-[130px_1fr] gap-3 border-b px-4 py-3">
            <dt className="text-muted-foreground">Login link</dt>
            <dd className="min-w-0 break-all font-medium">
              <a
                href={credentials.loginUrl}
                target="_blank"
                rel="noreferrer"
                className="text-primary hover:underline"
              >
                {credentials.loginUrl}
              </a>
            </dd>
          </div>
        )}
        <div className="grid grid-cols-[130px_1fr] gap-3 border-b px-4 py-3">
          <dt className="text-muted-foreground">Email</dt>
          <dd className="break-all font-medium">{credentials.email}</dd>
        </div>
        <div className="grid grid-cols-[130px_1fr] gap-3 px-4 py-3">
          <dt className="text-muted-foreground">Password</dt>
          <dd className="break-all font-mono font-semibold">
            {credentials.password}
          </dd>
        </div>
      </dl>

      {copyError && (
        <p className="mt-3 text-sm text-destructive">{copyError}</p>
      )}

      <div className="mt-6 flex justify-end gap-3">
        <Button type="button" variant="outline" onClick={onClose}>
          Done
        </Button>
        <Button type="button" onClick={copyCredentials}>
          {copied ? (
            <Check size={15} className="mr-1.5" />
          ) : (
            <Copy size={15} className="mr-1.5" />
          )}
          {copied ? "Copied" : "Copy credentials"}
        </Button>
      </div>
    </Dialog>
  );
}
