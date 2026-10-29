import { ChevronDown, ChevronUp } from "lucide-react";

import "./GridColumnOptionList.css";

export interface GridColumnOptionItem {
  key: string;
  label: string;
  visible: boolean;
}

interface GridColumnOptionListProps {
  columnOptions: readonly GridColumnOptionItem[];
  onVisibilityChange: (key: string, visible: boolean) => void;
  onMove: (key: string, direction: -1 | 1) => void;
}

/**
 * Show/hide and reorder controls for a data grid's configurable columns. The
 * last visible column stays checked so a grid cannot end up with no columns.
 */
export default function GridColumnOptionList({
  columnOptions,
  onVisibilityChange,
  onMove,
}: GridColumnOptionListProps) {
  const visibleCount = columnOptions.filter((option) => option.visible).length;

  return (
    <ul className="grid-column-option-list">
      {columnOptions.map((option, index) => {
        const lastVisible = option.visible && visibleCount === 1;

        return (
          <li className="grid-column-option" key={option.key}>
            <label className="grid-column-option-label">
              <input
                type="checkbox"
                checked={option.visible}
                disabled={lastVisible}
                onChange={(event) =>
                  onVisibilityChange(option.key, event.target.checked)
                }
              />
              <span>{option.label}</span>
            </label>

            <span className="grid-column-option-actions">
              <button
                type="button"
                className="grid-column-move-button"
                aria-label={`Move ${option.label} up`}
                disabled={index === 0}
                onClick={() => onMove(option.key, -1)}
              >
                <ChevronUp size={14} aria-hidden="true" />
              </button>
              <button
                type="button"
                className="grid-column-move-button"
                aria-label={`Move ${option.label} down`}
                disabled={index === columnOptions.length - 1}
                onClick={() => onMove(option.key, 1)}
              >
                <ChevronDown size={14} aria-hidden="true" />
              </button>
            </span>
          </li>
        );
      })}
    </ul>
  );
}
