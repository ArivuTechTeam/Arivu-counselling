"use client";

import { ErrorPanel } from "@/components/shared/error-panel";
import "./globals.css";

export default function GlobalError({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body>
        <ErrorPanel reset={reset} />
      </body>
    </html>
  );
}
