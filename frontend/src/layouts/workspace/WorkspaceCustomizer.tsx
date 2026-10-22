
import {
  Check,
  GripVertical,
  PanelLeftClose,
  PanelLeftOpen,
  RotateCcw,
  X,
} from "lucide-react";

import type {
  WorkspacePreferences,
} from "./workspacePreferences";

interface WorkspaceCustomizerProps {
  open: boolean;
  preferences: WorkspacePreferences;
  availableModules: string[];
  onClose: () => void;
  onChange: (preferences: WorkspacePreferences) => void;
  onReset: () => void;
}

export default function WorkspaceCustomizer({
  open,
  preferences,
  availableModules,
  onClose,
  onChange,
  onReset,
}: WorkspaceCustomizerProps) {
  if (!open) {
    return null;
  }

  function update(
    changes: Partial<WorkspacePreferences>,
  ) {
    onChange({
      ...preferences,
      ...changes,
    });
  }

  function toggleHidden(module: string) {
    const hidden = new Set(preferences.hiddenModules);

    if (hidden.has(module)) {
      hidden.delete(module);
    } else {
      hidden.add(module);
    }

    update({ hiddenModules: [...hidden] });
  }

  function moveModule(module: string, direction: -1 | 1) {
    const order = [...preferences.navigationOrder];
    const currentIndex = order.indexOf(module);

    if (currentIndex < 0) return;

    const nextIndex = currentIndex + direction;

    if (nextIndex < 0 || nextIndex >= order.length) return;

    [order[currentIndex], order[nextIndex]] = [
      order[nextIndex],
      order[currentIndex],
    ];

    update({ navigationOrder: order });
  }

  return (
    <div
      className="workspace-customizer-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        className="workspace-customizer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="workspace-customizer-title"
      >
        <header className="workspace-customizer-header">
          <div>
            <h2 id="workspace-customizer-title">
              Customize workspace
            </h2>
            <p>
              Arrange your workspace to suit the way you work.
            </p>
          </div>

          <button
            type="button"
            className="icon-button"
            aria-label="Close customization"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>

        <div className="workspace-customizer-body">
          <section className="workspace-setting-section">
            <h3>Sidebar</h3>

            <button
              type="button"
              className="workspace-setting-row"
              onClick={() =>
                update({
                  sidebarCollapsed: !preferences.sidebarCollapsed,
                })
              }
            >
              {preferences.sidebarCollapsed ? (
                <PanelLeftOpen size={18} />
              ) : (
                <PanelLeftClose size={18} />
              )}

              <span>
                <strong>Collapse sidebar</strong>
                <small>
                  Keep more room for your records and dashboards.
                </small>
              </span>

              <span
                className={`workspace-toggle ${
                  preferences.sidebarCollapsed ? "is-on" : ""
                }`}
                aria-hidden="true"
              >
                <span />
              </span>
            </button>
          </section>

          <section className="workspace-setting-section">
            <h3>Navigation modules</h3>
            <p className="workspace-setting-description">
              Hide optional modules and arrange the order. Access
              permissions are not changed by these preferences.
            </p>

            <div className="workspace-module-list">
              {availableModules.map((module) => {
                const hidden =
                  preferences.hiddenModules.includes(module);

                const index =
                  preferences.navigationOrder.indexOf(module);

                return (
                  <div
                    className="workspace-module-row"
                    key={module}
                  >
                    <GripVertical
                      size={16}
                      className="workspace-module-grip"
                      aria-hidden="true"
                    />

                    <span className="workspace-module-name">
                      {module}
                    </span>

                    <button
                      type="button"
                      className="workspace-order-button"
                      aria-label={`Move ${module} up`}
                      disabled={index <= 0}
                      onClick={() => moveModule(module, -1)}
                    >
                      ↑
                    </button>

                    <button
                      type="button"
                      className="workspace-order-button"
                      aria-label={`Move ${module} down`}
                      disabled={
                        index < 0 ||
                        index >=
                          preferences.navigationOrder.length - 1
                      }
                      onClick={() => moveModule(module, 1)}
                    >
                      ↓
                    </button>

                    <button
                      type="button"
                      className={`workspace-module-visibility ${
                        hidden ? "" : "is-visible"
                      }`}
                      aria-label={
                        hidden
                          ? `Show ${module}`
                          : `Hide ${module}`
                      }
                      aria-pressed={!hidden}
                      onClick={() => toggleHidden(module)}
                    >
                      {!hidden && <Check size={16} />}
                    </button>
                  </div>
                );
              })}
            </div>
          </section>

          <section className="workspace-setting-section">
            <h3>Table density</h3>

            <div className="workspace-density-options">
              {(
                [
                  ["comfortable", "Comfortable"],
                  ["compact", "Compact"],
                ] as const
              ).map(([value, label]) => (
                <button
                  type="button"
                  key={value}
                  className={`workspace-density-option ${
                    preferences.tableDensity === value
                      ? "is-selected"
                      : ""
                  }`}
                  aria-pressed={
                    preferences.tableDensity === value
                  }
                  onClick={() =>
                    update({ tableDensity: value })
                  }
                >
                  <span className={`density-preview ${value}`}>
                    <span />
                    <span />
                    <span />
                  </span>
                  <span>{label}</span>
                </button>
              ))}
            </div>
          </section>
        </div>

        <footer className="workspace-customizer-footer">
          <button
            type="button"
            className="button button-secondary"
            onClick={onReset}
          >
            <RotateCcw size={15} />
            Reset preferences
          </button>

          <button
            type="button"
            className="button button-primary"
            onClick={onClose}
          >
            Done
          </button>
        </footer>
      </section>
    </div>
  );
}
