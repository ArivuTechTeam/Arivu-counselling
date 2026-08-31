import { AlertTriangle, RefreshCw } from "./icons";

/**
 * Styled error state — replaces bare `<p className="text-red-600">{error}</p>`.
 * Give it the error message and (optionally) an `onRetry` to re-run the failed
 * fetch. Keep the page header above it; drop this into the body.
 */
export function ErrorCard({
  title = "Something went wrong",
  message,
  onRetry,
  className,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center gap-3 rounded-2xl border border-destructive/20 bg-destructive/5 px-6 py-8 text-center ${className ?? ""}`}
    >
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <AlertTriangle size={22} />
      </span>
      <div>
        <p className="text-sm font-semibold text-foreground">{title}</p>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">{message}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 rounded-lg border border-input bg-card px-4 py-2 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-accent"
        >
          <RefreshCw size={15} />
          Try again
        </button>
      )}
    </div>
  );
}
