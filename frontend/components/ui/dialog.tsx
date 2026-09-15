"use client";

import { useEffect, type MouseEvent, type ReactNode } from "react";

export function useEscapeKey(active: boolean, onEscape?: () => void) {
  useEffect(() => {
    if (!active || !onEscape) return;

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onEscape?.();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [active, onEscape]);
}

export function Dialog({
  children,
  onClose,
  ariaLabel,
  ariaLabelledBy,
  closeOnBackdrop = true,
  overlayClassName = "fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4",
  contentClassName = "",
}: {
  children: ReactNode;
  onClose?: () => void;
  ariaLabel?: string;
  ariaLabelledBy?: string;
  closeOnBackdrop?: boolean;
  overlayClassName?: string;
  contentClassName?: string;
}) {
  useEscapeKey(true, onClose);

  function handleBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (closeOnBackdrop && event.target === event.currentTarget) onClose?.();
  }

  return (
    <div className={overlayClassName} onMouseDown={handleBackdrop}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        className={contentClassName}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
