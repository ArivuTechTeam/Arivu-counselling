"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { createPortal } from "react-dom";

import { AlertTriangle, Check, Sparkles } from "@/components/ui/icons";

/**
 * Lightweight, dependency-free toast (pop-up) system.
 *
 * Use it for ONE-OFF actions — publish, extract, generate, approve-all — where a
 * single confirmation is welcome. Do NOT use it for per-item feedback like
 * approving individual questions (50 questions would mean 50 toasts); those use
 * in-card animation instead.
 *
 * Mounted once near the root (dashboard layout). Call `useToast().notify(...)`.
 */

type ToastTone = "success" | "error" | "info";
type ToastItem = { id: number; message: string; tone: ToastTone };
type ToastContextValue = {
  notify: (message: string, tone?: ToastTone) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) {
    throw new Error("useToast must be used within a <ToastProvider>.");
  }
  return ctx;
}

let nextId = 0;
const AUTO_DISMISS_MS = 4200;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id));
  }, []);

  const notify = useCallback(
    (message: string, tone: ToastTone = "success") => {
      const id = ++nextId;
      setToasts((current) => [...current, { id, message, tone }]);
      window.setTimeout(() => dismiss(id), AUTO_DISMISS_MS);
    },
    [dismiss],
  );

  return (
    <ToastContext.Provider value={{ notify }}>
      {children}
      {mounted &&
        createPortal(
          <div className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-[min(92vw,22rem)] flex-col gap-2">
            {toasts.map((toast) => (
              <ToastCard
                key={toast.id}
                toast={toast}
                onClose={() => dismiss(toast.id)}
              />
            ))}
          </div>,
          document.body,
        )}
    </ToastContext.Provider>
  );
}

const TONE_BORDER: Record<ToastTone, string> = {
  success: "border-emerald-300",
  error: "border-rose-300",
  info: "border-primary/30",
};
const TONE_ICON_COLOR: Record<ToastTone, string> = {
  success: "text-emerald-600",
  error: "text-rose-600",
  info: "text-primary",
};

function ToastCard({
  toast,
  onClose,
}: {
  toast: ToastItem;
  onClose: () => void;
}) {
  const Icon =
    toast.tone === "error"
      ? AlertTriangle
      : toast.tone === "info"
        ? Sparkles
        : Check;
  return (
    <div
      role="status"
      className={`animate-toast-in pointer-events-auto flex items-start gap-3 rounded-xl border ${TONE_BORDER[toast.tone]} bg-card px-4 py-3 text-foreground shadow-lg`}
    >
      <span className={`mt-0.5 shrink-0 ${TONE_ICON_COLOR[toast.tone]}`}>
        <Icon size={18} />
      </span>
      <p className="flex-1 text-sm font-medium leading-snug">{toast.message}</p>
      <button
        type="button"
        onClick={onClose}
        aria-label="Dismiss"
        className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
      >
        ✕
      </button>
    </div>
  );
}
