
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { authApi } from "../../../services/authApi";

type VerificationState = "verifying" | "success" | "error";

export default function VerifyEmailPage() {
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token")?.trim() ?? "";

  const [state, setState] = useState<VerificationState>("verifying");
  const [message, setMessage] = useState(
    "Please wait while we verify your email address.",
  );

  // Prevent duplicate requests during React Strict Mode effect replay.
  const requestStarted = useRef(false);

  useEffect(() => {
    if (requestStarted.current) {
      return;
    }

    requestStarted.current = true;

    if (!token) {
      setState("error");
      setMessage("The verification link is missing its token.");
      return;
    }

    let active = true;

    async function verifyEmail() {
      try {
        const result = await authApi.verifyEmail({ token });

        if (active) {
          setState("success");
          setMessage(
            result.message ||
              "Your email has been verified. You can now sign in.",
          );
        }
      } catch {
        if (active) {
          setState("error");
          setMessage(
            "This verification link is invalid or has expired. Request a new verification email and try again.",
          );
        }
      }
    }

    void verifyEmail();

    return () => {
      active = false;
    };
  }, [token]);

  return (
    <main
      style={{
        width: "min(100% - 32px, 460px)",
        margin: "64px auto",
        padding: "32px",
        border: "1px solid var(--border-color, #e5e7eb)",
        borderRadius: "16px",
        background: "var(--surface-color, #ffffff)",
        boxSizing: "border-box",
        textAlign: "center",
      }}
      aria-live="polite"
    >
      <h1 style={{ marginTop: 0 }}>
        {state === "verifying"
          ? "Verifying your email"
          : state === "success"
            ? "Email verified"
            : "Verification unsuccessful"}
      </h1>

      <p>{message}</p>

      {state === "verifying" && <p>Please keep this page open.</p>}

      {state === "success" && (
        <Link to="/login">Continue to sign in</Link>
      )}

      {state === "error" && (
        <p>
          <Link to="/signup">Return to signup</Link>
          {" · "}
          <Link to="/login">Go to sign in</Link>
        </p>
      )}
    </main>
  );
}
