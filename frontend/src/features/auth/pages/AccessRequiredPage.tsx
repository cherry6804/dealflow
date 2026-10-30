import { useSearchParams } from "react-router-dom";

type NextStep = "plans" | "sibvo";

interface AccessMessage {
  title: string;
  body: string;
  nextStep: NextStep;
  actionLabel: string;
}

/**
 * Denial reasons SIBVO can return on the SSO error redirect. The reason is
 * only ever used as a key here, so unknown values fall back to the default.
 */
const ACCESS_MESSAGES = new Map<string, AccessMessage>([
  [
    "subscription_required",
    {
      title: "Choose a Dealsflo plan",
      body: "This organisation does not have a Dealsflo subscription or trial yet.",
      nextStep: "plans",
      actionLabel: "View Dealsflo plans",
    },
  ],
  [
    "trial_expired",
    {
      title: "Your Dealsflo trial has ended",
      body: "Choose a plan in SIBVO to keep using Dealsflo.",
      nextStep: "plans",
      actionLabel: "View Dealsflo plans",
    },
  ],
  [
    "subscription_inactive",
    {
      title: "Your Dealsflo subscription is not active",
      body: "Renew or change your plan in SIBVO to restore access.",
      nextStep: "plans",
      actionLabel: "View Dealsflo plans",
    },
  ],
  [
    "product_membership_required",
    {
      title: "You do not have Dealsflo access",
      body: "Ask an organisation administrator to give you a Dealsflo seat.",
      nextStep: "sibvo",
      actionLabel: "Open SIBVO",
    },
  ],
  [
    "organization_membership_required",
    {
      title: "No access to this organisation",
      body: "You are not a member of this organisation. Ask an administrator to invite you.",
      nextStep: "sibvo",
      actionLabel: "Open SIBVO",
    },
  ],
  [
    "product_seat_limit_exceeded",
    {
      title: "All Dealsflo seats are in use",
      body: "Ask an administrator to free a seat or change the plan in SIBVO.",
      nextStep: "sibvo",
      actionLabel: "Open SIBVO",
    },
  ],
]);

const DEFAULT_MESSAGE: AccessMessage = {
  title: "Dealsflo is not available",
  body: "Dealsflo access for this organisation could not be confirmed. Try again later or ask your administrator.",
  nextStep: "sibvo",
  actionLabel: "Open SIBVO",
};

/** Build a SIBVO link from the configured origin. Returns null when misconfigured. */
function sibvoUrl(path: string): string | null {
  try {
    const base = new URL(
      (import.meta.env.VITE_SIBVO_AUTH_URL ?? "http://localhost:5173").trim(),
    );
    if (
      !["http:", "https:"].includes(base.protocol) ||
      base.username ||
      base.password ||
      (import.meta.env.PROD && base.protocol !== "https:")
    ) {
      return null;
    }
    return new URL(path, base.origin).toString();
  } catch {
    return null;
  }
}

export default function AccessRequiredPage() {
  const [searchParams] = useSearchParams();
  const reason = searchParams.get("reason") ?? "";
  const message = ACCESS_MESSAGES.get(reason) ?? DEFAULT_MESSAGE;
  const nextUrl = sibvoUrl(
    message.nextStep === "plans" ? "/products/dealsflo#dp-plans" : "/app",
  );

  return (
    <main className="public-auth-page">
      <section className="public-auth-card" aria-labelledby="access-required-title">
        <h1 id="access-required-title">{message.title}</h1>
        <p>{message.body}</p>
        {nextUrl ? (
          <a className="button button--primary" href={nextUrl}>
            {message.actionLabel}
          </a>
        ) : (
          <p role="alert">The SIBVO link is not configured. Contact your administrator.</p>
        )}
        <p>
          <a href="/login">Sign in with a different account</a>
        </p>
      </section>
    </main>
  );
}
