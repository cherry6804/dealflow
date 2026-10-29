
import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import RequireAuth from "../guards/RequireAuth";

import PublicLayout from "../../layouts/PublicLayout";
import WorkspaceLayout from "../../layouts/WorkspaceLayout";

// Authentication pages
const BillingAccessPage = lazy(
  () => import("../../features/billing/pages/BillingAccessPage"),
);
const SibvoSignInRedirectPage = lazy(
  () => import("../../features/auth/pages/SibvoSignInRedirectPage"),
);
const SignupRoutePage = lazy(
  () => import("../../features/auth/pages/SignupRoutePage"),
);
const VerifyEmailPage = lazy(
  () => import("../../features/auth/pages/VerifyEmailPage"),
);
const ForgotPasswordPage = lazy(
  () => import("../../features/auth/pages/ForgotPasswordPage"),
);
const ResetPasswordPage = lazy(
  () => import("../../features/auth/pages/ResetPasswordPage"),
);

// SIBVO single sign-on callback
const SsoCallbackPage = lazy(
  () => import("../../features/auth/pages/SsoCallbackPage"),
);

// Public next step when SIBVO denies Dealsflo access
const AccessRequiredPage = lazy(
  () => import("../../features/auth/pages/AccessRequiredPage"),
);

// Onboarding
const OnboardingPage = lazy(
  () => import("../../features/onboarding/pages/OnboardingPage"),
);

// CRM pages
const TodayPage = lazy(() => import("../../pages/TodayPage"));
const LeadsPage = lazy(() => import("../../pages/LeadsPage"));
const ContactsPage = lazy(() => import("../../pages/ContactsPage"));
const CustomersPage = lazy(() => import("../../pages/CustomersPage"));
const RequirementsPage = lazy(
  () => import("../../pages/RequirementsPage"),
);
const PipelinePage = lazy(() => import("../../pages/PipelinePage"));
const DealsPage = lazy(() => import("../../pages/DealsPage"));
const ReferralsPage = lazy(() => import("../../pages/ReferralsPage"));
const PropertiesPage = lazy(() => import("../../pages/PropertiesPage"));
const SiteVisitsPage = lazy(
  () => import("../../pages/SiteVisitsPage"),
);

// Operations
const ImportsPage = lazy(() => import("../../pages/ImportsPage"));
const DocumentsPage = lazy(() => import("../../pages/DocumentsPage"));
const AutomationRulesPage = lazy(
  () => import("../../pages/AutomationRulesPage"),
);
const AutomationHistoryPage = lazy(
  () => import("../../pages/AutomationExecutionHistoryPage"),
);
const NotificationPreferencesPage = lazy(
  () => import("../../pages/NotificationPreferencesPage"),
);

// Team and invitations
const TeamAccessPage = lazy(
  () => import("../../features/settings/pages/TeamAccessPage"),
);
const AcceptInvitationPage = lazy(
  () => import("../../pages/AcceptInvitationPage"),
);

function PageLoadingFallback() {
  return (
    <div
      className="module-placeholder"
      role="status"
      aria-live="polite"
      aria-label="Loading page"
    >
      <div className="module-placeholder__content">
        <span className="module-placeholder__eyebrow">
          DEALSFLO WORKSPACE
        </span>
        <p>Loading page...</p>
      </div>
    </div>
  );
}

function ModulePlaceholder({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <section className="module-placeholder">
      <div className="module-placeholder__content">
        <span className="module-placeholder__eyebrow">
          DEALSFLO WORKSPACE
        </span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
    </section>
  );
}

export default function AppRouter() {
  return (
    <Suspense fallback={<PageLoadingFallback />}>
      <Routes>
        {/* SIBVO SSO callback: must be accessible before Dealsflo sign-in */}
        <Route
          path="/sso/callback"
          element={<SsoCallbackPage />}
        />

        {/* Public authentication pages */}
        <Route element={<PublicLayout />}>
          <Route path="/login" element={<SibvoSignInRedirectPage />} />
          <Route path="/signup" element={<SignupRoutePage />} />
          <Route
            path="/access-required"
            element={<AccessRequiredPage />}
          />

          <Route
            path="/verify-email"
            element={<VerifyEmailPage />}
          />

          <Route
            path="/forgot-password"
            element={<ForgotPasswordPage />}
          />

          <Route
            path="/reset-password"
            element={<ResetPasswordPage />}
          />
        </Route>

        {/* Invitation links must work before sign-in */}
        <Route
          path="/accept-invitation"
          element={<AcceptInvitationPage />}
        />

        {/* Authenticated workspace */}
        <Route element={<RequireAuth />}>
          <Route element={<WorkspaceLayout />}>
            <Route index element={<TodayPage />} />

            {/* Getting started */}
            <Route
              path="/onboarding"
              element={<OnboardingPage />}
            />

            {/* CRM */}
            <Route path="/leads" element={<LeadsPage />} />
            <Route path="/contacts" element={<ContactsPage />} />
            <Route path="/customers" element={<CustomersPage />} />
            <Route
              path="/requirements"
              element={<RequirementsPage />}
            />
            <Route path="/pipeline" element={<PipelinePage />} />
            <Route path="/deals" element={<DealsPage />} />
            <Route
              path="/properties"
              element={<PropertiesPage />}
            />
            <Route path="/referrals" element={<ReferralsPage />} />
            <Route
              path="/site-visits"
              element={<SiteVisitsPage />}
            />

            {/* Operations */}
            <Route path="/imports" element={<ImportsPage />} />
            <Route path="/documents" element={<DocumentsPage />} />

            <Route
              path="/automation-rules"
              element={<AutomationRulesPage />}
            />

            <Route
              path="/automation-history"
              element={<AutomationHistoryPage />}
            />

            <Route
              path="/notification-preferences"
              element={<NotificationPreferencesPage />}
            />

            {/* Organization and team settings */}
            <Route path="/settings" element={<TeamAccessPage />} />

            {/* Modules not yet implemented */}
            <Route
              path="/follow-ups"
              element={
                <ModulePlaceholder
                  title="Follow-ups"
                  description="Manage upcoming follow-ups, overdue activities, and customer reminders."
                />
              }
            />

            <Route
              path="/commissions"
              element={
                <ModulePlaceholder
                  title="Commissions"
                  description="Track proposed, agreed, and paid deal commissions."
                />
              }
            />

            <Route path="/billing" element={<BillingAccessPage />} />

            {/* Unknown workspace routes */}
            <Route
              path="*"
              element={<Navigate to="/" replace />}
            />
          </Route>
        </Route>

        {/* Unknown public routes */}
        <Route
          path="*"
          element={<Navigate to="/" replace />}
        />
      </Routes>
    </Suspense>
  );
}
