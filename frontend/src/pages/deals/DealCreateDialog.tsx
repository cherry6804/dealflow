import { useState, type FormEvent } from "react";

import { RecordDialog } from "../../components/record/RecordDialog";
import { Button, SelectField, TextField, TextareaField } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { dealsApi, type DealStage } from "../../services/dealApi";
import { DEAL_STAGES, dealFieldsError, dealStageLabel, expectedValueOrNull } from "./deal-workflow";
import { type DealLookups } from "./DealRecordDialog";
import { dealCustomerName, dealPropertyTitle, leadOptionLabel } from "./deal-workflow";

interface DealCreateDialogProps {
  lookups: DealLookups;
  onClose: () => void;
  onCreated: (message: string) => void;
}

/** Create a deal. Customer and an available property are required, as on the legacy Deals page. */
export default function DealCreateDialog({ lookups, onClose, onCreated }: DealCreateDialogProps) {
  const [customerId, setCustomerId] = useState("");
  const [propertyId, setPropertyId] = useState("");
  const [leadId, setLeadId] = useState("");
  const [stage, setStage] = useState<DealStage>("NEW");
  const [expectedValue, setExpectedValue] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [notes, setNotes] = useState("");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);

  const dirty = customerId !== "" || propertyId !== "" || leadId !== "" || expectedValue !== "" || notes !== "";
  const activeCustomers = lookups.customers.filter((customer) => customer.is_active);
  const availableProperties = lookups.properties.filter((property) => property.status === "AVAILABLE");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    if (!customerId) return setMessage("Select a customer.");
    if (!propertyId) return setMessage("Select an available property.");
    const rule = dealFieldsError(expectedValue, currency);
    if (rule) return setMessage(rule);
    setSaving(true);
    try {
      await dealsApi.create({
        customer_profile_id: customerId,
        property_id: propertyId,
        stage,
        expected_value: expectedValueOrNull(expectedValue),
        currency: currency.trim().toUpperCase(),
        notes: notes.trim() || null,
        lead_id: leadId || null,
      });
      onCreated("Deal created successfully.");
    } catch (error) {
      setMessage(error instanceof ApiError || error instanceof Error ? error.message : "The deal could not be created. Try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <RecordDialog
      open
      onClose={onClose}
      eyebrow="Deal"
      title="New deal"
      closeLabel="Close new deal"
      busy={saving}
      dirty={dirty}
      footer={(close) => (
        <>
          <Button variant="secondary" onClick={close} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="deal-create-form" variant="primary" loading={saving}>
            Create deal
          </Button>
        </>
      )}
      main={
        <form id="deal-create-form" className="df-sales-form" onSubmit={submit} noValidate>
          {message ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              {message}
            </p>
          ) : null}
          <div className="df-sales-form-grid">
            <SelectField
              label="Customer"
              required
              value={customerId}
              disabled={saving}
              options={[{ value: "", label: "Select a customer" }, ...activeCustomers.map((customer) => ({ value: customer.id, label: dealCustomerName(customer) }))]}
              onChange={(event) => setCustomerId(event.target.value)}
            />
            <SelectField
              label="Property"
              required
              value={propertyId}
              disabled={saving}
              helper={availableProperties.length === 0 ? "No available properties." : undefined}
              options={[{ value: "", label: "Select a property" }, ...availableProperties.map((property) => ({ value: property.id, label: dealPropertyTitle(property) }))]}
              onChange={(event) => setPropertyId(event.target.value)}
            />
            <SelectField
              label="Lead"
              value={leadId}
              disabled={saving}
              options={[{ value: "", label: "Not linked" }, ...lookups.leads.filter((lead) => lead.is_active).map((lead) => ({ value: lead.id, label: leadOptionLabel(lead, lookups.contacts) }))]}
              onChange={(event) => setLeadId(event.target.value)}
            />
            <SelectField label="Stage" value={stage} disabled={saving} options={DEAL_STAGES.map((value) => ({ value, label: dealStageLabel(value) }))} onChange={(event) => setStage(event.target.value as DealStage)} />
            <TextField label="Expected value" type="number" min="0" value={expectedValue} disabled={saving} onChange={(event) => setExpectedValue(event.target.value)} />
            <TextField label="Currency" value={currency} maxLength={3} disabled={saving} onChange={(event) => setCurrency(event.target.value)} />
          </div>
          <TextareaField label="Notes" rows={3} value={notes} disabled={saving} onChange={(event) => setNotes(event.target.value)} />
        </form>
      }
    />
  );
}
