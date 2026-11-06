import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "tertiary" | "danger";
export type ButtonSize = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a progress indicator, keeps the label, and blocks further clicks. */
  loading?: boolean;
  /** Visually hides the label. Requires `aria-label`. */
  iconOnly?: boolean;
  icon?: ReactNode;
}

/**
 * Action button. One primary action per region; secondary is outlined; tertiary is text-only;
 * danger is reserved for destructive actions with an explicit verb in the label.
 */
export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  iconOnly = false,
  icon,
  disabled,
  className,
  children,
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = [
    "df-btn",
    `df-btn--${variant}`,
    `df-btn--${size}`,
    iconOnly ? "df-btn--icon-only" : "",
    loading ? "df-btn--loading" : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button
      {...rest}
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
    >
      {loading ? <span className="df-btn-spinner" aria-hidden="true" /> : icon}
      {iconOnly ? null : <span className="df-btn-label">{children}</span>}
    </button>
  );
}
