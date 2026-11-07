import type { GridFilterField, GridFilterOption } from "../../../components/grid/gridFilters";
import type { Contact } from "../../../services/contactApi";
import type { Lead } from "../../../services/leadApi";
import { personName } from "../sales-shared";
import { LEAD_INTERESTS, LEAD_STATUSES, formatStageLabel } from "./lead-workflow";

/**
 * Filter fields for leads, limited to values the lead data really has. Owner is listed only when the team list can name at
 * least one owner, so the control never offers an empty choice list.
 */
export function buildLeadFilterFields(owners: readonly GridFilterOption[]): GridFilterField[] {
  const fields: GridFilterField[] = [
    { key: "lead", label: "Lead", type: "text" },
    { key: "email", label: "Email address", type: "text" },
    { key: "phone", label: "Phone", type: "text" },
    {
      key: "stage",
      label: "Stage",
      type: "select",
      options: LEAD_STATUSES.map((stage) => ({ value: stage, label: formatStageLabel(stage) })),
    },
    {
      key: "interest",
      label: "Interest",
      type: "select",
      options: LEAD_INTERESTS.map((level) => ({ value: level, label: formatStageLabel(level) })),
    },
  ];
  if (owners.length > 0) {
    fields.push({ key: "owner", label: "Owner", type: "select", options: owners });
  }
  fields.push({ key: "nextFollowUp", label: "Next follow-up", type: "date" }, { key: "created", label: "Created", type: "date" });
  return fields;
}

/** Raw filter value for a lead and field key. Matches the fields from buildLeadFilterFields. */
export function leadFilterValue(
  lead: Lead,
  key: string,
  contactOf: (contactId: string) => Contact | undefined,
): string | null {
  const contact = contactOf(lead.contact_id);
  switch (key) {
    case "lead":
      return contact ? personName(contact) || null : null;
    case "email":
      return contact?.email ?? null;
    case "phone":
      return contact?.phone ?? null;
    case "stage":
      return lead.status;
    case "interest":
      return lead.interest;
    case "owner":
      // Owner options use the user id as their value, so the raw value is the id.
      return lead.owner_user_id;
    case "nextFollowUp":
      return lead.next_action_at;
    case "created":
      return lead.created_at;
    default:
      return null;
  }
}
