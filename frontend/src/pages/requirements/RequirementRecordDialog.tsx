import { useEffect, useState, type FormEvent } from "react";

import RequirementMatchPanel from "../RequirementMatchPanel";
import { RecordDialog, RecordProperty } from "../../components/record/RecordDialog";
import { Badge, Button, SelectField, TextField } from "../../components/ui";
import { ApiError } from "../../lib/api";
import type { CustomerProfile } from "../../services/customerProfileApi";
import type { Lead } from "../../services/leadApi";
import { propertiesApi, type Property } from "../../services/propertyApi";
import {
  requirementsApi,
  type CustomerRequirement,
  type ParkingPreference,
  type PossessionPreference,
  type PropertyType,
  type RequirementAssociation,
  type RequirementLocation,
  type RequirementPossessionParkingPreference,
  type RequirementPropertyPreference,
  type RequirementShortlistItem,
} from "../../services/requirementApi";
import { formatShortDate } from "../sales/sales-shared";
import {
  PARKING_OPTIONS,
  POSSESSION_OPTIONS,
  REQUIREMENT_PROPERTY_TYPES,
  bhkError,
  budgetError,
  budgetRange,
  enumLabel,
  formatBudget,
  optionalNumber,
  parkingSpacesError,
  requirementCustomerName,
} from "./requirement-workflow";

export interface RequirementLeadOption {
  lead: Lead;
  label: string;
}

export interface RequirementCustomerOption {
  profile: CustomerProfile;
  label: string;
}

interface RequirementRecordDialogProps {
  requirement: CustomerRequirement;
  leads: readonly RequirementLeadOption[];
  customers: readonly RequirementCustomerOption[];
  onClose: () => void;
  /** Called after any change so the grid can refresh the requirement's summary. */
  onChanged: (message: string) => void;
}

function describe(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message;
  return "Something went wrong. Please try again.";
}

/**
 * A customer requirement. Each section saves on its own, as on the legacy page: budget, the linked lead or customer, preferred
 * locations, property preferences, possession and parking, the shortlist, and matching (the shared match panel).
 */
export default function RequirementRecordDialog({ requirement, leads, customers, onClose, onChanged }: RequirementRecordDialogProps) {
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [budgetMin, setBudgetMin] = useState(requirement.budget_min == null ? "" : String(requirement.budget_min));
  const [budgetMax, setBudgetMax] = useState(requirement.budget_max == null ? "" : String(requirement.budget_max));

  const [association, setAssociation] = useState<RequirementAssociation | null>(null);
  const [leadId, setLeadId] = useState("");
  const [customerId, setCustomerId] = useState("");

  const [locations, setLocations] = useState<RequirementLocation[]>([]);
  const [city, setCity] = useState("");
  const [locality, setLocality] = useState("");

  const [preferences, setPreferences] = useState<RequirementPropertyPreference[]>([]);
  const [propertyType, setPropertyType] = useState<PropertyType>("APARTMENT");
  const [bhkMin, setBhkMin] = useState("");
  const [bhkMax, setBhkMax] = useState("");

  const [possession, setPossession] = useState<RequirementPossessionParkingPreference | null>(null);
  const [possessionValue, setPossessionValue] = useState<PossessionPreference>("ANY");
  const [parkingValue, setParkingValue] = useState<ParkingPreference>("ANY");
  const [parkingSpaces, setParkingSpaces] = useState("");

  const [shortlist, setShortlist] = useState<RequirementShortlistItem[]>([]);
  const [propertyQuery, setPropertyQuery] = useState("");
  const [propertyResults, setPropertyResults] = useState<Property[]>([]);
  const [shortlistBusy, setShortlistBusy] = useState("");

  // Load every section once, as the legacy page does. A failed section shows empty rather than blocking the others.
  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      requirementsApi.listLocations(requirement.id),
      requirementsApi.listPropertyPreferences(requirement.id),
      requirementsApi.getPossessionParking(requirement.id),
      requirementsApi.getAssociation(requirement.id),
      requirementsApi.listShortlist(requirement.id),
    ]).then(([locationResult, preferenceResult, possessionResult, associationResult, shortlistResult]) => {
      if (cancelled) return;
      setLocations(locationResult.status === "fulfilled" ? locationResult.value : []);
      setPreferences(preferenceResult.status === "fulfilled" ? preferenceResult.value : []);
      const possessionRecord = possessionResult.status === "fulfilled" ? possessionResult.value : null;
      setPossession(possessionRecord);
      setPossessionValue(possessionRecord?.possession_preference ?? "ANY");
      setParkingValue(possessionRecord?.parking_preference ?? "ANY");
      setParkingSpaces(possessionRecord?.parking_spaces_min == null ? "" : String(possessionRecord.parking_spaces_min));
      const associationRecord = associationResult.status === "fulfilled" ? associationResult.value : null;
      setAssociation(associationRecord);
      setLeadId(associationRecord?.lead_id ?? "");
      setCustomerId(associationRecord?.customer_profile_id ?? "");
      setShortlist(shortlistResult.status === "fulfilled" ? shortlistResult.value.items : []);
    });
    return () => {
      cancelled = true;
    };
  }, [requirement.id]);

  async function run(action: () => Promise<void>, confirmation: string) {
    setSaving(true);
    setError("");
    try {
      await action();
      onChanged(confirmation);
    } catch (actionError) {
      setError(describe(actionError));
    } finally {
      setSaving(false);
    }
  }

  async function saveBudget(event: FormEvent) {
    event.preventDefault();
    const rule = budgetError(budgetMin, budgetMax);
    if (rule) return setError(rule);
    await run(async () => {
      await requirementsApi.update(requirement.id, {
        budget_min: optionalNumber(budgetMin),
        budget_max: optionalNumber(budgetMax),
        budget_currency: "INR",
      });
    }, "Budget saved.");
  }

  async function saveAssociation(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      const input = { lead_id: leadId || null, customer_profile_id: customerId || null };
      const saved = association ? await requirementsApi.updateAssociation(requirement.id, input) : await requirementsApi.createAssociation(requirement.id, input);
      setAssociation(saved);
    }, "Customer assignment saved.");
  }

  async function addLocation(event: FormEvent) {
    event.preventDefault();
    if (!city.trim() || !locality.trim()) return setError("Enter both city and locality.");
    await run(async () => {
      await requirementsApi.createLocation(requirement.id, { city: city.trim(), locality: locality.trim() });
      setCity("");
      setLocality("");
      setLocations(await requirementsApi.listLocations(requirement.id));
    }, "Preferred location added.");
  }

  async function toggleLocation(location: RequirementLocation) {
    await run(async () => {
      await requirementsApi.updateLocation(requirement.id, location.id, { is_active: !location.is_active });
      setLocations(await requirementsApi.listLocations(requirement.id));
    }, "Location updated.");
  }

  async function addPreference(event: FormEvent) {
    event.preventDefault();
    const rule = bhkError(bhkMin, bhkMax);
    if (rule) return setError(rule);
    await run(async () => {
      await requirementsApi.createPropertyPreference(requirement.id, {
        property_type: propertyType,
        bhk_min: optionalNumber(bhkMin),
        bhk_max: optionalNumber(bhkMax),
      });
      setBhkMin("");
      setBhkMax("");
      setPreferences(await requirementsApi.listPropertyPreferences(requirement.id));
    }, "Property preference added.");
  }

  async function togglePreference(preference: RequirementPropertyPreference) {
    await run(async () => {
      await requirementsApi.updatePropertyPreference(requirement.id, preference.id, { is_active: !preference.is_active });
      setPreferences(await requirementsApi.listPropertyPreferences(requirement.id));
    }, "Property preference updated.");
  }

  async function savePossession(event: FormEvent) {
    event.preventDefault();
    const rule = parkingSpacesError(parkingSpaces);
    if (rule) return setError(rule);
    await run(async () => {
      const input = {
        possession_preference: possessionValue,
        parking_preference: parkingValue,
        parking_spaces_min: optionalNumber(parkingSpaces),
      };
      const saved = possession
        ? await requirementsApi.updatePossessionParking(requirement.id, input)
        : await requirementsApi.createPossessionParking(requirement.id, input);
      setPossession(saved);
    }, "Possession and parking preferences saved.");
  }

  async function searchProperties(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const result = await propertiesApi.search({ q: propertyQuery.trim() || undefined, status: "AVAILABLE", page: 1, page_size: 10 });
      setPropertyResults(result.items);
    } catch (searchError) {
      setError(describe(searchError));
    }
  }

  async function addToShortlist(property: Property) {
    if (shortlist.some((item) => item.property.id === property.id)) {
      return setError("This property is already shortlisted.");
    }
    setShortlistBusy(property.id);
    setError("");
    try {
      await requirementsApi.addToShortlist(requirement.id, property.id);
      setShortlist((await requirementsApi.listShortlist(requirement.id)).items);
      onChanged("Property added to the shortlist.");
    } catch (actionError) {
      setError(describe(actionError));
    } finally {
      setShortlistBusy("");
    }
  }

  async function removeFromShortlist(propertyId: string) {
    setShortlistBusy(propertyId);
    setError("");
    try {
      await requirementsApi.removeFromShortlist(requirement.id, propertyId);
      setShortlist((current) => current.filter((item) => item.property.id !== propertyId));
      onChanged("Property removed from the shortlist.");
    } catch (actionError) {
      setError(describe(actionError));
    } finally {
      setShortlistBusy("");
    }
  }

  const leadOptions = [{ value: "", label: "Not assigned" }, ...leads.map((option) => ({ value: option.lead.id, label: option.label }))];
  const customerOptions = [{ value: "", label: "Not assigned" }, ...customers.map((option) => ({ value: option.profile.id, label: option.label }))];
  const customerName = requirementCustomerName(requirement);

  return (
    <RecordDialog
      open
      onClose={onClose}
      eyebrow="Requirement"
      title={customerName}
      closeLabel="Close requirement"
      status={<Badge tone={requirement.is_active ? "success" : "neutral"}>{requirement.is_active ? "Active" : "Inactive"}</Badge>}
      busy={saving}
      main={
        <div className="df-sales-form">
          {error ? (
            <p className="df-sales-form-message df-sales-form-message--error" role="alert">
              {error}
            </p>
          ) : null}

          <form className="df-sales-section" onSubmit={saveBudget} noValidate aria-label="Budget">
            <h3 className="df-sales-section-title">Budget</h3>
            <div className="df-sales-form-grid">
              <TextField label="Minimum budget (INR)" type="number" min="0" value={budgetMin} disabled={saving} onChange={(event) => setBudgetMin(event.target.value)} />
              <TextField label="Maximum budget (INR)" type="number" min="0" value={budgetMax} disabled={saving} onChange={(event) => setBudgetMax(event.target.value)} />
            </div>
            <div className="df-sales-form-actions">
              <Button type="submit" variant="primary" size="sm" loading={saving}>
                Save budget
              </Button>
            </div>
          </form>

          <form className="df-sales-section" onSubmit={saveAssociation} noValidate aria-label="Linked lead or customer">
            <h3 className="df-sales-section-title">Assigned to</h3>
            <div className="df-sales-form-grid">
              <SelectField label="Lead" value={leadId} disabled={saving} options={leadOptions} onChange={(event) => setLeadId(event.target.value)} />
              <SelectField label="Customer" value={customerId} disabled={saving} options={customerOptions} onChange={(event) => setCustomerId(event.target.value)} />
            </div>
            <div className="df-sales-form-actions">
              <Button type="submit" variant="primary" size="sm" loading={saving}>
                Save assignment
              </Button>
            </div>
          </form>

          <section className="df-sales-section" aria-label="Preferred locations">
            <h3 className="df-sales-section-title">Preferred locations</h3>
            {locations.length === 0 ? <p className="df-sales-muted">No preferred locations yet.</p> : null}
            <ul className="df-sales-followup-list">
              {locations.map((location) => (
                <li key={location.id} className="df-sales-followup">
                  <div className="df-sales-followup-main">
                    <div>
                      <strong>{location.locality}</strong>
                      <span className="df-sales-muted">{location.city}</span>
                    </div>
                    <Badge tone={location.is_active ? "success" : "neutral"}>{location.is_active ? "Active" : "Inactive"}</Badge>
                  </div>
                  <div className="df-sales-followup-actions">
                    <Button size="sm" variant="secondary" disabled={saving} onClick={() => void toggleLocation(location)}>
                      {location.is_active ? "Deactivate" : "Reactivate"}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
            <form className="df-sales-form-grid" onSubmit={addLocation} noValidate aria-label="Add a preferred location">
              <TextField label="City" value={city} disabled={saving} onChange={(event) => setCity(event.target.value)} />
              <TextField label="Locality" value={locality} disabled={saving} onChange={(event) => setLocality(event.target.value)} />
              <div className="df-sales-form-actions">
                <Button type="submit" variant="secondary" size="sm" loading={saving}>
                  Add location
                </Button>
              </div>
            </form>
          </section>

          <section className="df-sales-section" aria-label="Property preferences">
            <h3 className="df-sales-section-title">Property preferences</h3>
            {preferences.length === 0 ? <p className="df-sales-muted">No property preferences yet.</p> : null}
            <ul className="df-sales-followup-list">
              {preferences.map((preference) => (
                <li key={preference.id} className="df-sales-followup">
                  <div className="df-sales-followup-main">
                    <div>
                      <strong>{enumLabel(preference.property_type)}</strong>
                      <span className="df-sales-muted">
                        {preference.bhk_min || preference.bhk_max ? `${preference.bhk_min ?? "any"} to ${preference.bhk_max ?? "any"} BHK` : "Any BHK"}
                      </span>
                    </div>
                    <Badge tone={preference.is_active ? "success" : "neutral"}>{preference.is_active ? "Active" : "Inactive"}</Badge>
                  </div>
                  <div className="df-sales-followup-actions">
                    <Button size="sm" variant="secondary" disabled={saving} onClick={() => void togglePreference(preference)}>
                      {preference.is_active ? "Deactivate" : "Reactivate"}
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
            <form className="df-sales-form-grid" onSubmit={addPreference} noValidate aria-label="Add a property preference">
              <SelectField label="Property type" value={propertyType} disabled={saving} options={REQUIREMENT_PROPERTY_TYPES.map((value) => ({ value, label: enumLabel(value) }))} onChange={(event) => setPropertyType(event.target.value as PropertyType)} />
              <TextField label="Minimum BHK" type="number" min="1" value={bhkMin} disabled={saving} onChange={(event) => setBhkMin(event.target.value)} />
              <TextField label="Maximum BHK" type="number" min="1" value={bhkMax} disabled={saving} onChange={(event) => setBhkMax(event.target.value)} />
              <div className="df-sales-form-actions">
                <Button type="submit" variant="secondary" size="sm" loading={saving}>
                  Add preference
                </Button>
              </div>
            </form>
          </section>

          <form className="df-sales-section" onSubmit={savePossession} noValidate aria-label="Possession and parking">
            <h3 className="df-sales-section-title">Possession and parking</h3>
            <div className="df-sales-form-grid">
              <SelectField label="Possession timeline" value={possessionValue} disabled={saving} options={POSSESSION_OPTIONS.map((value) => ({ value, label: enumLabel(value) }))} onChange={(event) => setPossessionValue(event.target.value as PossessionPreference)} />
              <SelectField label="Parking" value={parkingValue} disabled={saving} options={PARKING_OPTIONS.map((value) => ({ value, label: enumLabel(value) }))} onChange={(event) => setParkingValue(event.target.value as ParkingPreference)} />
              <TextField label="Minimum parking spaces" type="number" min="1" value={parkingSpaces} disabled={saving} onChange={(event) => setParkingSpaces(event.target.value)} />
            </div>
            <div className="df-sales-form-actions">
              <Button type="submit" variant="primary" size="sm" loading={saving}>
                Save possession and parking
              </Button>
            </div>
          </form>

          <section className="df-sales-section" aria-label="Shortlist">
            <h3 className="df-sales-section-title">Shortlist</h3>
            {shortlist.length === 0 ? <p className="df-sales-muted">No properties shortlisted yet.</p> : null}
            <ul className="df-sales-followup-list">
              {shortlist.map((item) => (
                <li key={item.property.id} className="df-sales-followup">
                  <div className="df-sales-followup-main">
                    <div>
                      <strong>{item.property.locality || item.property.city || "Property"}</strong>
                      <span className="df-sales-muted">{formatBudget(item.property.price)}</span>
                    </div>
                  </div>
                  <div className="df-sales-followup-actions">
                    <Button size="sm" variant="secondary" disabled={shortlistBusy !== ""} onClick={() => void removeFromShortlist(item.property.id)}>
                      Remove from shortlist
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
            <form className="df-sales-form-grid" onSubmit={searchProperties} noValidate aria-label="Find properties to shortlist">
              <TextField label="Search available properties" value={propertyQuery} onChange={(event) => setPropertyQuery(event.target.value)} />
              <div className="df-sales-form-actions">
                <Button type="submit" variant="secondary" size="sm">
                  Search
                </Button>
              </div>
            </form>
            {propertyResults.length > 0 ? (
              <ul className="df-sales-followup-list">
                {propertyResults.map((property) => (
                  <li key={property.id} className="df-sales-followup">
                    <div className="df-sales-followup-main">
                      <div>
                        <strong>{property.locality || property.city || "Property"}</strong>
                        <span className="df-sales-muted">{formatBudget(property.price)}</span>
                      </div>
                    </div>
                    <div className="df-sales-followup-actions">
                      <Button size="sm" variant="primary" disabled={shortlistBusy !== ""} onClick={() => void addToShortlist(property)}>
                        Add to shortlist
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : null}
          </section>

          <section className="df-sales-section" aria-label="Matching properties">
            <h3 className="df-sales-section-title">Matching properties</h3>
            <RequirementMatchPanel requirementId={requirement.id} transactionType={requirement.transaction_type} />
          </section>
        </div>
      }
      aside={
        <>
          <dl className="df-sales-properties">
            <RecordProperty label="Budget">{budgetRange(requirement)}</RecordProperty>
            <RecordProperty label="Transaction">{requirement.transaction_type ? enumLabel(requirement.transaction_type) : "—"}</RecordProperty>
            <RecordProperty label="Customer">{customerName}</RecordProperty>
            <RecordProperty label="Created">{formatShortDate(requirement.created_at)}</RecordProperty>
            <RecordProperty label="Last updated">{formatShortDate(requirement.updated_at)}</RecordProperty>
          </dl>
          {association ? <p className="df-sales-muted">Linked: {association.lead_id ? "lead" : "no lead"}, {association.customer_profile_id ? "customer" : "no customer"}</p> : null}
        </>
      }
    />
  );
}
