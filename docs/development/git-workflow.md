# DealFlow Git Workflow

## 1. Purpose

This document defines the Git branching, commit, pull request, merge, and release practices for the DealFlow product.

The goal is to keep development:

- traceable
- reviewable
- secure
- reproducible
- releasable
- easy to maintain
- aligned with Jira

Every meaningful engineering change must be traceable from:

Jira Issue → Git Branch → Commit(s) → Pull Request → Review → Merge → Release

---

## 2. Repository Branches

DealFlow uses the following primary branches:

### main

`main` represents production-ready code.

Rules:

- Never develop directly on `main`.
- Direct pushes are prohibited.
- Changes enter `main` through an approved pull request.
- `main` must remain releasable.
- Production releases are created from `main`.

### develop

`develop` represents the current integrated development baseline.

Rules:

- Feature branches are created from `develop`.
- Completed feature work is merged into `develop`.
- `develop` should remain buildable and testable.
- Incomplete work must not be merged merely to meet a deadline.

---

## 3. Feature Branches

Feature branches are created from `develop`.

Naming convention:

```text
feature/DF-<issue-key>-<short-name>

Examples:

feature/DF-1-repository-foundation
feature/DF-9-fastapi-backend
feature/DF-10-react-frontend

A feature branch should normally represent one Jira story or one tightly related engineering change.

4. Bug-Fix Branches

Bug fixes use:

fix/DF-<issue-key>-<short-name>

Example:

fix/DF-142-lead-status-validation
5. Security Branches

Security-sensitive changes use:

security/DF-<issue-key>-<short-name>

Example:

security/DF-201-tenant-access-control

Security fixes must receive appropriate security review before release.

6. Documentation Branches

Documentation-only changes use:

docs/DF-<issue-key>-<short-name>

Example:

docs/DF-35-api-guidelines
7. Refactoring Branches

Refactoring that does not intentionally change product behavior uses:

refactor/DF-<issue-key>-<short-name>

Example:

refactor/DF-88-domain-service-cleanup
8. Spike Branches

Technical investigation work uses:

spike/DF-<issue-key>-<short-name>

Example:

spike/DF-76-postgresql-index-strategy

A spike should produce a documented conclusion or decision.

9. Branch Lifecycle

Standard feature lifecycle:

develop
   |
   +--> feature/DF-<id>-<name>
             |
             +--> implementation
             |
             +--> tests
             |
             +--> review
             |
             +--> merge
                    |
                    v
                 develop
                    |
                    v
                   main

Branches should be short-lived whenever practical.

Avoid keeping completed work isolated for long periods because long-lived branches increase merge conflicts and integration risk.

10. Commit Convention

DealFlow uses Conventional Commit-style messages.

Format:

type(scope): description

Common types:

feat
fix
docs
refactor
test
chore
build
ci
perf
security

Examples:

feat(leads): add lead creation endpoint
fix(auth): reject expired access tokens
docs(api): document lead endpoints
test(leads): add lead validation tests
refactor(domain): separate lead services
chore(repo): update development tooling
ci(test): add backend test workflow
perf(search): add lead search index
security(auth): enforce tenant authorization
11. Commit Rules

Commits should:

represent one logical change
be understandable without opening every file
reference the relevant Jira issue where practical
avoid unrelated modifications
avoid generated files unless intentionally required
avoid secrets
avoid credentials
avoid local environment files

Good:

feat(leads): add lead creation endpoint

Poor:

update stuff

Poor:

changes

Poor:

final final
12. Commit Size

Prefer small, logically complete commits.

A commit should normally answer one question:

What single engineering change does this commit represent?

Large changes should be divided when doing so improves reviewability and traceability.

13. Jira Traceability

Every development branch must correspond to a Jira issue.

Example:

Jira:
DF-9 Bootstrap FastAPI backend

Branch:
feature/DF-9-fastapi-backend

Commit:
feat(api): bootstrap FastAPI backend

The Jira issue should contain enough information to identify the associated branch, commits, and pull request.

14. Pull Requests

Changes should be merged through pull requests once the repository is connected to the remote Git platform.

A pull request should contain:

Jira issue reference
summary of the change
implementation details where useful
test results
security considerations where applicable
migration information where applicable
deployment considerations where applicable
15. Pull Request Quality Gate

Before merge, verify:

code builds successfully
automated tests pass
relevant manual testing is complete
security checks pass
linting/formatting checks pass
database migrations are reviewed
API changes are reviewed
backward compatibility is considered
observability impact is considered
documentation is updated when necessary
16. Merge Rules

Feature branches merge into:

develop

Release-ready changes merge from the appropriate release process into:

main

Do not merge unfinished work into main.

17. Force Push Policy

Avoid force pushing shared branches.

Force pushing is prohibited on:

main
develop

If history rewriting is required on a private feature branch, it must be done carefully and must not destroy work belonging to another developer.

18. Secrets and Sensitive Data

Never commit:

passwords
API keys
access tokens
private keys
production credentials
database credentials
customer secrets
personal authentication data

Use environment variables and approved secret-management mechanisms.

Local environment files such as:

.env
.env.local
.env.production

must not be committed unless a file is explicitly designed to contain non-secret example configuration.

19. Protected Branches

When repository hosting is configured, the following protections should be enabled.

main
Pull request required
Required checks
No direct push
No force push
Review required as team size permits
develop
Pull request preferred/required
Required CI checks
No force push

Branch protection must evolve as the engineering team grows.

20. Local Development Flow

Typical workflow:

git switch develop
git pull --rebase origin develop

git switch -c feature/DF-<id>-<short-name>

# implement change

git status
git diff

# run tests

git add <files>
git commit -m "type(scope): description"

git push -u origin feature/DF-<id>-<short-name>

Then create the pull request.

21. Before Starting Work

Before starting a new issue:

Confirm the Jira issue is ready.
Confirm acceptance criteria are understood.
Update local develop.
Create a correctly named branch.
Confirm the branch contains the expected baseline.
22. Before Commit

Before committing:

Review changed files.
Review the diff.
Run relevant tests.
Confirm no secrets are present.
Confirm no unrelated files are included.
Confirm the commit message follows the convention.
23. Before Merge

Before merge:

CI passes.
Tests pass.
Review is complete.
Security implications are considered.
Database/API compatibility is considered.
Documentation is updated where required.
Jira acceptance criteria are satisfied.
24. Emergency Changes

Emergency production fixes may use:

hotfix/DF-<issue-key>-<short-name>

Example:

hotfix/DF-500-production-auth-failure

Emergency changes must still be:

tracked in Jira
reviewed as soon as practical
tested
merged back into the appropriate development branch
documented
25. General Principle

Git is part of the DealFlow engineering control system.

The repository must preserve:

traceability
accountability
reproducibility
security
reviewability
rollback capability
release confidence

The objective is not merely to store code.

The objective is to maintain a controlled and auditable path from engineering decision to production software.