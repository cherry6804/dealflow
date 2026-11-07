const RESOURCE_ROUTES: Record<string, string> = {
  contact: "/contacts",
  contacts: "/contacts",
  customer: "/customers",
  customers: "/customers",
  lead: "/leads",
  leads: "/leads",
  deal: "/deals",
  deals: "/deals",
  referral: "/referrals",
  referrals: "/referrals",
  property: "/properties",
  properties: "/properties",
  site_visit: "/site-visits",
  site_visits: "/site-visits",
  requirement: "/requirements",
  requirements: "/requirements",
  import: "/imports",
  imports: "/imports",
  document: "/documents",
  documents: "/documents",
  follow_up: "/",
  followup: "/",
  automation_rule: "/automation-rules",
};

export function getNotificationResourceRoute(
  resourceType: string | null,
): string | null {
  if (!resourceType) {
    return null;
  }

  return RESOURCE_ROUTES[resourceType.toLowerCase()] ?? null;
}
