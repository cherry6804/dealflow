import { Monitor, Moon, Sun } from "lucide-react";
import type { KeyboardEvent } from "react";

import type { ThemePreference } from "./theme";
import { useTheme } from "./useTheme";

const OPTIONS: { value: ThemePreference; label: string; Icon: typeof Sun }[] = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
];

/**
 * Three-way theme choice as a radio group. Arrow keys move the selection, as the WAI-ARIA radio group
 * pattern requires. The note under the control says the choice is kept on this device only.
 */
export function ThemeToggle() {
  const { preference, setPreference, persisted } = useTheme();

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const index = OPTIONS.findIndex((option) => option.value === preference);
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const step = event.key === "ArrowRight" ? 1 : -1;
    const next = OPTIONS[(index + step + OPTIONS.length) % OPTIONS.length];
    setPreference(next.value);
    document.getElementById(`theme-option-${next.value}`)?.focus();
  }

  return (
    <div className="df-theme-toggle">
      <div role="radiogroup" aria-label="Colour theme" className="df-theme-toggle-group" onKeyDown={onKeyDown}>
        {OPTIONS.map(({ value, label, Icon }) => {
          const selected = preference === value;
          return (
            <button
              key={value}
              id={`theme-option-${value}`}
              type="button"
              role="radio"
              aria-checked={selected}
              tabIndex={selected ? 0 : -1}
              className="df-theme-toggle-option"
              onClick={() => setPreference(value)}
              title={`${label} theme`}
            >
              <Icon size={14} aria-hidden="true" />
              <span className="df-visually-hidden">{label} theme</span>
            </button>
          );
        })}
      </div>
      {!persisted && (
        <p role="status" className="df-theme-toggle-note">
          Your browser would not remember this choice. It applies to this page only.
        </p>
      )}
    </div>
  );
}
