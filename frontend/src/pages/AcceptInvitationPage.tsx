
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AlertCircle, CheckCircle2, Mail, ShieldCheck } from "lucide-react";

import { ApiError } from "../lib/api";
import { useAppContext } from "../contexts/useAppContext";
import { teamApi } from "../services/teamApi";
import "./AcceptInvitationPage.css";

export default function AcceptInvitationPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { refreshSession } = useAppContext();

  const token = searchParams.get("token")?.trim() ?? "";
  const invitationPath = `/accept-invitation?${new URLSearchParams({
    token,
  }).toString()}`;
  const signInUrl = `/login?next=${encodeURIComponent(invitationPath)}`;
  const signupUrl = `/signup?invitation=${encodeURIComponent(token)}`;

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  async function handleAccept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!token || submitting) return;

    setSubmitting(true);
    setError(null);

    try {
      const result = await teamApi.acceptInvitation({ token });
      setSuccess(result.message || "Invitation accepted successfully.");

      await refreshSession();
      navigate("/", { replace: true });
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : cause instanceof Error
            ? cause.message
            : "Unable to accept this invitation. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="accept-invitation">
      <section className="accept-invitation__card">
        <span
          className={`accept-invitation__icon${
            success ? " accept-invitation__icon--success" : ""
          }`}
        >
          {success ? <CheckCircle2 size={24} /> : <ShieldCheck size={24} />}
        </span>

        <span className="accept-invitation__eyebrow">
          WORKSPACE INVITATION
        </span>

        <h1>{success ? "You're on the team" : "Join your team"}</h1>

        <p>
          {success
            ? success
            : "Join the existing workspace using the secure invitation sent to your email address."}
        </p>

        {!token && (
          <div className="accept-invitation__alert" role="alert">
            <AlertCircle size={17} />
            <span>
              This link is missing its invitation token. Open the complete link
              from your invitation email.
            </span>
          </div>
        )}

        {error && (
          <div className="accept-invitation__alert" role="alert">
            <AlertCircle size={17} />
            <span>{error}</span>
          </div>
        )}

        {!success && token && (
          <>
            <form onSubmit={handleAccept}>
              <button
                className="accept-invitation__button"
                type="submit"
                disabled={submitting}
              >
                {submitting ? "Accepting invitation..." : "Accept invitation"}
              </button>
            </form>

            <Link className="accept-invitation__button" to={signInUrl}>
              Sign in to accept
            </Link>

            <Link className="accept-invitation__button" to={signupUrl}>
              Create an account
            </Link>
          </>
        )}

        {success && (
          <Link className="accept-invitation__button" to="/">
            Continue to workspace
          </Link>
        )}

        <div className="accept-invitation__hint">
          <Mail size={16} />
          <span>
            Use the email address that received the invitation. Your access is
            determined by the role assigned by the workspace administrator.
          </span>
        </div>

        <p className="accept-invitation__footnote">
          Invitations expire after seven days and can only be accepted once.
          If the link is expired or revoked, ask the administrator to resend it.
        </p>
      </section>
    </main>
  );
}
