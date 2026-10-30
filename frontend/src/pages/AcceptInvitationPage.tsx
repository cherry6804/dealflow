
import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { AlertCircle, Mail, ShieldCheck } from "lucide-react";

import { ApiError, api } from "../lib/api";
import "./AcceptInvitationPage.css";

export default function AcceptInvitationPage() {
  const [searchParams] = useSearchParams();

  const token = searchParams.get("token")?.trim() ?? "";

  useEffect(() => {
    if (token) {
      window.history.replaceState({}, document.title, "/accept-invitation");
    }
  }, [token]);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleAccept(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!token || submitting) return;

    setSubmitting(true);
    setError(null);

    try {
      const result = await api.post<{ authorization_url: string }>(
        "/sso/start-invitation",
        { token },
      );
      window.location.assign(result.authorization_url);
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
        <span className="accept-invitation__icon">
          <ShieldCheck size={24} />
        </span>

        <span className="accept-invitation__eyebrow">
          WORKSPACE INVITATION
        </span>

        <h1>Join your team</h1>

        <p>
          Join the existing workspace using the secure invitation sent to your email address.
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

        {token && (
          <>
            <form onSubmit={handleAccept}>
              <button
                className="accept-invitation__button"
                type="submit"
                disabled={submitting}
              >
                {submitting ? "Connecting to SIBVO…" : "Continue with SIBVO"}
              </button>
            </form>
          </>
        )}

        <div className="accept-invitation__hint">
          <Mail size={16} />
          <span>
            Sign in to SIBVO with the verified email address that received the
            invitation. Your Dealsflo role comes from the workspace invitation.
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
