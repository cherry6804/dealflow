import type { Contact } from "../../services/contactApi";
import type { CustomerProfile } from "../../services/customerProfileApi";
import { personName } from "../sales/sales-shared";
import type { Referral, ReferralCreateInput, ReferralStatus } from "../../services/referralApi";

export const REFERRAL_STATUSES: readonly { value: ReferralStatus; label: string }[] = [
  { value: "NEW", label: "New" },
  { value: "CONTACTED", label: "Contacted" },
  { value: "CONVERTED", label: "Converted" },
  { value: "NOT_CONVERTED", label: "Not converted" },
];

export function referralStatusLabel(status: ReferralStatus): string {
  return REFERRAL_STATUSES.find((item) => item.value === status)?.label ?? status.replaceAll("_", " ");
}

export type ReferralStatusTone = "neutral" | "active" | "success" | "danger";

export function referralStatusTone(status: ReferralStatus): ReferralStatusTone {
  switch (status) {
    case "CONVERTED":
      return "success";
    case "CONTACTED":
      return "active";
    case "NOT_CONVERTED":
      return "danger";
    default:
      return "neutral";
  }
}

export interface ReferralForm {
  referral_name: string;
  referral_phone: string;
  referral_email: string;
  customer_profile_id: string;
  referrer_contact_id: string;
  deal_id: string;
  status: ReferralStatus;
  notes: string;
}

export const EMPTY_REFERRAL_FORM: ReferralForm = {
  referral_name: "",
  referral_phone: "",
  referral_email: "",
  customer_profile_id: "",
  referrer_contact_id: "",
  deal_id: "",
  status: "NEW",
  notes: "",
};

export function referralToForm(referral: Referral): ReferralForm {
  return {
    referral_name: referral.referral_name ?? "",
    referral_phone: referral.referral_phone ?? "",
    referral_email: referral.referral_email ?? "",
    customer_profile_id: referral.customer_profile_id ?? "",
    referrer_contact_id: referral.referrer_contact_id ?? "",
    deal_id: referral.deal_id ?? "",
    status: referral.status,
    notes: referral.notes ?? "",
  };
}

export type ReferralFormErrors = Partial<Record<keyof ReferralForm, string>>;

/** Same rules as the legacy Referrals page: a name, a link to a customer, referring contact or deal, and a valid email if given. */
export function validateReferralForm(form: ReferralForm): ReferralFormErrors {
  const errors: ReferralFormErrors = {};
  if (!form.referral_name.trim()) errors.referral_name = "Enter the referral name.";
  if (!form.customer_profile_id && !form.referrer_contact_id && !form.deal_id) {
    errors.customer_profile_id = "Link the referral to a customer, referring contact, or deal.";
  }
  if (form.referral_email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.referral_email.trim())) {
    errors.referral_email = "Enter a valid email address.";
  }
  return errors;
}

export function referralToPayload(form: ReferralForm): ReferralCreateInput {
  return {
    referral_name: form.referral_name.trim(),
    referral_phone: form.referral_phone.trim() || null,
    referral_email: form.referral_email.trim() || null,
    customer_profile_id: form.customer_profile_id || null,
    referrer_contact_id: form.referrer_contact_id || null,
    deal_id: form.deal_id || null,
    status: form.status,
    notes: form.notes.trim() || null,
  };
}

export function customerLabel(customer: CustomerProfile): string {
  return personName(customer.contact) || customer.contact.email || "Unnamed customer";
}

export function contactLabel(contact: Contact | undefined): string {
  return contact ? personName(contact) || "Unnamed contact" : "Contact unavailable";
}
