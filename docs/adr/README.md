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

New ADRs should be added to this index when created.
