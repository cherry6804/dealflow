import { useState, type FormEvent } from "react";

import { RecordDialog, RecordProperty } from "../../components/record/RecordDialog";
import { Badge, Button, ConfirmationDialog, SelectField, TextField, TextareaField } from "../../components/ui";
import { ApiError } from "../../lib/api";
import type { Contact } from "../../services/contactApi";
import type { CustomerProfile } from "../../services/customerProfileApi";
import type { Deal } from "../../services/dealApi";
import { referralsApi, type Referral } from "../../services/referralApi";
import { formatShortDate } from "../sales/sales-shared";
import {
  EMPTY_REFERRAL_FORM,
  REFERRAL_STATUSES,
  referralStatusLabel,
  referralStatusTone,
  referralToForm,
  referralToPayload,
  contactLabel,
  customerLabel,
  validateReferralForm,
  type ReferralForm,
  type ReferralFormErrors,
} from "./referral-workflow";

export interface ReferralLookups {
  customers: readonly CustomerProfile[];
  contacts: readonly Contact[];
  deals: readonly Deal[];
}

interface ReferralRecordDialogProps {
  /** Existing referral to edit. Omit to create a new one. */
  referral?: Referral;
  lookups: ReferralLookups;
  onClose: () => void;
  /** Called after a successful save or deactivation, with a confirmation message. */
  onSaved: (message: string) => void;
}

function describe(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

/**
 * A referral record. With no referral it creates one; with a referral it shows and edits the same fields, with Save changes in the
 * footer. Deactivation stays in the record, as on the legacy page, behind a confirmation.
 */
export default function ReferralRecordDialog({ referral, lookups, onClose, onSaved }: ReferralRecordDialogProps) {
  const initial = referral ? referralToForm(referral) : EMPTY_REFERRAL_FORM;
  const [form, setForm] = useState<ReferralForm>(initial);
  const [errors, setErrors] = useState<ReferralFormErrors>({});
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmDeactivate, setConfirmDeactivate] = useState(false);
  const dirty = JSON.stringify(form) !== JSON.stringify(initial);

  const customerById = new Map(lookups.customers.map((customer) => [customer.id, customer]));
  const contactById = new Map(lookups.contacts.map((contact) => [contact.id, contact]));
  const dealById = new Map(lookups.deals.map((deal) => [deal.id, deal]));

  function update<K extends keyof ReferralForm>(key: K, value: ReferralForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    const found = validateReferralForm(form);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setSaving(true);
    try {
      if (referral) {
        await referralsApi.update(referral.id, referralToPayload(form));
        onSaved("Referral updated successfully.");
      } else {
        await referralsApi.create(referralToPayload(form));
        onSaved("Referral created successfully.");
      }
    } catch (error) {
      setMessage(describe(error));
    } finally {
      setSaving(false);
    }
  }

  async function deactivate() {
    if (!referral) return;
    setConfirmDeactivate(false);
    setSaving(true);
    setMessage("");
    try {
      await referralsApi.deactivate(referral.id);
      onSaved("Referral deactivated.");
    } catch (error) {
      setMessage(describe(error));
    } finally {
      setSaving(false);
    }
  }

  const customerOptions = lookups.customers.map((customer) => ({ value: customer.id, label: customerLabel(customer) }));
  const contactOptions = lookups.contacts.map((contact) => ({ value: contact.id, label: contactLabel(contact) }));
  const dealOptions = lookups.deals.map((deal) => ({ value: deal.id, label: `Deal ${deal.id.slice(0, 8)} · ${deal.stage.replace(/_/g, " ").toLowerCase()}` }));

  const linkedCustomer = referral?.customer_profile_id ? customerById.get(referral.customer_profile_id) : undefined;
  const linkedReferrer = referral?.referrer_contact_id ? contactById.get(referral.referrer_contact_id) : undefined;
  const linkedDeal = referral?.deal_id ? dealById.get(referral.deal_id) : undefined;

  return (
    <>
    <RecordDialog
      open
      onClose={onClose}
      eyebrow="Referral"
      title={referral ? referral.referral_name : "New referral"}
      closeLabel={referral ? "Close referral" : "Close new referral"}
      status={referral ? <Badge tone={referralStatusTone(referral.status)}>{referralStatusLabel(referral.status)}</Badge> : undefined}
      busy={saving}
      dirty={dirty}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            {referral ? "Close" : "Cancel"}
          </Button>
          <Button type="submit" form="referral-form" variant="primary" disabled={referral !== undefined && !dirty} loading={saving}>
            {referral ? "Save changes" : "Create referral"}
          </Button>
        </>
      }
      main={
        <form id="referral-form" className="df-sales-form" onSubmit={submit} noValidate>
          {message ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              {message}
            </p>
          ) : null}
          <div className="df-sales-form-grid">
            <TextField label="Referral name" required value={form.referral_name} disabled={saving} error={errors.referral_name} onChange={(event) => update("referral_name", event.target.value)} />
            <SelectField label="Status" value={form.status} disabled={saving} options={REFERRAL_STATUSES.map((item) => ({ value: item.value, label: item.label }))} onChange={(event) => update("status", event.target.value as ReferralForm["status"])} />
            <TextField label="Phone" type="tel" value={form.referral_phone} disabled={saving} onChange={(event) => update("referral_phone", event.target.value)} />
            <TextField label="Email address" type="email" value={form.referral_email} disabled={saving} error={errors.referral_email} onChange={(event) => update("referral_email", event.target.value)} />
            <SelectField
              label="Referring contact"
              value={form.referrer_contact_id}
              disabled={saving}
              options={[{ value: "", label: "Not set" }, ...contactOptions]}
              onChange={(event) => update("referrer_contact_id", event.target.value)}
            />
            <SelectField label="Customer" value={form.customer_profile_id} disabled={saving} options={[{ value: "", label: "Not set" }, ...customerOptions]} onChange={(event) => update("customer_profile_id", event.target.value)} />
            <SelectField label="Deal" value={form.deal_id} disabled={saving} options={[{ value: "", label: "Not set" }, ...dealOptions]} onChange={(event) => update("deal_id", event.target.value)} />
          </div>
          <TextareaField label="Additional context" rows={3} value={form.notes} disabled={saving} onChange={(event) => update("notes", event.target.value)} />
          <p className={errors.customer_profile_id ? "df-sales-form-message df-sales-form-message--error" : "df-sales-muted"} role={errors.customer_profile_id ? "alert" : undefined}>
            {errors.customer_profile_id ?? "A referral must link to a customer, a referring contact or a deal."}
          </p>
        </form>
      }
      aside={
        referral ? (
          <>
            <dl className="df-sales-properties">
              <RecordProperty label="Customer">{linkedCustomer ? customerLabel(linkedCustomer) : referral.customer_profile_id ? "Linked" : "—"}</RecordProperty>
              <RecordProperty label="Referrer">{linkedReferrer ? contactLabel(linkedReferrer) : referral.referrer_contact_id ? "Linked" : "—"}</RecordProperty>
              <RecordProperty label="Deal">{linkedDeal ? linkedDeal.stage.replace(/_/g, " ").toLowerCase() : referral.deal_id ? "Linked" : "—"}</RecordProperty>
              <RecordProperty label="Referred">{formatShortDate(referral.created_at)}</RecordProperty>
              <RecordProperty label="Last updated">{formatShortDate(referral.updated_at)}</RecordProperty>
            </dl>
            <div className="df-sales-aside-actions">
              <Button variant="secondary" size="sm" onClick={() => setConfirmDeactivate(true)} disabled={saving}>
                Deactivate referral
              </Button>
            </div>
          </>
        ) : null
      }
    />
      <ConfirmationDialog
        open={confirmDeactivate}
        title="Deactivate referral?"
        message={`"${referral?.referral_name ?? "This referral"}" will be removed from active workflows. Its history is kept.`}
        confirmLabel="Deactivate"
        tone="danger"
        busy={saving}
        onConfirm={() => void deactivate()}
        onCancel={() => setConfirmDeactivate(false)}
      />
    </>
  );
}
