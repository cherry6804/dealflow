import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";

import { ApiError } from "../lib/api";
import { authApi } from "../services/authApi";
import { useAppContext } from "../contexts/useAppContext";

export default function LoginPage() {
  const { status, user } = useAppContext();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "authenticated" && user) {
    return <Navigate to="/" replace />;
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      await authApi.login({
        email: email.trim(),
        password,
      });

      window.location.assign("/");
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
        <div className="auth-brand">
          <span className="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 32 32" fill="none">
              <path
                d="M5 15.2 16 5l11 10.2"
                stroke="currentColor"
                strokeWidth="2.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M9 13.2V27h14V13.2M13 27v-8h6v8"
                stroke="currentColor"
                strokeWidth="2.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>

          <span className="brand-copy">
            <span className="brand-name">DealFlow</span>
            <span className="brand-subtitle">Real estate workspace</span>
          </span>
        </div>

        <div className="auth-heading">
          <span className="page-eyebrow">WELCOME BACK</span>
          <h1 id="login-heading">Sign in to DealFlow</h1>
          <p>Access your workspace and keep your business moving.</p>
        </div>

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
              name="email"
              autoComplete="username"
              placeholder="you@company.com"
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
              name="password"
              autoComplete="current-password"
              placeholder="Enter your password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              maxLength={128}
              disabled={submitting}
            />
          </label>

          <button
            className="button button-primary button-lg button-block"
            type="submit"
            disabled={submitting || status === "loading"}
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="auth-footnote">
          Secure access to your real estate workspace.
        </p>
      </section>
    </main>
  );
}