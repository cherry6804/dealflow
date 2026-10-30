import { useEffect, useRef, useState, type FormEvent } from "react";
import { AlertTriangle, X } from "lucide-react";

export const REMOVAL_REASON_MAX_LENGTH = 500;

interface RemoveMemberDialogProps {
  open: boolean;
  memberName: string;
  submitting: boolean;
  /** Error from the last attempt. Shown so the user can retry without losing the reason. */
  error: string | null;
  onClose: () => void;
  onSubmit: (reason: string) => Promise<void>;
}

export default function RemoveMemberDialog(props: RemoveMemberDialogProps) {
  // The form mounts only while open, so each opening starts with an empty reason
  // and no state has to be reset inside an effect.
  if (!props.open) return null;
  return <RemoveMemberForm {...props} />;
}

function RemoveMemberForm({
  memberName,
  submitting,
  error,
  onClose,
  onSubmit,
}: Omit<RemoveMemberDialogProps, "open">) {
  const [reason, setReason] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const reasonInputRef = useRef<HTMLTextAreaElement>(null);
  const onCloseRef = useRef(onClose);
  const submittingRef = useRef(submitting);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    submittingRef.current = submitting;
  }, [submitting]);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      reasonInputRef.current?.focus();
    });

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !submittingRef.current) {
        onCloseRef.current();
      }
    }

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (submitting) return;

    const normalized = reason.trim();

    if (!normalized) {
      setValidationError("Enter a reason for removing this member.");
      return;
    }

    if (normalized.length > REMOVAL_REASON_MAX_LENGTH) {
      setValidationError(
        `The reason must be ${REMOVAL_REASON_MAX_LENGTH} characters or fewer.`,
      );
      return;
    }

    setValidationError(null);
    await onSubmit(normalized);
  }

  const shownError = validationError ?? error;

  return (
    <div
      className="ta-modal-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !submitting) {
          onClose();
        }
      }}
    >
      <section
        className="ta-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="ta-remove-title"
        aria-describedby="ta-remove-description"
      >
        <header className="ta-modal__header">
          <span className="ta-modal__icon">
            <AlertTriangle size={20} />
          </span>

          <button
            type="button"
            className="ta-icon-button"
            aria-label="Close removal dialog"
            disabled={submitting}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>

        <h2 id="ta-remove-title">Remove {memberName}?</h2>

        <p id="ta-remove-description" className="ta-modal__description">
          This removes their access to this workspace and releases their
          Dealsflo seat in SIBVO. Their SIBVO account is not deleted.
        </p>

        {shownError && (
          <p className="ta-form-error" role="alert">
            {shownError}
          </p>
        )}

        <form className="ta-form" onSubmit={handleSubmit}>
          <label className="ta-field">
            <span>Reason for removal</span>
            <textarea
              ref={reasonInputRef}
              name="reason"
              rows={3}
              value={reason}
              maxLength={REMOVAL_REASON_MAX_LENGTH + 100}
              aria-required="true"
              aria-invalid={validationError !== null}
              disabled={submitting}
              onChange={(event) => setReason(event.target.value)}
            />
            <small>
              Recorded in the workspace audit trail.{" "}
              {reason.trim().length}/{REMOVAL_REASON_MAX_LENGTH}
            </small>
          </label>

          <div className="ta-modal__actions">
            <button
              type="button"
              className="ta-button ta-button--secondary"
              disabled={submitting}
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="ta-button ta-button--danger"
              disabled={submitting}
            >
              {submitting ? "Waiting for SIBVO…" : "Remove member"}
            </button>
          </div>
        </form>
      </section>
    </div>
  );
}
