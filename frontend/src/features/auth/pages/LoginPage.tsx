
import { useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../../../lib/api";
import { authApi } from "../../../services/authApi";
import { useAppContext } from "../../../contexts/useAppContext";

interface LoginLocationState {
  from?: {
    pathname?: string;
  };
  notice?: string;
}

export default function LoginPage() {
  const { status, refreshSession } = useAppContext();
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const locationState = location.state as LoginLocationState | null;
  const destination = locationState?.from?.pathname;
  const notice = locationState?.notice;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      await authApi.login({
        email: email.trim(),
        password,
      });

      await refreshSession();
      navigate(destination || "/", { replace: true });
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.message
          : "Unable to sign in. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="login-heading">
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
          <span className="page-eyebrow">WELCOME BACK</span>
          <h1 id="login-heading">Sign in to DealFlow</h1>
          <p>
            Access your workspace and keep your business moving.
          </p>
        </div>

        {notice && (
          <div className="feedback feedback-success" role="status">
            {notice}
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
              autoComplete="username"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              required
              maxLength={320}
              disabled={submitting}
            />
          </label>

          <label className="form-field">
            <span className="form-label">Password</span>
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              maxLength={128}
              disabled={submitting}
            />
          </label>

          <p className="auth-footnote">
            <Link to="/forgot-password">Forgot your password?</Link>
          </p>

          <button
            className="button button-primary button-lg button-block"
            type="submit"
            disabled={submitting || status === "loading"}
          >
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="auth-footnote">
          New to DealFlow? <Link to="/signup">Create a workspace</Link>
        </p>
      </section>
    </main>
  );
}
