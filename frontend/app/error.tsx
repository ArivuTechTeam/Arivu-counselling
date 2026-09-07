"use client";

import { ErrorPanel } from "@/components/shared/error-panel";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return <ErrorPanel reset={reset} />;
}
