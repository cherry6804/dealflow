
import {
  ArrowRight,
  Building2,
  CheckCircle2,
  Circle,
  ClipboardList,
  Home,
  RefreshCw,
  Users,
} from "lucide-react";
import { Navigate, useNavigate } from "react-router-dom";
import { useCallback, useEffect, useRef, useState } from "react";

import { useAppContext } from "../../../contexts/useAppContext";
import { leadsApi } from "../../../services/leadApi";
import { propertiesApi } from "../../../services/propertyApi";

interface ChecklistData {
  leadsTotal: number;
  propertiesTotal: number;
}

type LoadState = "loading" | "loaded" | "error";

export default function OnboardingPage() {
  const { user, selectedOrganization, organizations, status } = useAppContext();
  const navigate = useNavigate();
  const requestId = useRef(0);

  const [data, setData] = useState<ChecklistData>({
    leadsTotal: 0,
    propertiesTotal: 0,
  });
  const [loadState, setLoadState] = useState<LoadState>("loading");

  const organizationId = selectedOrganization?.id;

  const loadChecklist = useCallback(async () => {
    const currentRequestId = ++requestId.current;

    if (!organizationId) {
      setLoadState("error");
      return;
    }

    setLoadState("loading");

    try {
      const [leads, properties] = await Promise.all([
        leadsApi.list({ page: 1, page_size: 1 }),
        propertiesApi.search({ page: 1, page_size: 1 }),
      ]);

      if (currentRequestId !== requestId.current) {
        return;
      }

      setData({
        leadsTotal: leads.total,
        propertiesTotal: properties.total,
      });
      setLoadState("loaded");
    } catch {
      if (currentRequestId === requestId.current) {
        setLoadState("error");
      }
    }
  }, [organizationId]);

  useEffect(() => {
    void loadChecklist();

    return () => {
      requestId.current += 1;
    };
  }, [loadChecklist]);

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

  const checklist = [
    {
      id: "account",
      title: "Account ready",
      description: "Your account is signed in and ready to use.",
      complete: true,
      icon: Users,
      actionLabel: "Complete",
      path: null,
    },
    {
      id: "workspace",
      title: "Connect to your workspace",
      description: "Your organization is selected and ready.",
      complete: true,
      icon: Building2,
      actionLabel: "Complete",
      path: null,
    },
    {
      id: "lead",
      title: "Add your first lead",
      description: "Start tracking a potential buyer, seller, or enquiry.",
      complete: loadState === "loaded" && data.leadsTotal > 0,
      icon: ClipboardList,
      actionLabel: "Open leads",
      path: "/leads",
    },
    {
      id: "property",
      title: "Add your first property",
      description: "Build your inventory so your team can track properties.",
      complete: loadState === "loaded" && data.propertiesTotal > 0,
      icon: Home,
      actionLabel: "Open properties",
      path: "/properties",
    },
  ];

  const completedCount = checklist.filter((item) => item.complete).length;
  const progress = Math.round((completedCount / checklist.length) * 100);

  return (
    <main className="auth-page">
      <section className="auth-card onboarding-card">
        <span className="onboarding-success-icon">
          <Building2 size={30} />
        </span>

        <span className="page-eyebrow">GETTING STARTED</span>
        <h1>Welcome to DealFlow, {user.display_name}!</h1>
        <p>
          Your workspace is ready. Complete these first steps to get your real
          estate business organized.
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

        <section aria-labelledby="onboarding-progress-title">
          <div className="onboarding-progress-heading">
            <strong id="onboarding-progress-title">Workspace setup</strong>
            <span>
              {loadState === "loading"
                ? "Checking progress..."
                : loadState === "error"
                  ? "Progress unavailable"
                  : `${completedCount} of ${checklist.length} complete`}
            </span>
          </div>

          <div
            className="onboarding-progress-track"
            role="progressbar"
            aria-label="Workspace setup progress"
            aria-valuemin={0}
            aria-valuemax={checklist.length}
            aria-valuenow={completedCount}
          >
            <span style={{ width: `${progress}%` }} />
          </div>
        </section>

        {loadState === "error" && (
          <div className="onboarding-load-error" role="alert">
            <p>
              We couldn't verify your lead and property setup. Your progress
              may be out of date.
            </p>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void loadChecklist()}
            >
              <RefreshCw size={16} /> Try again
            </button>
          </div>
        )}

        <ul className="onboarding-checklist">
          {checklist.map((item) => {
            const Icon = item.icon;
            const completed = item.complete;

            return (
              <li
                key={item.id}
                className={completed ? "is-complete" : "is-pending"}
              >
                <span className="onboarding-checklist-status">
                  {completed ? (
                    <CheckCircle2 size={19} />
                  ) : (
                    <Circle size={19} />
                  )}
                </span>

                <span className="onboarding-checklist-copy">
                  <strong>{item.title}</strong>
                  <small>{item.description}</small>
                </span>

                {item.path && (
                  <button
                    type="button"
                    className="onboarding-checklist-action"
                    onClick={() => navigate(item.path!)}
                    aria-label={`${item.actionLabel}: ${item.title}`}
                  >
                    <Icon size={17} />
                    <span>{item.actionLabel}</span>
                  </button>
                )}
              </li>
            );
          })}
        </ul>

        <button
          type="button"
          className="button button-primary button-lg button-block"
          onClick={() => navigate("/", { replace: true })}
        >
          Go to workspace <ArrowRight size={18} />
        </button>
      </section>
    </main>
  );
}
