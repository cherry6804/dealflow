
import { useState, type FormEvent } from "react";
import { CheckCircle2, Mail } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "../../../lib/api";
import { authApi } from "../../../services/authApi";

export default function SignupPage() {
  const [searchParams] = useSearchParams();
  const invitationToken = searchParams.get("invitation")?.trim() ?? "";
  const isInvitationSignup = invitationToken.length > 0;

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [verificationEmail, setVerificationEmail] = useState<string | null>(
    null,
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;

    setError(null);

    if (password.length < 12 || password.length > 128) {
      setError("Your password must contain between 12 and 128 characters.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Your passwords do not match.");
      return;
    }

    if (!isInvitationSignup && organizationName.trim().length < 2) {
      setError("Enter a workspace name with at least 2 characters.");
      return;
    }

    setSubmitting(true);

    const normalizedEmail = email.trim().toLowerCase();

    try {
      if (isInvitationSignup) {
        await authApi.signupFromInvitation({
          display_name: displayName.trim(),
          email: normalizedEmail,
          password,
          invitation_token: invitationToken,
        });
      } else {
        await authApi.signup({
          display_name: displayName.trim(),
          email: normalizedEmail,
          organization_name: organizationName.trim(),
          password,
        });
      }

      setVerificationEmail(normalizedEmail);
      setPassword("");
      setConfirmPassword("");
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Unable to create your account. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="signup-heading">
        <Link to="/login" className="auth-brand">
          <span className="brand-mark" aria-hidden="true">D</span>
          <span className="brand-copy">
            <span className="brand-name">DealFlow</span>
            <span className="brand-subtitle">Real estate workspace</span>
          </span>
        </Link>

        {verificationEmail ? (
          <div className="auth-heading">
            <span className="onboarding-success-icon" aria-hidden="true">
              <Mail size={32} />
            </span>
            <span className="page-eyebrow">ONE LAST STEP</span>
            <h1 id="signup-heading">Verify your email</h1>
            <p>
              Follow the verification link sent to
              {" "}
              <strong>{verificationEmail}</strong>.
            </p>
            <div className="feedback" role="status">
              <CheckCircle2 size={18} />
              Account registration submitted.
            </div>
            <p>
              After verification, sign in and open your invitation link again
              to join the workspace.
            </p>
            <Link
              to="/login"
              className="button button-primary button-lg button-block"
            >
              Continue to sign in
            </Link>
          </div>
        ) : (
          <>
            <div className="auth-heading">
              <span className="page-eyebrow">
                {isInvitationSignup ? "JOIN YOUR TEAM" : "GET STARTED"}
              </span>
              <h1 id="signup-heading">
                {isInvitationSignup
                  ? "Create your account"
                  : "Create your workspace"}
              </h1>
              <p>
                {isInvitationSignup
                  ? "Register using the email address that received your invitation."
                  : "Bring your leads, contacts, and deals together in one place."}
              </p>
            </div>

            {error && (
              <div className="feedback feedback-error" role="alert">
                {error}
              </div>
            )}

            <form className="auth-form" onSubmit={handleSubmit}>
              <label className="form-field">
                <span className="form-label">Full name</span>
                <input
                  className="input"
                  name="display_name"
                  autoComplete="name"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  required
                  maxLength={200}
                  disabled={submitting}
                />
              </label>

              <label className="form-field">
                <span className="form-label">Work email</span>
                <input
                  className="input"
                  type="email"
                  name="email"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                  maxLength={320}
                  disabled={submitting}
                />
              </label>

              {!isInvitationSignup && (
                <label className="form-field">
                  <span className="form-label">Workspace name</span>
                  <input
                    className="input"
                    name="organization_name"
                    autoComplete="organization"
                    placeholder="e.g. Skyline Realty"
                    value={organizationName}
                    onChange={(event) =>
                      setOrganizationName(event.target.value)
                    }
                    required
                    minLength={2}
                    maxLength={200}
                    disabled={submitting}
                  />
                </label>
              )}

              <label className="form-field">
                <span className="form-label">Password</span>
                <input
                  className="input"
                  type="password"
                  name="password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                  minLength={12}
                  maxLength={128}
                  disabled={submitting}
                />
                <span className="form-hint">
                  Use between 12 and 128 characters.
                </span>
              </label>

              <label className="form-field">
                <span className="form-label">Confirm password</span>
                <input
                  className="input"
                  type="password"
                  name="confirm_password"
                  autoComplete="new-password"
                  value={confirmPassword}
                  onChange={(event) =>
                    setConfirmPassword(event.target.value)
                  }
                  required
                  minLength={12}
                  maxLength={128}
                  disabled={submitting}
                />
              </label>

              <button
                className="button button-primary button-lg button-block"
                type="submit"
                disabled={submitting}
              >
                {submitting
                  ? "Creating account..."
                  : isInvitationSignup
                    ? "Create account"
                    : "Create workspace"}
              </button>
            </form>

            <p className="auth-footnote">
              Already have an account? <Link to="/login">Sign in</Link>
            </p>
          </>
        )}
      </section>
    </main>
  );
}
