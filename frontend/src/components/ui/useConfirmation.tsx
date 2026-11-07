import { useCallback, useState, type ReactNode } from "react";

import { ConfirmationDialog } from "./ConfirmationDialog";

export interface ConfirmOptions {
  /** Short question, for example "Cancel this commission?". */
  title?: string;
  /** Label of the confirm button. Use the action's own verb. */
  confirmLabel?: string;
  /** Use "danger" for actions that cannot be undone or remove access. */
  tone?: "default" | "danger";
}

type Pending = { message: string; options: ConfirmOptions; resolve: (confirmed: boolean) => void };

/**
 * Promise-based confirmation for async handlers. Replaces window.confirm with the shared ConfirmationDialog without changing the
 * handler's flow:
 *
 *   const [confirm, confirmDialog] = useConfirmation();
 *   ...
 *   const confirmed = await confirm("Cancel this commission?", { tone: "danger", confirmLabel: "Cancel commission" });
 *   if (!confirmed) return;
 *
 * Render `confirmDialog` once in the component. Cancel, Escape and the backdrop resolve to false.
 */
export function useConfirmation(): readonly [(message: string, options?: ConfirmOptions) => Promise<boolean>, ReactNode] {
  const [pending, setPending] = useState<Pending | null>(null);

  const confirm = useCallback(
    (message: string, options: ConfirmOptions = {}) =>
      new Promise<boolean>((resolve) => {
        setPending({ message, options, resolve });
      }),
    [],
  );

  function settle(result: boolean) {
    pending?.resolve(result);
    setPending(null);
  }

  const dialog = (
    <ConfirmationDialog
      open={pending !== null}
      title={pending?.options.title ?? "Please confirm"}
      message={pending?.message ?? ""}
      confirmLabel={pending?.options.confirmLabel ?? "Confirm"}
      tone={pending?.options.tone ?? "default"}
      onConfirm={() => settle(true)}
      onCancel={() => settle(false)}
    />
  );

  return [confirm, dialog] as const;
}
