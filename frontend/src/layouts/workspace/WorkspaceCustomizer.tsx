
import {
  Check,
  ChevronDown,
  ChevronUp,
  Pin,
  PinOff,
  RotateCcw,
  X,
} from "lucide-react";

import type { WorkspacePreferences } from "./workspacePreferences";

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

  const orderedModules = [
    ...preferences.navigationOrder.filter((module) =>
      availableModules.includes(module),
    ),
    ...availableModules.filter(
      (module) => !preferences.navigationOrder.includes(module),
    ),
  ];

  function update(changes: Partial<WorkspacePreferences>) {
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

  function togglePinned(module: string) {
    const pinned = new Set(preferences.pinnedModules);

    if (pinned.has(module)) {
      pinned.delete(module);
    } else {
      pinned.add(module);
    }

    update({ pinnedModules: [...pinned] });
  }

  function moveModule(module: string, direction: -1 | 1) {
    const order = [...orderedModules];
    const currentIndex = order.indexOf(module);
    const nextIndex = currentIndex + direction;

    if (currentIndex < 0 || nextIndex < 0 || nextIndex >= order.length) {
      return;
    }

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
            <h2 id="workspace-customizer-title">Customize workspace</h2>
            <p>Arrange your workspace for the way your team works.</p>
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
              aria-pressed={preferences.sidebarCollapsed}
              onClick={() =>
                update({
                  sidebarCollapsed: !preferences.sidebarCollapsed,
                })
              }
            >
              <span>
                <strong>Collapse sidebar</strong>
                <small>Make more room for your records.</small>
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
              Reorder modules, pin frequently used pages, or hide optional
              links. These settings do not grant or revoke permissions.
            </p>

            <div className="workspace-module-list">
              {orderedModules.map((module, index) => {
                const hidden = preferences.hiddenModules.includes(module);
                const pinned = preferences.pinnedModules.includes(module);

                return (
                  <div className="workspace-module-row" key={module}>
                    <span className="workspace-module-name">{module}</span>

                    <button
                      type="button"
                      className="workspace-order-button"
                      aria-label={`Move ${module} up`}
                      disabled={index === 0}
                      onClick={() => moveModule(module, -1)}
                    >
                      <ChevronUp size={16} />
                    </button>

                    <button
                      type="button"
                      className="workspace-order-button"
                      aria-label={`Move ${module} down`}
                      disabled={index === orderedModules.length - 1}
                      onClick={() => moveModule(module, 1)}
                    >
                      <ChevronDown size={16} />
                    </button>

                    <button
                      type="button"
                      className={`workspace-order-button ${
                        pinned ? "is-pinned" : ""
                      }`}
                      aria-label={
                        pinned ? `Unpin ${module}` : `Pin ${module}`
                      }
                      aria-pressed={pinned}
                      onClick={() => togglePinned(module)}
                    >
                      {pinned ? <PinOff size={15} /> : <Pin size={15} />}
                    </button>

                    <button
                      type="button"
                      className={`workspace-module-visibility ${
                        hidden ? "" : "is-visible"
                      }`}
                      aria-label={hidden ? `Show ${module}` : `Hide ${module}`}
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
                    preferences.tableDensity === value ? "is-selected" : ""
                  }`}
                  aria-pressed={preferences.tableDensity === value}
                  onClick={() => update({ tableDensity: value })}
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
