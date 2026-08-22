import * as React from "react";

/** The muted one-liner (with an optional action) shown when a list is empty. */
export function EmptyState({
  message,
  action,
}: {
  message: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-start gap-3 py-2">
      <p className="text-sm text-muted-foreground">{message}</p>
      {action}
    </div>
  );
}
