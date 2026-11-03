# Automation execution authority (WS6 WP5)

Who may activate an automation rule, and whose authority an automation action runs with.

## 1. The rule

An automation action runs with the authority of people, never of the event that triggered it. The user who
created a deal does not authorize what a rule does after that deal exists.

| Check | Where | Source of truth |
|---|---|---|
| The initiating user may run deal-created automation | execution gate (WP4) | `deals.create`, entitlement, switches, rate |
| The action type is supported | `authority.authorize_action` | `ACTION_PERMISSIONS` |
| The rule belongs to the organization and is active | `authority.authorize_action` | database |
| The **activator** is a member and holds `automation.update` and the action permission | `authority.authorize_action` | database, read at execution |
| The **target owner** (deal owner) holds the action permission | `authority.authorize_action` | database, read at execution |

The effective privilege is the intersection of the activator and the target owner, behind the gate for the
initiator. Nothing is cached between calls, so a permission removed after activation stops the next execution.

## 2. Action permissions

`ACTION_PERMISSIONS` in `app/automation_rules/authority.py` is the only mapping. It currently holds one action:

| Action | Permission | Why |
|---|---|---|
| `CREATE_FOLLOW_UP` | `leads.update` | The follow-up route requires it for a user doing the same thing by hand |

An action type with no mapping is refused at activation (`unsupported_action`) and at execution. A test fails if
the set of actions accepted by activation gets ahead of this table.

## 3. Activation

`activate_automation_rule` calls `authorize_activation` after the existing configuration checks. The activator
needs `automation.update` and the permission of every action in the rule, so configuring a rule cannot escalate
privilege: a user cannot activate a rule that does more than they could do themselves. This is checked on the
server in addition to the route's own permission check. A denial returns `403` with code
`AUTOMATION_AUTHORITY_DENIED` and a stable `reason_code`. The rule stays a draft.

Publishing is activation. There is no separate publish step in the model.

**The activator** is the rule's `updated_by_user_id` while the rule is active. An active rule cannot be edited,
and activation is the last write that sets the column, so no new column or migration is needed. Disabling and
activating again by another user moves the authority to that user. A rule whose `updated_by_user_id` is empty
(for example the user was deleted) fails closed with `activator_missing`.

Rules that were already active before this change run under their last updater. If that user no longer holds the
permissions, the rule stops running until a user who holds them activates it again.

## 4. Execution

For each action of each matching rule, in order:

1. `authorize_action` decides.
2. The decision is written **independently** (WP3): `denied` for a denial, `requested` for an allowed action.
   If this write fails, `AuditPersistenceError` propagates and the action does not run.
3. A denied action is recorded in the execution as `FAILED` with `reason_code`. No work is done.
4. An allowed action runs, then a `completed` row is written **in the business transaction** with
   `causation_id` pointing at the requested row.

A rollback therefore leaves the decision (a denial, or the fact that an action was authorized and attempted) and
removes the completion, so the log never claims success for work that did not commit. Decisions use the
idempotency key `automation-action:{rule}:{deal}:{index}:decision`, so a retry does not duplicate them.

## 5. Audit

Event type `automation_authority`. Attribution is the initiating user. Metadata carries `rule_id`, `deal_id`,
`action_type`, `action_index`, `activator_user_id`, `owner_user_id` and `reason_code`. No configuration content or
secret is stored.

| Action | Outcomes |
|---|---|
| `automation.rule.activate` | `denied`, or `requested` then `completed` |
| `automation.action.authorize` | `denied`, or `requested` |
| `automation.action.result` | `completed` |

## 6. Background and system actors

Unchanged and fail-closed. `execute_deal_created_automations` returns nothing when there is no user context, and
the WP4 gate refuses system actors. No service identity exists to authorize background automation, and none was
invented here.

## 7. Manual CRM

A denied action never stops the deal. The deal is created and the execution records `FAILED` with the reason.
One related fix: the execution notification went to the rule creator and raised when that user was no longer an
active member, which aborted deal creation. The notification is now skipped for an inactive creator.

## 8. Limitations

- One action type exists. Adding another means adding it to `ACTION_PERMISSIONS`, the activation validator and
  the executor together.
- Authoring a draft does not check action permissions. They are enforced at activation, which is the point a rule
  becomes executable.
- The `completed` row for an execution is written before the surrounding request commits, like other
  business-transaction audit rows, and rolls back with it.
- If the audit store is unavailable, deal creation with an active rule fails with the `AUDIT_UNAVAILABLE`
  response (fail closed). This already applied to the WP4 gate.
- Background execution needs a trusted service identity that does not exist yet.
