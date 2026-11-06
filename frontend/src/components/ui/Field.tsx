import { useId } from "react";
import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

interface FieldFrameProps {
  id: string;
  label: string;
  required?: boolean;
  helper?: string;
  error?: string;
  children: ReactNode;
  helperId: string;
  errorId: string;
}

/** Shared label, helper text and error layout for every field. Errors are text plus an icon-free mark. */
function FieldFrame({ id, label, required, helper, error, children, helperId, errorId }: FieldFrameProps) {
  return (
    <div className={`df-field${error ? " df-field--error" : ""}`}>
      <label className="df-field-label" htmlFor={id}>
        {label}
        {required ? <span className="df-field-required" aria-hidden="true"> *</span> : null}
      </label>
      {children}
      {helper && !error ? (
        <p id={helperId} className="df-field-helper">
          {helper}
        </p>
      ) : null}
      {error ? (
        <p id={errorId} className="df-field-error" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}

interface CommonFieldProps {
  label: string;
  helper?: string;
  error?: string;
  required?: boolean;
  id?: string;
}

function useFieldIds(id?: string) {
  const generated = useId();
  const base = id ?? `df-field-${generated}`;
  return { id: base, helperId: `${base}-helper`, errorId: `${base}-error` };
}

function describedBy(ids: { helperId: string; errorId: string }, helper?: string, error?: string) {
  if (error) return ids.errorId;
  if (helper) return ids.helperId;
  return undefined;
}

export type TextFieldProps = CommonFieldProps & InputHTMLAttributes<HTMLInputElement>;

export function TextField({ label, helper, error, required, id, className, ...rest }: TextFieldProps) {
  const ids = useFieldIds(id);
  return (
    <FieldFrame {...ids} label={label} helper={helper} error={error} required={required}>
      <input
        {...rest}
        id={ids.id}
        required={required}
        className={`df-input${className ? ` ${className}` : ""}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(ids, helper, error)}
      />
    </FieldFrame>
  );
}

export type TextareaFieldProps = CommonFieldProps & TextareaHTMLAttributes<HTMLTextAreaElement>;

export function TextareaField({ label, helper, error, required, id, className, ...rest }: TextareaFieldProps) {
  const ids = useFieldIds(id);
  return (
    <FieldFrame {...ids} label={label} helper={helper} error={error} required={required}>
      <textarea
        {...rest}
        id={ids.id}
        required={required}
        className={`df-input df-textarea${className ? ` ${className}` : ""}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(ids, helper, error)}
      />
    </FieldFrame>
  );
}

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export type SelectFieldProps = CommonFieldProps &
  Omit<SelectHTMLAttributes<HTMLSelectElement>, "children"> & { options: readonly SelectOption[] };

export function SelectField({ label, helper, error, required, id, options, className, ...rest }: SelectFieldProps) {
  const ids = useFieldIds(id);
  return (
    <FieldFrame {...ids} label={label} helper={helper} error={error} required={required}>
      <select
        {...rest}
        id={ids.id}
        required={required}
        className={`df-input df-select${className ? ` ${className}` : ""}`}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy(ids, helper, error)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value} disabled={option.disabled}>
            {option.label}
          </option>
        ))}
      </select>
    </FieldFrame>
  );
}
