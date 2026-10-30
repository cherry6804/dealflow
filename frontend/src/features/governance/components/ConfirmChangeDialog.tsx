import { useEffect, useId, useRef, type ReactNode } from "react";

interface ConfirmChangeDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  submitting: boolean;
  error: string | null;
  onConfirm: () => void;
  onCancel: () => void;
  children?: ReactNode;
}

/** Modal confirmation for a consequential governance change. Focus moves into the dialog. */
export default function ConfirmChangeDialog({
  open,
  title,
  description,
  confirmLabel,
  submitting,
  error,
  onConfirm,
  onCancel,
  children,
}: ConfirmChangeDialogProps) {
  const titleId = useId();
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (open) {
      confirmRef.current?.focus();
    }
  }, [open]);

  if (!open) return null;

  return (
    <div
      className="governance-dialog-backdrop"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !submitting) onCancel();
      }}
    >
      <div role="dialog" aria-modal="true" aria-labelledby={titleId} className="governance-dialog">
        <h2 id={titleId}>{title}</h2>
        <p>{description}</p>
        {children}
        {error ? (
          <p role="alert" className="governance-error">
            {error}
          </p>
        ) : null}
        <div className="governance-dialog-actions">
          <button type="button" onClick={onCancel} disabled={submitting}>
            Cancel
          </button>
          <button
            type="button"
            ref={confirmRef}
            onClick={onConfirm}
            disabled={submitting}
            className="governance-primary"
          >
            {submitting ? "Saving…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
