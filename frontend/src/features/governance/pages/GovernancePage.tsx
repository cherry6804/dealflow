import { useEffect, useState } from "react";

import { governanceApi, type GovernanceAccess } from "../../../services/governanceApi";
import CapabilitiesPanel from "../components/CapabilitiesPanel";
import PrivacyPanel from "../components/PrivacyPanel";
import UsagePanel from "../components/UsagePanel";
import "./GovernancePage.css";

type Section = "capabilities" | "usage" | "privacy";

export default function GovernancePage() {
  const [access, setAccess] = useState<GovernanceAccess | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [section, setSection] = useState<Section>("capabilities");

  useEffect(() => {
    let active = true;
    governanceApi
      .getAccess()
      .then((value) => {
        if (active) setAccess(value);
      })
      .catch((error: unknown) => {
        if (active) {
          setLoadError(
            error instanceof Error && error.message.trim()
              ? error.message
              : "Governance settings could not be loaded.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, []);

  if (loadError) {
    return (
      <main className="governance-page">
        <h1>AI and automation governance</h1>
        <p role="alert" className="governance-error">
          {loadError}
        </p>
      </main>
    );
  }
  if (access === null) {
    return (
      <main className="governance-page">
        <h1>AI and automation governance</h1>
        <p role="status">Loading governance settings…</p>
      </main>
    );
  }

  const tabs: { key: Section; label: string; visible: boolean }[] = [
    { key: "capabilities", label: "Capabilities", visible: access.capabilities_read },
    { key: "usage", label: "Usage and budgets", visible: access.usage_read },
    { key: "privacy", label: "Privacy and retention", visible: access.privacy_read },
  ];
  const visibleTabs = tabs.filter((tab) => tab.visible);

  if (visibleTabs.length === 0) {
    return (
      <main className="governance-page">
        <h1>AI and automation governance</h1>
        <p>You do not have permission to view governance settings. Ask an organization owner for access.</p>
      </main>
    );
  }

  const activeSection = visibleTabs.some((tab) => tab.key === section) ? section : visibleTabs[0].key;

  return (
    <main className="governance-page">
      <h1>AI and automation governance</h1>
      <div role="tablist" aria-label="Governance sections" className="governance-tabs">
        {visibleTabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            id={`governance-tab-${tab.key}`}
            aria-selected={activeSection === tab.key}
            aria-controls="governance-panel"
            onClick={() => setSection(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="governance-panel" aria-labelledby={`governance-tab-${activeSection}`}>
        {activeSection === "capabilities" ? <CapabilitiesPanel canManage={access.capabilities_manage} /> : null}
        {activeSection === "usage" ? <UsagePanel canManage={access.budgets_manage} /> : null}
        {activeSection === "privacy" ? <PrivacyPanel canManage={access.privacy_manage} /> : null}
      </div>
    </main>
  );
}
