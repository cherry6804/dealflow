# DealFlow Definition of Ready and Definition of Done

## 1. Purpose

This document defines the minimum quality gates that DealFlow work must satisfy before it can start and before it can be considered complete.

The purpose is to ensure that development remains:

- clear
- traceable
- secure
- testable
- maintainable
- observable
- backward-compatible
- releasable
- aligned with product requirements

This document applies to Jira stories, tasks, bugs, spikes, and other engineering work where applicable.

---

# 2. Definition of Ready

An issue is **Ready** when the team has enough information to begin implementation without avoidable ambiguity.

Ready does not mean the work is already implemented.

## 2.1 Jira Readiness

The Jira issue must have:

- clear issue title
- correct issue type
- appropriate priority
- appropriate epic
- sprint assignment when scheduled
- clear description
- acceptance criteria
- known dependencies identified
- relevant documentation references
- estimated story points when estimation applies

---

## 2.2 Product Readiness

The intended product behavior must be understood.

The issue should identify:

- user problem
- business purpose
- expected behavior
- relevant user journey
- affected product area
- important business rules
- expected success conditions

If the requested behavior is ambiguous, the issue is not Ready.

---

## 2.3 Technical Readiness

The engineering team must understand enough of the technical scope to begin safely.

Where applicable, identify:

- affected services or modules
- API impact
- database impact
- frontend impact
- background processing impact
- integration impact
- configuration impact
- infrastructure impact
- migration requirements
- observability requirements

A detailed implementation design is not always required before starting, but major unknowns must be resolved or explicitly tracked as a Spike.

---

## 2.4 Security Readiness

Potential security implications must be identified before implementation.

Consider:

- authentication
- authorization
- tenant isolation
- data access
- sensitive data
- input validation
- file handling
- secrets
- audit requirements
- abuse cases
- privilege boundaries

Security-critical ambiguity must be resolved before implementation.

---

## 2.5 Data Readiness

If the work affects data, identify:

- entities involved
- fields affected
- relationships affected
- validation rules
- migration requirements
- historical-data impact
- backward compatibility
- future compatibility
- retention requirements where applicable

Destructive or irreversible data changes require explicit review and migration planning.

---

## 2.6 Testing Readiness

The issue must identify how correctness will be verified.

Where applicable, identify:

- unit tests
- integration tests
- API tests
- frontend tests
- end-to-end tests
- security tests
- migration tests
- regression tests
- manual verification

Acceptance criteria must be testable.

---

## 2.7 Dependency Readiness

Known dependencies must be identified.

Examples:

- another Jira issue
- API contract
- database migration
- external integration
- infrastructure capability
- design decision
- security decision
- product decision

Blocked dependencies must not be hidden.

---

## 2.8 Documentation Readiness

If the change affects documented behavior, identify the documentation that must be updated.

Examples:

- API documentation
- architecture documentation
- ADR
- product documentation
- operational runbook
- security documentation
- customer documentation

---

# 3. Definition of Done

An issue is **Done** only when the agreed implementation is complete, verified, reviewed, and traceable.

"Code exists" is not sufficient for Done.

---

## 3.1 Product Completion

The implementation satisfies the approved acceptance criteria.

Verify:

- expected behavior works
- business rules are implemented
- relevant user flows work
- edge cases are handled
- failure behavior is defined
- no known acceptance-criteria gaps remain

---

## 3.2 Code Quality

Code must:

- follow repository conventions
- be understandable
- avoid unnecessary duplication
- use appropriate abstractions
- avoid dead code
- avoid debug code
- avoid temporary workarounds without tracking
- preserve maintainability

---

## 3.3 Testing

Appropriate automated tests must be added or updated.

Depending on scope, this may include:

- unit tests
- integration tests
- API tests
- frontend component tests
- end-to-end tests
- regression tests
- security tests
- migration tests

Tests must pass before the issue is marked Done.

A test that is intentionally omitted must have a documented reason.

---

## 3.4 Security

Security requirements must be satisfied.

Verify as applicable:

- authentication is enforced
- authorization is enforced
- tenant boundaries are enforced
- input validation exists
- unsafe input is handled
- secrets are not committed
- sensitive data is appropriately protected
- audit requirements are satisfied
- security-sensitive errors do not leak unnecessary information

Security findings that block release must be resolved or explicitly accepted through the appropriate governance process.

---

## 3.5 Data Integrity

For data-affecting work:

- validation is implemented
- database constraints are appropriate
- migrations are tested
- rollback strategy is understood where required
- existing data remains usable
- historical data is not silently destroyed
- backward compatibility is considered
- future compatibility is considered

No destructive migration should be considered Done without explicit approval and a safe migration strategy.

---

## 3.6 API Quality

For API changes:

- request validation exists
- response contracts are defined
- appropriate status codes are used
- authentication/authorization is enforced
- errors are handled consistently
- API documentation is updated where required
- backward compatibility is considered

Breaking API changes require explicit review.

---

## 3.7 Frontend Quality

For frontend changes:

- user flow works as intended
- loading states are handled
- empty states are handled
- error states are handled
- validation feedback is clear
- accessibility is considered
- responsive behavior is considered where applicable
- frontend tests are updated where appropriate

---

## 3.8 Observability

For operationally relevant changes, verify appropriate:

- structured logging
- metrics
- tracing
- audit events
- error reporting
- operational visibility

Sensitive information must not be unnecessarily written to logs.

---

## 3.9 Performance

Performance impact must be considered.

Where applicable:

- database queries are reviewed
- indexes are appropriate
- unnecessary network calls are avoided
- expensive operations are controlled
- pagination is used where appropriate
- background processing is used when justified
- resource usage is understood

Performance-sensitive work should have measurable verification where practical.

---

## 3.10 Documentation

Required documentation must be updated.

This may include:

- README
- API documentation
- architecture documentation
- ADR
- security documentation
- operational runbook
- product documentation
- deployment documentation

Documentation must describe actual behavior, not intended behavior that has not been implemented.

---

## 3.11 Git and Traceability

Before Done:

- branch follows the Git workflow
- commits are meaningful
- no secrets are committed
- unrelated changes are removed
- Jira issue is traceable to the branch/commit/PR
- code review is completed when applicable
- merge is performed through the approved workflow when applicable

---

## 3.12 CI/CD

Required automated checks must pass.

Depending on the repository state, this may include:

- formatting
- linting
- type checking
- unit tests
- integration tests
- security scanning
- build verification
- migration checks
- frontend checks
- end-to-end tests

A failed required check prevents Done unless the failure is explicitly understood and approved.

---

## 3.13 Operational Readiness

For changes that affect deployed systems:

- configuration is documented
- deployment impact is understood
- migration steps are known
- rollback/recovery approach is understood
- monitoring is sufficient
- alerts are updated where required
- operational documentation is updated where required

---

## 3.14 Acceptance Verification

The acceptance criteria must be verified.

The verification result should be recorded in Jira or the relevant pull request.

Examples:

```text
All acceptance criteria verified.
Backend tests: PASS
Frontend tests: PASS
Integration tests: PASS
Security checks: PASS
```

---

# 4. Done Exceptions

An issue should not normally be marked Done with known incomplete work.

If an exception is necessary:

1. The incomplete item must be documented.
2. The risk must be understood.
3. A follow-up Jira issue must be created when appropriate.
4. The exception must be explicitly reviewed.
5. The reason must be recorded in Jira.

Technical debt must never become invisible work.

---

# 5. Definition of Ready Checklist

Before moving an issue to **Ready**, verify:

- [ ] Jira issue is correctly classified
- [ ] Product problem is understood
- [ ] Expected behavior is clear
- [ ] Acceptance criteria are testable
- [ ] Dependencies are identified
- [ ] Technical scope is understood
- [ ] Security implications are considered
- [ ] Data impact is understood
- [ ] Testing approach is understood
- [ ] Documentation impact is identified
- [ ] Story points are assigned where applicable

---

# 6. Definition of Done Checklist

Before moving an issue to **Done**, verify:

- [ ] Acceptance criteria satisfied
- [ ] Product behavior verified
- [ ] Code quality requirements satisfied
- [ ] Automated tests added/updated
- [ ] Relevant tests pass
- [ ] Security requirements satisfied
- [ ] Data integrity verified
- [ ] API contracts verified where applicable
- [ ] Frontend behavior verified where applicable
- [ ] Observability requirements satisfied
- [ ] Performance impact considered
- [ ] Documentation updated
- [ ] Git traceability maintained
- [ ] Required CI checks pass
- [ ] Operational readiness verified where applicable
- [ ] Jira/PR verification recorded
- [ ] No known untracked blocking work remains

---

# 7. Release-Level Done

An individual Jira issue can be Done while the overall release is not yet ready.

A release requires an additional release gate covering:

- critical acceptance criteria
- regression testing
- security verification
- data migration readiness
- backup/recovery readiness
- observability
- deployment readiness
- rollback readiness
- documentation
- support readiness
- unresolved critical/high-severity defects

Release readiness is therefore evaluated separately from individual issue completion.

---

# 8. Guiding Principle

DealFlow follows this principle:

> Ready means we understand enough to start safely.

> Done means the agreed work is implemented, verified, secure, traceable, and ready for its intended next stage.

The purpose of these definitions is not bureaucracy.

The purpose is to prevent incomplete requirements, unsafe implementation, hidden technical debt, untested behavior, security gaps, and operational surprises from becoming normal parts of product development.
