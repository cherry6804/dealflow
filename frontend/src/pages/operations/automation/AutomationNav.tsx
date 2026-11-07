import { Link } from "react-router-dom";

export type AutomationSection = "rules" | "activity" | "workflows" | "approvals";

const SECTIONS: readonly { id: AutomationSection; label: string; to: string }[] = [
  { id: "rules", label: "Rules", to: "/automation-rules" },
  { id: "activity", label: "Activity", to: "/automation-history" },
  { id: "workflows", label: "Workflows", to: "/workflows" },
  { id: "approvals", label: "Approvals", to: "/approvals" },
];

/** Section links shared by the automation pages. The current section is marked for assistive technology. */
export function AutomationNav({ current }: { current: AutomationSection }) {
  return (
    <nav className="df-ops-subnav" aria-label="Automation sections">
      {SECTIONS.map((section) => (
        <Link
          key={section.id}
          to={section.to}
          className={`df-ops-subnav-link${section.id === current ? " df-ops-subnav-link--active" : ""}`}
          aria-current={section.id === current ? "page" : undefined}
        >
          {section.label}
        </Link>
      ))}
    </nav>
  );
}
