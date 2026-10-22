
import { CheckCircle2, ArrowRight, Building2 } from "lucide-react";
import { Navigate, useNavigate } from "react-router-dom";

import { useAppContext } from "../../../contexts/useAppContext";

export default function OnboardingPage() {
  const { user, selectedOrganization, organizations, status } = useAppContext();
  const navigate = useNavigate();

  if (status !== "authenticated" || !user) {
    return <Navigate to="/login" replace />;
  }

  if (organizations.length === 0 || !selectedOrganization) {
    return (
      <main className="auth-page">
        <section className="auth-card">
          <h1>Workspace unavailable</h1>
          <p>
            Your account is signed in, but no active workspace was returned.
            Please contact your administrator.
          </p>
        </section>
      </main>
    );
  }

  return (
    <main className="auth-page">
      <section className="auth-card onboarding-card">
        <span className="onboarding-success-icon">
          <CheckCircle2 size={32} />
        </span>

        <span className="page-eyebrow">YOU'RE ALL SET</span>
        <h1>Welcome to DealFlow, {user.display_name}!</h1>
        <p>
          Your account is ready. Your workspace has been created and is ready
          for you to start organizing your real estate business.
        </p>

        <div className="onboarding-workspace">
          <span className="onboarding-workspace-icon">
            <Building2 size={22} />
          </span>
          <span>
            <small>YOUR WORKSPACE</small>
            <strong>{selectedOrganization.name}</strong>
          </span>
          <CheckCircle2 size={19} />
        </div>

        <ul className="onboarding-checklist">
          <li><CheckCircle2 size={17} /> Account created</li>
          <li><CheckCircle2 size={17} /> Workspace connected</li>
          <li><CheckCircle2 size={17} /> Secure session established</li>
        </ul>

        <button
          className="button button-primary button-lg button-block"
          onClick={() => navigate("/", { replace: true })}
        >
          Continue to workspace <ArrowRight size={18} />
        </button>
      </section>
    </main>
  );
}
