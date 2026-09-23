"use client";

import { ChangePasswordForm } from "@/components/shared/change-password-form";
import { Dialog } from "@/components/ui/dialog";

export function ChangePasswordModal({
  open,
  forced,
  onClose,
  onDone,
}: {
  open: boolean;
  forced: boolean;
  onClose: () => void;
  onDone: () => void;
}) {
  if (!open) return null;

  return (
    <Dialog
      onClose={forced ? undefined : onClose}
      closeOnBackdrop={!forced}
      ariaLabelledBy="change-password-title"
      overlayClassName="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      contentClassName="animate-rise w-full max-w-md rounded-2xl bg-card p-6 shadow-xl"
    >
      <h2 id="change-password-title" className="text-lg font-semibold text-foreground">
        {forced ? "Set a new password" : "Change your password"}
      </h2>
      <p className="mb-4 mt-1 text-sm text-muted-foreground">
        {forced
          ? "For your security, replace the temporary password your administrator set for you."
          : "Choose a new password for your account."}
      </p>
      <ChangePasswordForm
        forced={forced}
        onDone={onDone}
        onCancel={forced ? undefined : onClose}
      />
    </Dialog>
  );
}
