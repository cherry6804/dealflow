# ADR-0013: Customer Requirement Budget Range

- **Status:** Accepted
- **Date:** 2026-10-04
- **Related Sprint:** DF-S05
- **Related Story:** DF-51
- **Related Epic:** DF-E05 — Customer Requirements
- **Depends On:** ADR-0012, Customer Requirement Domain Architecture

---

## 1. Context

DealFlow Customer Requirements represent the real-estate needs and preferences associated with an actively managed business opportunity.

DF-50 established the Customer Requirement as a tenant-scoped domain entity with a minimal foundation containing:

- identity
- organization ownership
- lifecycle status
- active state
- creation timestamp
- update timestamp

DF-51 extends that foundation by allowing a Customer Requirement to capture the customer's expected budget range.

Budget is an attribute of the customer's requirement. It is not an independent business entity in the current product scope.

The budget capability must therefore extend the existing Customer Requirement model without introducing unnecessary domain complexity.

The design must remain compatible with future requirement capabilities planned for:

- DF-52 — Capture location preferences
- DF-53 — Capture property type/BHK/preferences
- DF-54 — Capture possession/parking preferences
- DF-55 — Associate requirement with lead/customer
- DF-56 — Edit requirement while preserving history

---

## 2. Decision

DealFlow will represent the customer's budget as part of the Customer Requirement entity.

The budget representation will consist of:

- minimum budget
- maximum budget
- currency

The budget fields are optional.

A requirement may therefore exist without a captured budget.

Budget information must remain tenant-scoped through the owning Customer Requirement.

---

## 3. Domain Ownership

Budget belongs to the Customer Requirement domain.

The ownership relationship is:

Customer Requirement
→ Budget Range

The budget must not become a separate top-level tenant entity for DF-51.

This avoids unnecessary complexity while keeping the model extensible for future requirement capabilities.

---

## 4. Budget Minimum

The minimum budget represents the lowest expected value supplied for the customer's requirement.

The minimum budget:

- is optional
- must not be negative
- represents a monetary amount
- must use the requirement's specified currency
- may be provided without a maximum budget

If the customer does not provide a minimum budget, the value remains unset.

---

## 5. Budget Maximum

The maximum budget represents the highest expected value supplied for the customer's requirement.

The maximum budget:

- is optional
- must not be negative
- represents a monetary amount
- must use the requirement's specified currency
- may be provided without a minimum budget

If the customer does not provide a maximum budget, the value remains unset.

---

## 6. Budget Range Validation

When both minimum and maximum budget values are provided:

`budget_min <= budget_max`

must hold.

The following combinations are valid:

- minimum absent and maximum absent
- minimum present and maximum absent
- minimum absent and maximum present
- minimum present and maximum present where minimum <= maximum

The following combinations are invalid:

- minimum < 0
- maximum < 0
- minimum > maximum

Invalid budget ranges must be rejected at the application validation boundary.

The database must not be relied upon as the sole mechanism for communicating these business validation errors to API consumers.

---

## 7. Currency

Budget values require an explicit currency representation.

The currency will be stored as a three-character currency code.

The initial DealFlow market is India, so INR is the primary supported currency.

However, the domain must not structurally assume that all future customers use INR.

Currency is therefore stored with the requirement rather than being inferred permanently from application configuration.

DF-51 does not introduce a complete multi-currency or foreign-exchange subsystem.

---

## 8. Monetary Precision

Budget values represent monetary amounts and must use a fixed decimal representation rather than floating-point application values.

This prevents binary floating-point representation from introducing inappropriate monetary precision behavior.

The persistence representation must provide sufficient precision for normal real-estate transaction values while retaining exactly two fractional decimal places.

The application/API representation must preserve monetary accuracy when reading and writing budget values.

---

## 9. Optional Budget

Budget is not mandatory when creating a Customer Requirement.

A Customer Requirement may therefore be created with:

- no budget
- minimum budget only
- maximum budget only
- both minimum and maximum budget

This preserves the DF-50 behavior where the requirement can exist before complete qualification information has been captured.

The system must not fabricate or infer a budget when none was provided.

---

## 10. Budget Update

Budget information must be independently editable without requiring unrelated Customer Requirement fields to change.

Updating budget must not automatically modify:

- requirement lifecycle status
- `is_active`
- organization ownership
- requirement identity
- lead association
- customer association
- future location preferences
- future property preferences

Budget changes must not implicitly create or modify a Lead.

---

## 11. Clearing Budget Values

The API must support explicitly clearing previously captured budget values.

An explicit null value represents removal of the corresponding captured budget value.

The implementation must distinguish between:

- a field being omitted from an update request
- a field explicitly supplied as null
- a field supplied with a monetary value

An omitted field must remain unchanged.

An explicitly null field must be cleared.

This follows the update semantics established by the existing DealFlow domain APIs.

---

## 12. Currency and Budget Consistency

A requirement's budget values must use the same currency.

DF-51 does not support separate currencies for minimum and maximum values.

The system must not silently convert budget values between currencies.

No exchange-rate conversion is performed by DF-51.

---

## 13. Tenant Isolation

Customer Requirement budget data is tenant-owned.

All access must remain constrained by the authenticated tenant context.

A user must not be able to:

- create budget information for another organization
- read another organization's budget
- update another organization's budget
- clear another organization's budget

The organization identifier must be derived from the verified tenant context rather than trusted from the request body.

Cross-tenant access must continue to follow existing DealFlow tenant-security behavior.

---

## 14. Authorization

Budget operations use the existing Customer Requirement authorization boundary.

Reading budget requires the existing requirement read permission.

Changing budget requires the Customer Requirement update permission:

`requirements.update`

The implementation must not introduce a bypass around the existing authorization system.

Authorization remains separate from authentication.

---

## 15. API Boundary

The API representation of Customer Requirement will expose the budget information as part of the requirement representation.

The API must validate:

- monetary value format
- non-negative values
- minimum/maximum relationship
- currency format

Malformed request payloads remain API validation errors.

Business-invalid budget ranges must produce an appropriate client-visible validation response consistent with existing DealFlow API conventions.

---

## 16. Persistence

The Customer Requirement persistence model will be extended with budget fields.

The migration must be backward compatible with existing Customer Requirement records created under DF-50.

Existing requirements must remain valid after the migration.

Existing DF-50 records will have no captured budget unless budget data is subsequently supplied.

The migration must not:

- delete existing requirements
- change tenant ownership
- change requirement lifecycle state
- fabricate budget information

---

## 17. Backward Compatibility

DF-51 must preserve all DF-50 behavior.

Existing operations for Customer Requirements must continue to work.

In particular:

- creating a requirement without budget remains valid
- retrieving existing requirements remains valid
- tenant isolation remains unchanged
- existing authorization behavior remains unchanged
- existing requirement lifecycle behavior remains unchanged

The budget capability is additive.

---

## 18. Future Compatibility

DF-51 must not prevent future Customer Requirement capabilities.

The design must remain compatible with:

### DF-52
Location preferences.

### DF-53
Property type, BHK and other property preferences.

### DF-54
Possession and parking preferences.

### DF-55
Requirement association with Lead and/or Customer.

### DF-56
Requirement editing and history preservation.

Future capabilities must be able to coexist with the budget fields without requiring destructive restructuring of the Customer Requirement identity.

---

## 19. History

DF-51 does not introduce a complete requirement-history subsystem.

However, budget updates must be implemented in a way that does not prevent DF-56 from introducing historical tracking.

No existing budget value may be silently overwritten through an operation that is intended to preserve history once DF-56 establishes the formal history model.

DF-56 remains responsible for defining the authoritative historical record of requirement changes.

---

## 20. Non-Goals

DF-51 does not implement:

- property matching
- budget-based property ranking
- affordability calculations
- mortgage calculations
- loan eligibility
- EMI calculations
- currency conversion
- foreign-exchange rates
- financial advice
- property price estimation
- market valuation
- negotiation pricing
- deal pricing
- payment tracking
- commission calculations
- AI budget recommendations
- automatic budget inference
- automatic budget changes

These capabilities belong to future product areas.

---

## 21. Security Considerations

Budget information can represent commercially sensitive customer information.

The implementation must therefore:

- enforce tenant isolation
- enforce authorization
- avoid accepting client-controlled organization ownership
- avoid cross-tenant reads
- avoid cross-tenant updates
- avoid logging unnecessary sensitive budget data
- preserve existing authentication and session controls

The budget capability must use the same security foundation as the existing Customer Requirement domain.

---

## 22. Testing Requirements

DF-51 must include focused automated tests covering at minimum:

### Valid budget cases

- no budget
- minimum only
- maximum only
- minimum and maximum
- equal minimum and maximum
- valid decimal values

### Invalid budget cases

- negative minimum
- negative maximum
- minimum greater than maximum
- invalid currency format
- malformed monetary values

### Update semantics

- update minimum
- update maximum
- update both
- clear minimum
- clear maximum
- clear both
- omitted fields remain unchanged

### Security

- authenticated access
- missing authentication
- missing permission
- cross-tenant read
- cross-tenant update
- client-controlled organization rejection

### Regression

Existing DF-50 Customer Requirement tests must continue to pass.

The complete backend test suite must pass before the story is considered complete.

---

## 23. Implementation Order

DF-51 implementation should follow this order:

1. Add/confirm ADR-0013.
2. Extend Customer Requirement domain model.
3. Create Alembic migration.
4. Extend API schemas.
5. Extend service/business validation.
6. Implement authorized budget update behavior.
7. Update API response representation.
8. Add focused tests.
9. Run full backend regression.
10. Run `git diff --check`.
11. Review complete diff.
12. Commit the complete DF-51 implementation.
13. Push the feature branch.
14. Create one complete pull request.
15. Merge into `develop`.
16. Verify `develop`.
17. Delete the feature branch.
18. Mark DF-51 Done in Jira.

---

## 24. Consequences

### Positive

- Customer Requirements can capture a key qualification attribute.
- Budget remains part of the requirement rather than creating unnecessary domain complexity.
- Minimum and maximum values support realistic customer budget ranges.
- Optional values preserve the progressive-data-entry model established by DF-50.
- Explicit currency keeps the model future-compatible.
- Tenant and authorization boundaries remain consistent with the existing platform.
- The design supports future requirement capabilities.

### Trade-offs

- Monetary values require explicit precision handling.
- Currency must be stored and validated.
- Budget validation introduces additional API/domain rules.
- Historical budget tracking is deferred to DF-56.

These trade-offs are intentional to keep DF-51 focused while preserving future compatibility.

---

## 25. Final Decision

DealFlow will capture customer budget as an optional monetary range directly on the tenant-scoped Customer Requirement.

The range consists of:

- optional minimum budget
- optional maximum budget
- explicit three-character currency code

Budget values must be non-negative.

When both values exist:

`budget_min <= budget_max`

must hold.

Budget changes require Customer Requirement update authorization and remain subject to tenant isolation.

DF-51 extends the DF-50 foundation without changing the Customer Requirement identity, lifecycle, ownership, or existing security model.