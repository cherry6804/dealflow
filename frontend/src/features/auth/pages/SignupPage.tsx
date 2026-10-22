
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { ApiError } from "../../../lib/api";
import { useAppContext } from "../../../contexts/useAppContext";
import { authApi } from "../../../services/authApi";

export default function SignupPage() {
  const { status, refreshSession } = useAppContext();
  const navigate = useNavigate();

  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (password.length < 12 || password.length > 128) {
      setError("Your password must contain between 12 and 128 characters.");
      return;
    }

    if (password !== confirmPassword) {
      setError("Your passwords do not match.");
      return;
    }

    if (organizationName.trim().length < 2) {
      setError("Enter a workspace name with at least 2 characters.");
      return;
    }

    setSubmitting(true);

    try {
      const response = await authApi.signup({
        display_name: displayName.trim(),
        email: email.trim().toLowerCase(),
        organization_name: organizationName.trim(),
        password,
      });

      await refreshSession(response);
      navigate("/onboarding", { replace: true });
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

        <div className="auth-heading">
          <span className="page-eyebrow">GET STARTED</span>
          <h1 id="signup-heading">Create your workspace</h1>
          <p>Bring your leads, contacts, and deals together in one place.</p>
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

          <label className="form-field">
            <span className="form-label">Workspace name</span>
            <input
              className="input"
              name="organization_name"
              autoComplete="organization"
              placeholder="e.g. Skyline Realty"
              value={organizationName}
              onChange={(event) => setOrganizationName(event.target.value)}
              required
              minLength={2}
              maxLength={200}
              disabled={submitting}
            />
            <span className="form-hint">
              Use your company or real estate agency name.
            </span>
          </label>

          <label className="form-field">
            <span className="form-label">Password</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              minLength={12}
              maxLength={128}
              disabled={submitting}
            />
          </label>

          <label className="form-field">
            <span className="form-label">Confirm password</span>
            <input
              className="input"
              type="password"
              autoComplete="new-password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              required
              minLength={12}
              maxLength={128}
              disabled={submitting}
            />
          </label>

          <button
            className="button button-primary button-lg button-block"
            type="submit"
            disabled={submitting || status === "loading"}
          >
            {submitting ? "Creating workspace…" : "Create workspace"}
          </button>
        </form>

        <p className="auth-footnote">
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
        <p className="auth-footnote">
          Your workspace is private to your organization.
        </p>
      </section>
    </main>
  );
}
