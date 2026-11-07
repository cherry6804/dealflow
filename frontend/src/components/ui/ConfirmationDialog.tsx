import { Button } from "./Button";
import { Dialog } from "./Overlays";

export interface ConfirmationDialogProps {
  open: boolean;
  title: string;
  /** Explains what will happen and whether it can be undone. */
  message: string;
  confirmLabel: string;
  cancelLabel?: string;
  /** Destructive actions use the danger style on the confirm button. */
  tone?: "default" | "danger";
  /** True while the confirmed action runs. Dismissal is blocked until it settles. */
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * A small confirmation before a consequential action. Cancel, Escape and the backdrop all leave the action undone. The confirm button is
 * the primary action, styled as danger for destructive actions.
 */
export function ConfirmationDialog({
  open,
  title,
  message,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "default",
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmationDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onCancel}
      title={title}
      closeLabel={`Close ${title.toLowerCase()}`}
      size="sm"
      busy={busy}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={tone === "danger" ? "danger" : "primary"} onClick={onConfirm} loading={busy}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      <p className="df-dialog-description-plain">{message}</p>
    </Dialog>
  );
}
