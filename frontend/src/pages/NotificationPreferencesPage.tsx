import { useCallback, useEffect, useState } from "react";

import {
  notificationApi,
  type NotificationPreferences,
  type NotificationPreferenceKey,
} from "../services/notificationApi";

import "./NotificationPreferencesPage.css";

type PreferenceOption = {
  key: Exclude<NotificationPreferenceKey, "enabled">;
  title: string;
  description: string;
  icon: string;
};

const PREFERENCE_OPTIONS: PreferenceOption[] = [
  {
    key: "follow_ups_enabled",
    title: "Follow-ups",
    description:
      "Receive updates about follow-ups, reminders, and pending customer actions.",
    icon: "↗",
  },
  {
    key: "deals_enabled",
    title: "Deals",
    description:
      "Receive notifications about deal activity and changes in your pipeline.",
    icon: "◇",
  },
  {
    key: "site_visits_enabled",
    title: "Site visits",
    description:
      "Stay informed about property visits and related activity.",
    icon: "⌖",
  },
  {
    key: "leads_enabled",
    title: "Leads",
    description:
      "Receive updates about lead activity and changes that need your attention.",
    icon: "◎",
  },
  {
    key: "automation_enabled",
    title: "Automation",
    description:
      "Receive notifications about automated workflows and their activity.",
    icon: "✳",
  },
];

function getErrorMessage(cause: unknown): string {
  return cause instanceof Error
    ? cause.message
    : "Something went wrong. Please try again.";
}

export default function NotificationPreferencesPage() {
  const [preferences, setPreferences] =
    useState<NotificationPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingKey, setSavingKey] =
    useState<NotificationPreferenceKey | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadPreferences = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const result = await notificationApi.getPreferences();
      setPreferences(result);
    } catch (cause) {
      setError(getErrorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadPreferences();
  }, [loadPreferences]);

  const savePreference = async (
    key: NotificationPreferenceKey,
    value: boolean,
  ) => {
    if (!preferences || savingKey !== null) {
      return;
    }

    const previousPreferences = preferences;

    setSavingKey(key);
    setError(null);
    setNotice(null);

    setPreferences({
      ...previousPreferences,
      [key]: value,
    });

    try {
      const updated = await notificationApi.updatePreferences({
        [key]: value,
      });

      setPreferences(updated);
      setNotice("Your notification preferences have been saved.");
    } catch (cause) {
      setPreferences(previousPreferences);
      setError(getErrorMessage(cause));
    } finally {
      setSavingKey(null);
    }
  };

  const enabledCategoryCount = preferences
    ? PREFERENCE_OPTIONS.filter((option) => preferences[option.key]).length
    : 0;

  if (loading) {
    return (
      <section className="notification-preferences-page">
        <div
          className="notification-preferences-state"
          role="status"
          aria-live="polite"
        >
          <span
            className="notification-preferences-spinner"
            aria-hidden="true"
          />
          <h2>Loading notification preferences</h2>
          <p>Getting your saved notification settings.</p>
        </div>
      </section>
    );
  }

  if (!preferences) {
    return (
      <section className="notification-preferences-page">
        <header className="notification-preferences-header">
          <span className="notification-preferences-eyebrow">
            PERSONAL SETTINGS
          </span>
          <h1>Notification preferences</h1>
          <p className="notification-preferences-subtitle">
            Choose which updates you want to receive in DealFlow.
          </p>
        </header>

        <div
          className="notification-preferences-alert notification-preferences-alert-error"
          role="alert"
        >
          <span aria-hidden="true">!</span>
          <p>{error ?? "Unable to load your notification preferences."}</p>
          <button
            type="button"
            className="notification-preferences-button"
            onClick={() => void loadPreferences()}
          >
            Try again
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="notification-preferences-page">
      <header className="notification-preferences-header">
        <div>
          <span className="notification-preferences-eyebrow">
            PERSONAL SETTINGS
          </span>
          <h1>Notification preferences</h1>
          <p className="notification-preferences-subtitle">
            Make DealFlow work for you. Choose the updates that deserve your
            attention and keep the noise down.
          </p>
        </div>

        <div
          className={`notification-preferences-summary ${
            preferences.enabled ? "" : "is-paused"
          }`}
        >
          <span
            className="notification-preferences-summary-icon"
            aria-hidden="true"
          >
            {preferences.enabled ? "✓" : "Ⅱ"}
          </span>
          <div>
            <strong>
              {preferences.enabled ? "Notifications on" : "Notifications paused"}
            </strong>
            <span>
              {preferences.enabled
                ? `${enabledCategoryCount} of ${PREFERENCE_OPTIONS.length} categories enabled`
                : "All in-app notifications are paused"}
            </span>
          </div>
        </div>
      </header>

      {error && (
        <div
          className="notification-preferences-alert notification-preferences-alert-error"
          role="alert"
        >
          <span aria-hidden="true">!</span>
          <p>{error}</p>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setError(null)}
          >
            ×
          </button>
        </div>
      )}

      {notice && (
        <div
          className="notification-preferences-alert notification-preferences-alert-success"
          role="status"
          aria-live="polite"
        >
          <span aria-hidden="true">✓</span>
          <p>{notice}</p>
          <button
            type="button"
            aria-label="Dismiss confirmation"
            onClick={() => setNotice(null)}
          >
            ×
          </button>
        </div>
      )}

      <div className="notification-preferences-panel">
        <div className="notification-preferences-panel-heading">
          <div>
            <h2>General</h2>
            <p>Control in-app notifications across your workspace activity.</p>
          </div>
          <span className="notification-preferences-section-label">
            GLOBAL
          </span>
        </div>

        <div className="notification-preference-row notification-preference-global">
          <div className="notification-preference-icon global-icon" aria-hidden="true">
            ♧
          </div>
          <div className="notification-preference-copy">
            <strong>In-app notifications</strong>
            <p>
              Turn off all in-app notifications without changing your individual
              category settings.
            </p>
          </div>
          <label className="notification-preference-switch">
            <input
              type="checkbox"
              checked={preferences.enabled}
              disabled={savingKey !== null}
              onChange={(event) =>
                void savePreference("enabled", event.target.checked)
              }
              aria-label="Enable all in-app notifications"
            />
            <span className="notification-preference-switch-track" />
          </label>
        </div>
      </div>

      <div className="notification-preferences-panel">
        <div className="notification-preferences-panel-heading">
          <div>
            <h2>Activity notifications</h2>
            <p>
              Choose the types of activity for which you want in-app updates.
            </p>
          </div>
          <span className="notification-preferences-section-label">
            {enabledCategoryCount} / {PREFERENCE_OPTIONS.length} ON
          </span>
        </div>

        <div className="notification-preferences-list">
          {PREFERENCE_OPTIONS.map((option) => {
            const checked = preferences[option.key];

            return (
              <div className="notification-preference-row" key={option.key}>
                <div
                  className="notification-preference-icon"
                  aria-hidden="true"
                >
                  {option.icon}
                </div>
                <div className="notification-preference-copy">
                  <strong>{option.title}</strong>
                  <p>{option.description}</p>
                </div>
                <label className="notification-preference-switch">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={savingKey !== null}
                    onChange={(event) =>
                      void savePreference(option.key, event.target.checked)
                    }
                    aria-label={`Enable ${option.title.toLowerCase()} notifications`}
                  />
                  <span className="notification-preference-switch-track" />
                </label>
              </div>
            );
          })}
        </div>
      </div>

      <div className="notification-preferences-footnote">
        <span aria-hidden="true">ⓘ</span>
        <p>
          Your preferences are saved automatically. These settings control
          in-app notifications; they do not change your account access or
          notification permissions.
        </p>
      </div>

      {savingKey !== null && (
        <p
          className="notification-preferences-saving"
          role="status"
          aria-live="polite"
        >
          Saving your changes…
        </p>
      )}
    </section>
  );
}
