import { useId, useRef } from "react";
import type { InputHTMLAttributes, KeyboardEvent } from "react";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: string;
  /** Mixed state for a parent whose children are partly selected. */
  indeterminate?: boolean;
}

/** Native checkbox with a visible label. The indeterminate state is set on the DOM node, which React does not expose as a prop. */
export function Checkbox({ label, indeterminate = false, id, className, ...rest }: CheckboxProps) {
  const generated = useId();
  const inputId = id ?? `df-check-${generated}`;
  const ref = (node: HTMLInputElement | null) => {
    if (node) node.indeterminate = indeterminate;
  };
  return (
    <label className={`df-choice${className ? ` ${className}` : ""}`} htmlFor={inputId}>
      <input {...rest} ref={ref} id={inputId} type="checkbox" className="df-checkbox" />
      <span>{label}</span>
    </label>
  );
}

export interface RadioOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface RadioGroupProps {
  name: string;
  label: string;
  value: string;
  options: readonly RadioOption[];
  onChange: (value: string) => void;
  helper?: string;
}

/**
 * Radio group. Arrow keys move and select, as the WAI-ARIA radio pattern requires. Disabled options are skipped.
 */
export function RadioGroup({ name, label, value, options, onChange, helper }: RadioGroupProps) {
  const refs = useRef<Array<HTMLInputElement | null>>([]);
  const enabled = options.map((option, index) => ({ option, index })).filter(({ option }) => !option.disabled);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (!["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft"].includes(event.key)) return;
    event.preventDefault();
    const current = enabled.findIndex(({ option }) => option.value === value);
    const step = event.key === "ArrowDown" || event.key === "ArrowRight" ? 1 : -1;
    const next = enabled[(current + step + enabled.length) % enabled.length];
    if (!next) return;
    onChange(next.option.value);
    refs.current[next.index]?.focus();
  }

  return (
    <div role="radiogroup" aria-label={label} className="df-radio-group" onKeyDown={onKeyDown}>
      {options.map((option, index) => (
        <label key={option.value} className="df-choice">
          <input
            ref={(node) => {
              refs.current[index] = node;
            }}
            type="radio"
            name={name}
            value={option.value}
            checked={value === option.value}
            disabled={option.disabled}
            tabIndex={value === option.value ? 0 : -1}
            onChange={() => onChange(option.value)}
            className="df-radio"
          />
          <span>{option.label}</span>
        </label>
      ))}
      {helper ? <p className="df-field-helper">{helper}</p> : null}
    </div>
  );
}
