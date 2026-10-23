
import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";

import { ApiError } from "../../../lib/api";
import { authApi } from "../../../services/authApi";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage(null);
    setError(null);
    setSubmitting(true);

    try {
      const response = await authApi.requestPasswordReset({
        email: email.trim(),
      });
      setMessage(response.message);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Unable to submit your request. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section
        className="auth-card"
        aria-labelledby="forgot-password-heading"
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
          <h1 id="forgot-password-heading">
            Forgot your password?
          </h1>
          <p>
            Enter your email address. If your account is eligible,
            we’ll send you a password-reset link.
          </p>
        </div>

        {message && (
          <div className="feedback feedback-success" role="status">
            {message}
          </div>
        )}

        {error && (
          <div className="feedback feedback-error" role="alert">
            {error}
          </div>
        )}

        <form className="auth-form" onSubmit={handleSubmit}>
          <label className="form-field">
            <span className="form-label">Email address</span>
            <input
              className="input"
              type="email"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              maxLength={320}
              disabled={submitting}
            />
          </label>

          <button
            className="button button-primary button-lg button-block"
            type="submit"
            disabled={submitting}
          >
            {submitting ? "Submitting..." : "Send reset link"}
          </button>
        </form>

        <p className="auth-footnote">
          Remember your password? <Link to="/login">Sign in</Link>
        </p>
      </section>
    </main>
  );
}
