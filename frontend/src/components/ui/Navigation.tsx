import { useId, useRef, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";

export interface TabDefinition {
  id: string;
  label: string;
  content: ReactNode;
  disabled?: boolean;
}

export interface TabsProps {
  label: string;
  tabs: readonly TabDefinition[];
  /** Initially selected tab id. Defaults to the first enabled tab. */
  defaultTab?: string;
}

/**
 * Tabs following the WAI-ARIA tabs pattern. Arrow keys move and activate, Home and End jump. Only the selected tab is in the
 * tab order. Disabled tabs are skipped.
 */
export function Tabs({ label, tabs, defaultTab }: TabsProps) {
  const enabled = tabs.filter((tab) => !tab.disabled);
  const [selected, setSelected] = useState(defaultTab ?? enabled[0]?.id ?? "");
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const baseId = useId();

  function select(id: string) {
    setSelected(id);
    refs.current[id]?.focus();
  }

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = enabled.findIndex((tab) => tab.id === selected);
    if (event.key === "ArrowRight") select(enabled[(index + 1) % enabled.length].id);
    else if (event.key === "ArrowLeft") select(enabled[(index - 1 + enabled.length) % enabled.length].id);
    else if (event.key === "Home") select(enabled[0].id);
    else if (event.key === "End") select(enabled[enabled.length - 1].id);
    else return;
    event.preventDefault();
  }

  const active = tabs.find((tab) => tab.id === selected);

  return (
    <div className="df-tabs">
      <div role="tablist" aria-label={label} className="df-tablist" onKeyDown={onKeyDown}>
        {tabs.map((tab) => {
          const isSelected = tab.id === selected;
          return (
            <button
              key={tab.id}
              ref={(node) => {
                refs.current[tab.id] = node;
              }}
              id={`${baseId}-tab-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={isSelected}
              aria-controls={`${baseId}-panel`}
              tabIndex={isSelected ? 0 : -1}
              disabled={tab.disabled}
              className="df-tab"
              onClick={() => setSelected(tab.id)}
            >
              {tab.label}
            </button>
          );
        })}
      </div>
      <div
        id={`${baseId}-panel`}
        role="tabpanel"
        aria-labelledby={`${baseId}-tab-${selected}`}
        tabIndex={0}
        className="df-tabpanel"
      >
        {active?.content}
      </div>
    </div>
  );
}
