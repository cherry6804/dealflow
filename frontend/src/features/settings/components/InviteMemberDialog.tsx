
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Mail, UserPlus, X } from "lucide-react";

import type { TeamRole } from "../../../services/teamApi";

interface InviteMemberDialogProps {
  open: boolean;
  roles: TeamRole[];
  submitting: boolean;
  onClose: () => void;
  onSubmit: (email: string, roleId: string) => Promise<void>;
}

export default function InviteMemberDialog({
  open,
  roles,
  submitting,
  onClose,
  onSubmit,
}: InviteMemberDialogProps) {
  const [email, setEmail] = useState("");
  const [roleId, setRoleId] = useState("");
  const [validationError, setValidationError] = useState<string | null>(null);
  const emailInputRef = useRef<HTMLInputElement>(null);
  const onCloseRef = useRef(onClose);
  const submittingRef = useRef(submitting);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    submittingRef.current = submitting;
  }, [submitting]);

  useEffect(() => {
    if (!open) return;

    setEmail("");
    setValidationError(null);
    setRoleId(roles[0]?.id ?? "");

    const frame = window.requestAnimationFrame(() => {
      emailInputRef.current?.focus();
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
  }, [open]);

  useEffect(() => {
    if (!roleId || !roles.some((role) => role.id === roleId)) {
      setRoleId(roles[0]?.id ?? "");
    }
  }, [roles, roleId]);

  if (!open) return null;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (submitting) return;

    setValidationError(null);

    const normalizedEmail = email.trim().toLowerCase();
    const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

    if (!emailPattern.test(normalizedEmail)) {
      setValidationError("Enter a valid email address.");
      return;
    }

    const selectedRole = roles.find((role) => role.id === roleId);

    if (!selectedRole) {
      setValidationError("Select an available workspace role.");
      return;
    }

    try {
      await onSubmit(normalizedEmail, selectedRole.id);
    } catch {
      setValidationError("The invitation could not be sent. Please try again.");
    }
  }

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
        aria-labelledby="ta-invite-title"
        aria-describedby="ta-invite-description"
      >
        <header className="ta-modal__header">
          <span className="ta-modal__icon">
            <UserPlus size={20} />
          </span>

          <button
            type="button"
            className="ta-icon-button"
            aria-label="Close invitation dialog"
            disabled={submitting}
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>

        <h2 id="ta-invite-title">Invite a teammate</h2>

        <p
          id="ta-invite-description"
          className="ta-modal__description"
        >
          Send an email invitation to join this workspace.
        </p>

        {validationError && (
          <p className="ta-form-error" role="alert">
            {validationError}
          </p>
        )}

        <form className="ta-form" onSubmit={handleSubmit}>
          <label className="ta-field">
            <span>Email address</span>
            <input
              ref={emailInputRef}
              type="email"
              name="email"
              autoComplete="email"
              placeholder="name@company.com"
              value={email}
              maxLength={320}
              required
              disabled={submitting}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>

          <label className="ta-field">
            <span>Workspace role</span>

            <select
              name="role"
              value={roleId}
              onChange={(event) => setRoleId(event.target.value)}
              required
              disabled={submitting || roles.length === 0}
            >
              <option value="">
                {roles.length === 0
                  ? "No assignable roles available"
                  : "Select a role"}
              </option>

              {roles.map((role) => (
                <option value={role.id} key={role.id}>
                  {role.name}
                </option>
              ))}
            </select>

            {roles.find((role) => role.id === roleId)?.description && (
              <small>
                {roles.find((role) => role.id === roleId)?.description}
              </small>
            )}
          </label>

          <div className="ta-invite-hint">
            <Mail size={16} />
            <span>
              The invitation expires after seven days. The recipient must
              accept it using the invited email address.
            </span>
          </div>

          <footer className="ta-modal__actions">
            <button
              type="button"
              className="ta-button ta-button--secondary"
              onClick={onClose}
              disabled={submitting}
            >
              Cancel
            </button>

            <button
              type="submit"
              className="ta-button ta-button--primary"
              disabled={
                submitting ||
                !email.trim() ||
                !roleId ||
                roles.length === 0
              }
            >
              {submitting ? (
                <>
                  <span className="ta-small-spinner" />
                  Sending…
                </>
              ) : (
                <>
                  <Mail size={15} />
                  Send invitation
                </>
              )}
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}
