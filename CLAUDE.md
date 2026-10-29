# CLAUDE.md — Dealsflo Engineering Rules

Dealsflo is an enterprise SaaS product under SIBVO. These rules apply to every task.
For Git branch, commit and pull request conventions, see
[docs/development/git-workflow.md](docs/development/git-workflow.md).

## 1. Understand before changing

- Read repository instructions and follow the existing architecture, coding conventions, and testing practices.
- Inspect existing implementations before deciding what to build.
- Reuse working code and established abstractions.
- Never assume a feature is missing without verifying it.
- Make the smallest complete change that satisfies the assigned story.
- Do not implement unrelated features, broad refactors, or speculative abstractions.
- If requirements conflict with existing architecture, explain the conflict before making a risky change.

## 2. Git and branch safety

- Never work directly on `develop`.
- Use one feature branch per story, created from the latest `origin/develop`.
- Branch naming follows [docs/development/git-workflow.md](docs/development/git-workflow.md): `feature/DF-<issue-key>-<short-description>` for Jira-linked stories, and `feature/MVP-<story-id>-<short-description>` for workbook-only stories without a Jira key (for example `feature/MVP-00-repo-baseline-audit`).
- Before switching branches or creating a branch, inspect the repository, current branch, working tree, staged/unstaged/untracked changes, remotes, and recent commits.
- Never overwrite, discard, reset, clean, or silently move existing work.
- If the working tree is dirty or unrelated work exists, stop and report the situation before proceeding.
- Never use destructive Git commands, force-push, or push directly to `develop`.
- Keep each story's changes isolated and reviewable.

## 3. One story at a time

- Implement only the story explicitly assigned by the user.
- Understand its acceptance criteria, dependencies, scope, and definition of done before editing.
- Complete its backend, frontend, validation, tests, and documentation requirements where applicable.
- Do not begin the next story until the current story is tested, reviewed, and its release outcome is known.
- Do not silently expand scope to meet a deadline.

## 4. Enterprise architecture boundaries

SIBVO is the authority for:

- Identity and SSO.
- Canonical organizations and tenants.
- Organization memberships.
- Product access and entitlements.
- Plans, subscriptions, seat ownership, and billing.

Dealsflo owns its real-estate domain data, business rules, and workflows.

- Do not duplicate SIBVO's identity, tenant, subscription, entitlement, or billing authority.
- Follow the existing approved cross-repository contracts. The SSO contract is in [docs/architecture/sibvo-dealsflo-sso-contract.md](docs/architecture/sibvo-dealsflo-sso-contract.md).
- Do not invent a new authentication or tenant architecture without approval.
- Avoid breaking API contracts or database compatibility without an explicit migration plan.

## 5. Security and tenant isolation

- Enforce authentication and authorization server-side.
- Derive tenant context from trusted authentication and platform contracts.
- Never trust a client-supplied tenant or organization ID as proof of access.
- Scope all tenant-owned reads, writes, updates, deletes, lists, and aggregate queries correctly.
- Validate relationships so records cannot reference unauthorized entities from another tenant.
- Enforce role permissions and entitlement requirements on the server.
- Add negative tests for unauthorized access and cross-tenant data exposure.
- Do not log secrets, credentials, tokens, or unnecessary sensitive information.
- Never bypass security controls to make a feature or demo work.
- Treat security and data-integrity failures as release blockers.

## 6. Backend quality

- Follow existing service, router, schema, model, and dependency-injection patterns.
- Validate inputs and return consistent, meaningful errors.
- Use safe transaction boundaries and appropriate database constraints.
- Handle missing records, invalid relationships, duplicate requests, and invalid state transitions.
- Use migrations for schema changes and verify upgrade compatibility.
- Do not create duplicate models, endpoints, or services for existing capabilities.
- Do not return fabricated data or fake success responses.

## 7. Frontend quality

- Follow the established React, TypeScript, routing, component, and styling conventions in the repository.
- Use real backend APIs for persisted business data.
- Provide appropriate loading, empty, success, validation, error, and access-denied states.
- Ensure forms validate inputs and communicate failures clearly.
- Keep layouts responsive, consistent, accessible, and keyboard-usable.
- Ensure every visible control has a real, working behavior.
- Drag-and-drop interactions must persist correctly and provide a reasonable alternative interaction.
- Use supplied design references for interaction and organization patterns without copying another product's branding.
- Avoid unrelated redesigns.

## 8. Testing and verification

- Inspect existing tests and determine the correct commands from repository documentation.
- Add or update tests for each story's acceptance criteria.
- Test happy paths, validation failures, authorization failures, tenant isolation, and relevant edge cases.
- Run focused tests during development and relevant regression tests before completion.
- Run frontend type checks, linting, and production builds where configured.
- Validate migrations when database changes are made.
- Distinguish pre-existing failures from failures introduced by the story.
- Never claim a test, build, migration, or manual verification passed unless it actually ran successfully.
- Fix introduced regressions before declaring the story complete.

## 9. Code review and release

Before requesting release approval:

- Inspect the complete diff and Git status.
- Check for unrelated files, secrets, debug code, unsafe queries, missing authorization, incomplete UI controls, and migration risks.
- Map each acceptance criterion to implementation and test evidence.
- Document known limitations and any unverified behavior.
- Report the branch, files changed, API/schema impact, security checks, exact test commands and results, and outstanding blockers.

After the user explicitly approves release:

- Stage only the intended story changes.
- Create a descriptive commit referencing the story ID.
- Push the feature branch.
- Create a pull request targeting `develop`.
- Verify the commit, remote branch, and PR URL.
- Never merge the PR unless explicitly authorized.
- If GitHub access or permissions are unavailable, report the blocker honestly.

## 10. Efficiency and communication

- Inspect relevant files first; broaden investigation only when evidence requires it.
- Avoid repeated full-repository scans and repeated architecture summaries.
- Run targeted tests before expensive full regression suites.
- Use the current approved architecture and contracts rather than reinventing them.
- Keep implementation plans and progress reports concise and evidence-based.
- Use a stronger reasoning model for complex architecture, tenancy, security, or cross-repository problems; use the standard coding model for ordinary story implementation.
- Ask the user only when an unresolved decision materially affects correctness, security, data compatibility, or scope.

## 11. Required completion report

For every story, report:

1. Story ID and outcome.
2. Branch and base branch.
3. Acceptance criteria and evidence.
4. Files changed and reasons.
5. API, schema, and migration impact.
6. Security and tenant-isolation checks.
7. Exact tests/builds run and results.
8. Known gaps and blockers.
9. Git status and diff summary.
10. Whether the story is ready for release approval.
