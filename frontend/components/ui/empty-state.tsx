import * as React from "react";

import { Inbox } from "./icons";

/**
 * Warm empty state — an icon, an optional title, a supportive line, and an
 * optional CTA. Backward compatible: older call sites that pass only `message`
 * (and maybe `action`) still work and now render inside a friendly card.
 */
export function EmptyState({
  icon,
  title,
  message,
  action,
  className,
}: {
  icon?: React.ReactNode;
  title?: string;
  message: string;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`flex flex-col items-center gap-3 rounded-2xl border border-dashed border-input bg-muted/30 px-6 py-10 text-center ${className ?? ""}`}
    >
      <span className="flex h-12 w-12 items-center justify-center rounded-full bg-muted text-muted-foreground">
        {icon ?? <Inbox size={22} />}
      </span>
      {title && <p className="text-sm font-semibold text-foreground">{title}</p>}
      <p className="max-w-sm text-sm text-muted-foreground">{message}</p>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
