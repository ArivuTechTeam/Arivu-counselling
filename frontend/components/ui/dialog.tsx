"use client";

import { useEffect, useRef, type MouseEvent, type ReactNode } from "react";

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

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
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const content = contentRef.current;
    const previouslyFocused =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    if (!content) return;

    const focusableElements = () =>
      Array.from(
        content.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter(
        (element) =>
          !element.hasAttribute("disabled") &&
          element.getAttribute("aria-hidden") !== "true" &&
          element.getClientRects().length > 0,
      );

    const initialTarget =
      content.querySelector<HTMLElement>("[data-dialog-initial-focus]") ??
      focusableElements()[0] ??
      content;
    initialTarget.focus({ preventScroll: true });

    function keepFocusInside(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const elements = focusableElements();
      if (elements.length === 0) {
        event.preventDefault();
        content?.focus();
        return;
      }
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (!content?.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", keepFocusInside);
    return () => {
      document.removeEventListener("keydown", keepFocusInside);
      if (previouslyFocused?.isConnected) {
        previouslyFocused.focus({ preventScroll: true });
      }
    };
  }, []);

  function handleBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (closeOnBackdrop && event.target === event.currentTarget) onClose?.();
  }

  return (
    <div className={overlayClassName} onMouseDown={handleBackdrop}>
      <div
        ref={contentRef}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        aria-labelledby={ariaLabelledBy}
        className={contentClassName}
        tabIndex={-1}
        onMouseDown={(event) => event.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}
