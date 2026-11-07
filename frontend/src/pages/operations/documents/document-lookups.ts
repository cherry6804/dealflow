import { contactsApi, type Contact } from "../../../services/contactApi";
import { customerProfilesApi, type CustomerProfile } from "../../../services/customerProfileApi";
import { dealsApi, type Deal } from "../../../services/dealApi";
import { leadsApi, type Lead } from "../../../services/leadApi";
import { propertiesApi, type Property } from "../../../services/propertyApi";
import { teamApi } from "../../../services/teamApi";
import { dealCustomerName, dealPropertyTitle } from "../../deals/deal-workflow";
import { contactDisplayName, fetchAllPages, SALES_PAGE_SIZE } from "../../sales/sales-shared";
import type { DocumentRecordType } from "../../../services/documentApi";
import type { LinkLookup } from "./document-workflow";

export interface RecordOption {
  value: string;
  label: string;
}

export type RecordOptions = Readonly<Record<DocumentRecordType, readonly RecordOption[]>>;

export interface DocumentLookups {
  links: LinkLookup;
  options: RecordOptions;
  uploaders: ReadonlyMap<string, string>;
}

export const EMPTY_DOCUMENT_LOOKUPS: DocumentLookups = {
  links: { leads: new Map(), properties: new Map(), deals: new Map() },
  options: { lead: [], property: [], deal: [] },
  uploaders: new Map(),
};

/**
 * Business records a document can be linked to, and the names that show in the grid. Each list is read in full, so a long list is
 * never cut off. Team members are optional: when the directory is not readable the uploader shows as an unknown user.
 */
export async function loadDocumentLookups(): Promise<DocumentLookups> {
  const [leads, contacts, properties, customers, deals, members] = await Promise.all([
    fetchAllPages((page) => leadsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => contactsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => propertiesApi.search({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => customerProfilesApi.list({ page, page_size: SALES_PAGE_SIZE })),
    fetchAllPages((page) => dealsApi.list({ page, page_size: SALES_PAGE_SIZE })),
    teamApi.listMembers().catch(() => []),
  ]);

  const contactById = new Map<string, Contact>(contacts.map((contact) => [contact.id, contact]));
  const customerById = new Map<string, CustomerProfile>(customers.map((customer) => [customer.id, customer]));
  const propertyById = new Map<string, Property>(properties.map((property) => [property.id, property]));

  const leadLabels = new Map<string, string>(
    leads.map((lead: Lead) => [lead.id, contactDisplayName(contactById.get(lead.contact_id))]),
  );
  const propertyLabels = new Map<string, string>(properties.map((property) => [property.id, dealPropertyTitle(property)]));
  const dealLabels = new Map<string, string>(
    deals.map((deal: Deal) => [
      deal.id,
      `${dealCustomerName(customerById.get(deal.customer_profile_id))} · ${dealPropertyTitle(propertyById.get(deal.property_id))}`,
    ]),
  );

  return {
    links: { leads: leadLabels, properties: propertyLabels, deals: dealLabels },
    options: {
      lead: [...leadLabels].map(([value, label]) => ({ value, label })),
      property: [...propertyLabels].map(([value, label]) => ({ value, label })),
      deal: [...dealLabels].map(([value, label]) => ({ value, label })),
    },
    uploaders: new Map(members.map((member) => [member.user_id, member.display_name || member.email])),
  };
}
