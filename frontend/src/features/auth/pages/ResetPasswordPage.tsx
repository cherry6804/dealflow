
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../../../lib/api";
import { authApi } from "../../../services/authApi";

export default function ResetPasswordPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get("token")?.trim() ?? "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (!token) {
      setError("This password-reset link is invalid or has expired.");
      return;
    }

    if (password.length < 12 || password.length > 128) {
      setError("Your password must contain between 12 and 128 characters.");
      return;
    }

    if (password !== confirmPassword) {
      setError("The passwords do not match.");
      return;
    }

    setSubmitting(true);

    try {
      await authApi.confirmPasswordReset({
        token,
        new_password: password,
      });

      navigate("/login", {
        replace: true,
        state: {
          notice:
            "Your password has been reset. Please sign in with your new password.",
        },
      });
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Unable to reset your password. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section
        className="auth-card"
        aria-labelledby="reset-password-heading"
      >
        <Link to="/login" className="auth-brand">
          <span className="brand-mark" aria-hidden="true">
            D
          </span>
          <span className="brand-copy">
            <span className="brand-name">DealFlow</span>
            <span className="brand-subtitle">
              Real estate workspace
            </span>
          </span>
        </Link>

        <div className="auth-heading">
          <span className="page-eyebrow">ACCOUNT RECOVERY</span>
          <h1 id="reset-password-heading">Set a new password</h1>
          <p>
            Choose a new password for your DealFlow account.
          </p>
        </div>

        {!token && (
          <div className="feedback feedback-error" role="alert">
            This password-reset link is invalid or has expired.
            Request a new link to continue.
          </div>
        )}

        {error && (
          <div className="feedback feedback-error" role="alert">
            {error}
          </div>
        )}

        {token && (
          <form className="auth-form" onSubmit={handleSubmit}>
            <label className="form-field">
              <span className="form-label">New password</span>
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={12}
                maxLength={128}
                required
                disabled={submitting}
              />
              <span className="form-hint">
                Use between 12 and 128 characters.
              </span>
            </label>

            <label className="form-field">
              <span className="form-label">Confirm new password</span>
              <input
                className="input"
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) =>
                  setConfirmPassword(event.target.value)
                }
                minLength={12}
                maxLength={128}
                required
                disabled={submitting}
              />
            </label>

            <button
              className="button button-primary button-lg button-block"
              type="submit"
              disabled={submitting}
            >
              {submitting ? "Resetting password..." : "Reset password"}
            </button>
          </form>
        )}

        <p className="auth-footnote">
          Need a new reset link?{" "}
          <Link to="/forgot-password">Request one</Link>
        </p>

        <p className="auth-footnote">
          <Link to="/login">Back to sign in</Link>
        </p>
      </section>
    </main>
  );
}
