import { useEffect, useState, type FormEvent } from "react";

import { RecordDialog } from "../../components/record/RecordDialog";
import { Button, SelectField, TextField } from "../../components/ui";
import { ApiError } from "../../lib/api";
import { contactsApi, type Contact } from "../../services/contactApi";
import { propertiesApi, type PropertyStatus, type PropertyTransactionType, type PropertyType } from "../../services/propertyApi";
import { fetchAllPages, personName, SALES_PAGE_SIZE } from "../sales/sales-shared";
import {
  CURRENCIES,
  EMPTY_PROPERTY_FORM,
  PROPERTY_STATUSES,
  PROPERTY_TYPES,
  TRANSACTION_TYPES,
  enumLabel,
  numericOrNull,
  textOrNull,
  validatePropertyForm,
  type PropertyForm,
  type PropertyFormErrors,
} from "./property-workflow";

interface PropertyCreateDialogProps {
  onClose: () => void;
  /** Called after the property is saved, with a confirmation message. */
  onCreated: (message: string) => void;
}

function describeError(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

/**
 * Create a property. Saving runs the same sequence the legacy Properties page uses: create the record, then save its location,
 * commercial terms, availability and contact links. If a later step fails after the record exists, the dialog says so and
 * names the record, so the user can complete it rather than create a duplicate.
 */
export default function PropertyCreateDialog({ onClose, onCreated }: PropertyCreateDialogProps) {
  const [form, setForm] = useState<PropertyForm>(EMPTY_PROPERTY_FORM);
  const [sourceContactId, setSourceContactId] = useState("");
  const [ownerContactId, setOwnerContactId] = useState("");
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [errors, setErrors] = useState<PropertyFormErrors>({});
  const [message, setMessage] = useState("");
  const [partialId, setPartialId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchAllPages((page) => contactsApi.list({ page, page_size: SALES_PAGE_SIZE }))
      .then((items) => {
        if (!cancelled) setContacts(items);
      })
      .catch(() => {
        if (!cancelled) setContacts([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function update<K extends keyof PropertyForm>(key: K, value: PropertyForm[K]) {
    setForm((current) => ({ ...current, [key]: value }));
    setErrors((current) => ({ ...current, [key]: undefined }));
  }

  const dirty = JSON.stringify(form) !== JSON.stringify(EMPTY_PROPERTY_FORM) || sourceContactId !== "" || ownerContactId !== "";

  async function submit(event: FormEvent) {
    event.preventDefault();
    setMessage("");
    const found = validatePropertyForm(form);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setSaving(true);
    let propertyId: string | null = null;
    try {
      const created = await propertiesApi.create();
      propertyId = created.id;
      await propertiesApi.updateLocation(propertyId, {
        address_line_1: form.address_line_1.trim(),
        address_line_2: textOrNull(form.address_line_2),
        locality: form.locality.trim(),
        city: form.city.trim(),
        state: form.state.trim(),
        postal_code: textOrNull(form.postal_code),
        property_type: form.property_type,
        bhk: numericOrNull(form.bhk),
        built_up_area: numericOrNull(form.built_up_area),
        carpet_area: numericOrNull(form.carpet_area),
        floor_number: numericOrNull(form.floor_number),
        total_floors: numericOrNull(form.total_floors),
      });
      await propertiesApi.updateCommercial(propertyId, {
        transaction_type: form.transaction_type,
        price: numericOrNull(form.price),
        currency: form.currency.trim().toUpperCase(),
        rent: numericOrNull(form.rent),
        security_deposit: numericOrNull(form.security_deposit),
        maintenance_charge: numericOrNull(form.maintenance_charge),
      });
      await propertiesApi.updateStatus(propertyId, form.status);
      if (sourceContactId || ownerContactId) {
        await propertiesApi.updateAssociation(propertyId, {
          source_contact_id: sourceContactId || null,
          owner_contact_id: ownerContactId || null,
        });
      }
      onCreated("Property created successfully.");
    } catch (createError) {
      if (propertyId) {
        setPartialId(propertyId);
        setMessage(
          `Property ${propertyId} was created, but one of its detail updates failed. ${describeError(createError)} ` +
            "Refresh the listing and complete the missing details before relying on this record.",
        );
      } else {
        setMessage(describeError(createError));
      }
    } finally {
      setSaving(false);
    }
  }

  const isSale = form.transaction_type === "SALE";

  return (
    <RecordDialog
      open
      onClose={onClose}
      eyebrow="Property"
      title="Add a property"
      closeLabel="Close add property"
      busy={saving}
      dirty={dirty && partialId === null}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button type="submit" form="property-create-form" variant="primary" loading={saving} disabled={partialId !== null}>
            Create property
          </Button>
        </>
      }
      main={
        <form id="property-create-form" className="df-sales-form" onSubmit={submit} noValidate>
          {message ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              {message}
            </p>
          ) : null}

          <h3 className="df-sales-section-title">Listing</h3>
          <div className="df-sales-form-grid">
            <SelectField
              label="Transaction type"
              required
              value={form.transaction_type}
              disabled={saving}
              options={TRANSACTION_TYPES.map((value) => ({ value, label: enumLabel(value) }))}
              onChange={(event) => update("transaction_type", event.target.value as PropertyTransactionType)}
            />
            <SelectField
              label="Property type"
              required
              value={form.property_type}
              disabled={saving}
              options={PROPERTY_TYPES.map((value) => ({ value, label: enumLabel(value) }))}
              onChange={(event) => update("property_type", event.target.value as PropertyType)}
            />
            <TextField
              label={isSale ? "Sale price" : "Sale price (optional)"}
              type="number"
              min="0"
              step="0.01"
              required={isSale}
              value={form.price}
              disabled={saving}
              error={errors.price}
              onChange={(event) => update("price", event.target.value)}
            />
            <TextField
              label={isSale ? "Monthly rent (optional)" : "Monthly rent"}
              type="number"
              min="0"
              step="0.01"
              required={!isSale}
              value={form.rent}
              disabled={saving}
              error={errors.rent}
              onChange={(event) => update("rent", event.target.value)}
            />
            <TextField label="Security deposit" type="number" min="0" step="0.01" value={form.security_deposit} disabled={saving} onChange={(event) => update("security_deposit", event.target.value)} />
            <TextField label="Maintenance charge" type="number" min="0" step="0.01" value={form.maintenance_charge} disabled={saving} onChange={(event) => update("maintenance_charge", event.target.value)} />
            <SelectField
              label="Currency"
              required
              value={form.currency}
              disabled={saving}
              options={CURRENCIES.map((value) => ({ value, label: value }))}
              onChange={(event) => update("currency", event.target.value)}
            />
            <SelectField
              label="Availability"
              required
              value={form.status}
              disabled={saving}
              options={PROPERTY_STATUSES.map((value) => ({ value, label: enumLabel(value) }))}
              onChange={(event) => update("status", event.target.value as PropertyStatus)}
            />
          </div>

          <h3 className="df-sales-section-title">Location</h3>
          <div className="df-sales-form-grid">
            <TextField label="Address line 1" required maxLength={250} value={form.address_line_1} disabled={saving} error={errors.address_line_1} onChange={(event) => update("address_line_1", event.target.value)} />
            <TextField label="Address line 2" maxLength={250} value={form.address_line_2} disabled={saving} onChange={(event) => update("address_line_2", event.target.value)} />
            <TextField label="Locality" required value={form.locality} disabled={saving} error={errors.locality} onChange={(event) => update("locality", event.target.value)} />
            <TextField label="City" required value={form.city} disabled={saving} error={errors.city} onChange={(event) => update("city", event.target.value)} />
            <TextField label="State" required value={form.state} disabled={saving} error={errors.state} onChange={(event) => update("state", event.target.value)} />
            <TextField label="Postal code" value={form.postal_code} disabled={saving} onChange={(event) => update("postal_code", event.target.value)} />
          </div>

          <h3 className="df-sales-section-title">Details</h3>
          <div className="df-sales-form-grid">
            <TextField label="BHK" type="number" min="0" value={form.bhk} disabled={saving} onChange={(event) => update("bhk", event.target.value)} />
            <TextField label="Built-up area (sq. ft.)" type="number" min="0" value={form.built_up_area} disabled={saving} onChange={(event) => update("built_up_area", event.target.value)} />
            <TextField label="Carpet area (sq. ft.)" type="number" min="0" value={form.carpet_area} disabled={saving} onChange={(event) => update("carpet_area", event.target.value)} />
            <TextField label="Floor number" type="number" min="0" value={form.floor_number} disabled={saving} error={errors.floor_number} onChange={(event) => update("floor_number", event.target.value)} />
            <TextField label="Total floors" type="number" min="0" value={form.total_floors} disabled={saving} onChange={(event) => update("total_floors", event.target.value)} />
          </div>

          <h3 className="df-sales-section-title">Contacts</h3>
          <div className="df-sales-form-grid">
            <SelectField
              label="Source contact"
              value={sourceContactId}
              disabled={saving}
              options={[{ value: "", label: "Not assigned" }, ...contacts.map((contact) => ({ value: contact.id, label: personName(contact) || "Unnamed contact" }))]}
              onChange={(event) => setSourceContactId(event.target.value)}
            />
            <SelectField
              label="Owner contact"
              value={ownerContactId}
              disabled={saving}
              options={[{ value: "", label: "Not assigned" }, ...contacts.map((contact) => ({ value: contact.id, label: personName(contact) || "Unnamed contact" }))]}
              onChange={(event) => setOwnerContactId(event.target.value)}
            />
          </div>
        </form>
      }
    />
  );
}
