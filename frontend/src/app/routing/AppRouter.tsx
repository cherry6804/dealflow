
import { Navigate, Route, Routes } from "react-router-dom";

import RequireAuth from "../guards/RequireAuth";
import PublicOnly from "../guards/PublicOnly";

import PublicLayout from "../../layouts/PublicLayout";
import WorkspaceLayout from "../../layouts/WorkspaceLayout";

import LoginPage from "../../features/auth/pages/LoginPage";
import SignupPage from "../../features/auth/pages/SignupPage";
import ForgotPasswordPage from "../../features/auth/pages/ForgotPasswordPage";
import ResetPasswordPage from "../../features/auth/pages/ResetPasswordPage";
import OnboardingPage from "../../features/onboarding/pages/OnboardingPage";

import TodayPage from "../../pages/TodayPage";
import LeadsPage from "../../pages/LeadsPage";
import ContactsPage from "../../pages/ContactsPage";
import CustomersPage from "../../pages/CustomersPage";
import RequirementsPage from "../../pages/RequirementsPage";
import PipelinePage from "../../pages/PipelinePage";
import DealsPage from "../../pages/DealsPage";
import ReferralsPage from "../../pages/ReferralsPage";
import PropertiesPage from "../../pages/PropertiesPage";
import SiteVisitsPage from "../../pages/SiteVisitsPage";
import ImportsPage from "../../pages/ImportsPage";
import DocumentsPage from "../../pages/DocumentsPage";
import AutomationRulesPage from "../../pages/AutomationRulesPage";
import AutomationHistoryPage from "../../pages/AutomationExecutionHistoryPage";
import NotificationPreferencesPage from "../../pages/NotificationPreferencesPage";

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
          DEALFLOW WORKSPACE
        </span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
    </section>
  );
}

export default function AppRouter() {
  return (
    <Routes>
      {/* Public pages */}
      <Route element={<PublicLayout />}>
        <Route element={<PublicOnly />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/signup" element={<SignupPage />} />
        </Route>

        {/* Password recovery remains accessible without an active session. */}
        <Route
          path="/forgot-password"
          element={<ForgotPasswordPage />}
        />
        <Route
          path="/reset-password"
          element={<ResetPasswordPage />}
        />
      </Route>

      {/* Authenticated workspace */}
      <Route element={<RequireAuth />}>
        <Route element={<WorkspaceLayout />}>
          <Route index element={<TodayPage />} />

          {/* Getting started */}
          <Route path="/onboarding" element={<OnboardingPage />} />

          {/* CRM */}
          <Route path="/leads" element={<LeadsPage />} />
          <Route path="/contacts" element={<ContactsPage />} />
          <Route path="/customers" element={<CustomersPage />} />
          <Route path="/requirements" element={<RequirementsPage />} />
          <Route path="/pipeline" element={<PipelinePage />} />
          <Route path="/deals" element={<DealsPage />} />
          <Route path="/referrals" element={<ReferralsPage />} />
          <Route path="/properties" element={<PropertiesPage />} />
          <Route path="/site-visits" element={<SiteVisitsPage />} />

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

          {/* Additional modules — replace placeholders as features are built */}
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

          <Route
            path="/billing"
            element={
              <ModulePlaceholder
                title="Billing"
                description="Manage your subscription, invoices, and billing details."
              />
            }
          />

          <Route
            path="/settings"
            element={
              <ModulePlaceholder
                title="Settings"
                description="Configure your workspace, organization, and account preferences."
              />
            }
          />

          {/* Unknown workspace routes */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Route>

      {/* Unknown public routes */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
