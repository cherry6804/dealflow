# Architecture Decision Records

## Purpose

Architecture Decision Records (ADRs) document significant technical and architectural decisions made during the development of DealFlow.

An ADR records:

- the problem or context
- the decision
- the alternatives considered
- the consequences
- important constraints
- the status of the decision

ADRs preserve architectural reasoning so future developers can understand not only **what** DealFlow does, but **why** it was designed that way.

---

## When to Create an ADR

An ADR should be created when a decision has meaningful long-term impact on:

- system architecture
- domain boundaries
- data models
- security
- tenancy
- authentication or authorization
- API contracts
- infrastructure
- persistence
- integrations
- deployment
- observability
- reliability
- scalability
- performance
- AI capabilities
- privacy
- compliance
- backward compatibility
- technology selection

Not every implementation detail requires an ADR.

---

## ADR Naming

ADRs use sequential numeric identifiers.

Format:

```text
NNNN-short-decision-name.md
```

Examples:

```text
0001-adr-template.md
0002-modular-monolith.md
0003-postgresql.md
0004-tenant-isolation.md
```

The number must be unique and must not be reused.

---

## ADR Status

Allowed statuses:

- Proposed
- Accepted
- Rejected
- Superseded
- Deprecated

### Proposed

The decision is under discussion and has not been formally accepted.

### Accepted

The decision is approved and represents the current architectural direction.

### Rejected

The proposed decision was considered but not adopted.

### Superseded

A newer ADR replaces this decision.

The newer ADR must reference the superseded ADR.

### Deprecated

The decision is no longer relevant, but the historical record is retained.

---

## ADR Principles

### 1. Record significant decisions

ADRs should focus on decisions that matter to the long-term system.

### 2. Record reasoning

The reasoning behind a decision is often more valuable than the decision itself.

### 3. Record alternatives

Reasonable alternatives should be documented when they were seriously considered.

### 4. Record consequences

Both positive and negative consequences should be documented.

### 5. Preserve history

Existing ADRs should not be rewritten merely because the system evolved.

If a decision changes, create a new ADR and mark the previous ADR as superseded.

### 6. Link related decisions

Related ADRs should reference one another where useful.

---

## ADR Lifecycle

```text
Proposed
   |
   v
Review
   |
   +----> Rejected
   |
   v
Accepted
   |
   +----> Superseded
   |
   +----> Deprecated
```

---

## ADR Review

Architecture decisions should be reviewed before implementation when practical.

Review should consider:

- product requirements
- security
- privacy
- data integrity
- operational impact
- scalability
- performance
- maintainability
- testing
- backward compatibility
- future compatibility
- cost
- developer experience

---

## Relationship to Jira

Architecture decisions should be traceable to the relevant Jira issue when applicable.

Example:

```text
Jira:
DF-123

ADR:
0007-tenant-isolation.md
```

The Jira issue may reference the ADR, and the ADR may reference the Jira issue.

---

## Relationship to Code

When an ADR results in an implementation change, the related code changes should reference the ADR where useful.

Example commit:

```text
feat(auth): enforce tenant authorization

ADR: 0007
```

---

## Superseding an ADR

When a decision changes:

1. Create a new ADR.
2. Reference the previous ADR.
3. Explain why the decision changed.
4. Mark the previous ADR as `Superseded`.
5. Link the new ADR from the previous ADR where practical.

Never silently rewrite architectural history.

---

## Current ADR Index

| ADR | Title | Status |
|---|---|---|
| 0001 | ADR Template | Accepted |
| 0002 | Identity and Tenant Architecture | Accepted |
| 0003 | Authentication Security Architecture | Accepted |
| 0004 | Tenant Context Architecture | Accepted |
| 0005 | Authorization Model Architecture | Accepted |
| 0006 | Authorization Audit Events Architecture | Accepted |
| 0007 | Contact and Customer Domain Architecture | Accepted |
| 0008 | Lead Domain Architecture and Lifecycle | Accepted |
| 0009 | Lead Update and Lifecycle Management | Accepted |
| 0010 | Lead Assignment and Ownership | Accepted |
| 0011 | Lead Next Action and Outcome Management | Accepted |
| 0012 | Customer Requirement Domain Architecture | Accepted |
| 0013 | Customer Requirement Budget Range | Accepted |
| 0014 | Customer Requirement Location Preferences | Accepted |
| 0015 | Customer Requirement Property Type, BHK & Property Preferences | Accepted |
| 0016 | Customer Requirement Possession & Parking Preferences | Accepted |
| 0017 | Customer Requirement Lead and Customer Profile Association | Accepted |
| 0018 | Customer Requirement Edit History & Versioning | Proposed |
| 0019 | Property Domain Foundation | Accepted |
| 0020 | Property Commercial Fields | Accepted |
| 0021 | Property Location and Attributes | Accepted |
| 0022 | Property Availability and Status | Accepted |
| 0023 | Property Search and Filtering | Accepted |
| 0024 | Property Source and Owner Association | Proposed |
| 0025 | Modular Monolith Boundaries and Module Ownership | Proposed |
| 0026 | Transactional Outbox and Background Execution | Proposed |
| 0027 | SIBVO Authority and Entitlement Snapshot | Proposed |
| 0028 | Communication Channel Gateway Architecture | Proposed |
| 0029 | AI Execution and Disabled-by-Default Enablement Policy | Accepted |
| 0030 | Environment and Configuration Standards | Proposed |

New ADRs should be added to this index when created.
