import type { ReactNode } from "react";

import { Button } from "../ui";

/*
 * Shared state panels for routes and panels: loading, empty, error and permission-denied.
 * Every string is passed in already translated. Each panel names itself with a heading so screen-reader users
 * hear the state change.
 */

interface StateProps {
  title: string;
  message?: string;
  action?: ReactNode;
}

export function LoadingState({ title, message }: StateProps) {
  return (
    <section className="df-state df-state--loading" aria-busy="true" aria-live="polite">
      <span className="df-btn-spinner" aria-hidden="true" />
      <h2 className="df-state-title">{title}</h2>
      {message ? <p className="df-state-message">{message}</p> : null}
    </section>
  );
}

export function EmptyState({ title, message, action }: StateProps) {
  return (
    <section className="df-state">
      <h2 className="df-state-title">{title}</h2>
      {message ? <p className="df-state-message">{message}</p> : null}
      {action}
    </section>
  );
}

export interface ErrorStateProps extends StateProps {
  retryLabel: string;
  onRetry: () => void;
}

/** Error with a retry action. Uses role="alert" so the failure is announced once. */
export function ErrorState({ title, message, retryLabel, onRetry }: ErrorStateProps) {
  return (
    <section className="df-state df-state--error" role="alert">
      <h2 className="df-state-title">{title}</h2>
      {message ? <p className="df-state-message">{message}</p> : null}
      <Button variant="secondary" onClick={onRetry}>
        {retryLabel}
      </Button>
    </section>
  );
}

/** Shown when the user is signed in but lacks the permission for this surface. No data is loaded behind it. */
export function PermissionDeniedState({ title, message, action }: StateProps) {
  return (
    <section className="df-state df-state--permission">
      <h2 className="df-state-title">{title}</h2>
      {message ? <p className="df-state-message">{message}</p> : null}
      {action}
    </section>
  );
}
