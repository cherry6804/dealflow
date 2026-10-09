interface AppStatusScreenProps {
  title: string;
  message: string;
  actionLabel?: string;
  onAction?: () => void;
  loading?: boolean;
}

export default function AppStatusScreen({
  title,
  message,
  actionLabel,
  onAction,
  loading = false,
}: AppStatusScreenProps) {
  return (
    <main className="app-status-page">
      <section
        className="surface app-status-card"
        aria-labelledby="app-status-heading"
        aria-busy={loading}
      >
        {loading && (
          <span className="app-status-spinner" aria-hidden="true" />
        )}

        <h1 id="app-status-heading">{title}</h1>
        <p>{message}</p>

        {actionLabel && onAction && (
          <button
            className="button button-primary"
            type="button"
            onClick={onAction}
          >
            {actionLabel}
          </button>
        )}
      </section>
    </main>
  );
}