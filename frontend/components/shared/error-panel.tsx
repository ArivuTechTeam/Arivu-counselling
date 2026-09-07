"use client";

import Link from "next/link";

import { Brand } from "@/components/ui/brand";
import { Button } from "@/components/ui/button";

export function ErrorPanel({ reset }: { reset: () => void }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-5">
      <section
        role="alert"
        className="animate-rise w-full max-w-lg rounded-2xl border border-border bg-card p-8 text-center shadow-xl sm:p-10"
      >
        <Brand height={38} className="mb-7" />
        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10 text-2xl text-primary">
          !
        </div>
        <h1 className="text-2xl font-extrabold text-foreground">
          Something didn&apos;t load
        </h1>
        <p className="mx-auto mt-3 max-w-sm text-sm leading-6 text-muted-foreground">
          Your work is safe. Please try again, or return to sign in if the
          problem continues.
        </p>
        <div className="mt-7 flex flex-col justify-center gap-3 sm:flex-row">
          <Button type="button" onClick={reset}>
            Try again
          </Button>
          <Button asChild variant="outline">
            <Link href="/login">Return to sign in</Link>
          </Button>
        </div>
      </section>
    </main>
  );
}
