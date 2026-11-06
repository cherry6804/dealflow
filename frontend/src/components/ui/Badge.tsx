import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "success" | "active" | "pending" | "danger" | "automated";

export interface BadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
}

/** Status badge. The label carries the meaning; the colour only reinforces it. */
export function Badge({ tone = "neutral", children }: BadgeProps) {
  return <span className={`df-badge df-badge--${tone}`}>{children}</span>;
}
