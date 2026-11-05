# Agent runtime (DFR1-019)

Status: implemented on `feature/DFR1-E07-agent-runtime`. Production execution is refused until the AI approvals in the
completion record are granted (see the open items in evidence section 27).

## Purpose and scope

An agent is an organization-scoped, versioned plan of approved steps. It runs through the platform's existing components only:

- model steps use the AI gateway (`ai.agents` capability, text task, structured output);
- tool steps use the typed tool registry (DFR1-018), as the initiating user;
- knowledge steps use knowledge retrieval (DFR1-016), limited to the agent's assigned documents;
- approval steps pause the run until a different member decides.

The runtime does not add a gateway, a tool registry or an authorization path. The plan is a fixed, ordered list, so an agent
cannot loop, recurse, or choose a tool that it was not assigned. The model never chooses a tool.

## Configuration

A configuration is strict JSON. Unknown fields are refused at every level (`app/agents/configuration.py`).

| Field | Meaning | Bounds |
|---|---|---|
| `category` | sales, operations or research | enum |
| `purpose`, `instructions` | what the agent is for and how it should behave | 500 and 4,000 characters |
| `language` | output language | en, de, es, fr, nl, sv, da, nb |
| `model_task` | the gateway task | text only |
| `autonomy_level` | `suggest` or `act`. A suggest-only agent needs a review step | enum |
| `approval_policy` | `none` or `before_result` (the result is released only after approval) | enum |
| `trigger` | how a run starts | `manual` only; event triggers are not available |
| `tools` | approved tool keys | registry keys only, at most 10 |
| `knowledge_document_ids` | assigned knowledge sources | identifiers, at most 20 |
| `inputs` | declared run inputs (`uuid`, `string`, `integer`) | at most 10 |
| `steps` | the plan (`tool`, `knowledge`, `model`, `approval`) | at least one; at most the step limit |
| `limits` | execution limits (see below) | each has a floor and a hard ceiling |

Step rules: a tool step names an assigned tool and its arguments refer only to declared inputs; a knowledge step needs at least one
assigned source; a model prompt may refer only to declared inputs and to earlier steps.

## Limits and retry policy

| Limit | Ceiling | Enforced |
|---|---|---|
| `max_duration_seconds` | 300 | Deadline set when the run starts; checked before every step. A run past its deadline ends as `timed_out`. |
| `max_steps` | 20 | Validation (plan length) and runtime check. |
| `max_tool_calls` | 10 | Validation (count of tool steps) and runtime check. |
| `max_retries` | 2 | Model steps only, for transient provider failures (`provider_unavailable`, `provider_timeout`). Each gateway call also retries inside the gateway, bounded by its own attempts. |
| `max_output_characters` | 16,384 | Size of the final result. A larger result fails the run as `output_too_large`. |
| `max_concurrent_executions` | 5 | Per agent, counted at creation under a row lock on the agent. |
| `max_executions_per_hour` | 1,000 | Per agent, counted over the previous hour. |
| Organization executions per hour | `AGENT_ORG_EXECUTIONS_PER_HOUR` (default 200) | Per organization, counted over the previous hour. |

Publishing refuses a configuration that does not set every limit. A draft may be saved while incomplete.

Retries: a transient model failure is retried up to `max_retries` times with a short backoff. Tool steps are not retried by the
runtime: tools are read-only, and a failed tool step fails the run with the tool's reason.

## Execution state model

```
queued ──start──▶ running ──┬──▶ succeeded
   │                        ├──▶ failed        (step failure, rejected approval, output too large, interrupted step)
   │                        ├──▶ timed_out     (deadline passed at a boundary)
   │                        ├──▶ cancelled     (cancel requested, observed at the next boundary)
   │                        └──▶ stopped       (membership revoked, permission removed, agent not published,
   │                                            AI disabled or not ready, budget refused)
   ├──▶ cancelled (cancelled while queued)
   └──▶ waiting_approval ──decision──▶ queued ──▶ running ... (approve)  or  failed (reject)
```

- Terminal states: `succeeded`, `failed`, `timed_out`, `cancelled`, `stopped`. A terminal execution is never run again.
- `queued`, `running` and `waiting_approval` count against the agent's concurrency limit.
- Each step has its own record with a status (`running`, `succeeded`, `failed`, `stopped`, `waiting`), a stable reason code, the
  attempt count and a bounded trace. A trace never holds argument values, raw documents or unbounded model output.

## Execution flow

1. **Create** (`create_execution`): the initiator must be an active member with `agents.run`. The agent must be published. The
   input is validated against the pinned version's declared inputs. Concurrency, the per-agent hour and the per-organization hour are
   checked under a lock on the agent. The static checks (tools, knowledge access, model route, AI capability) run once. The
   execution is stored with its exact version and an outbox event is queued. A repeated idempotency key with the same agent and input
   returns the stored execution; the same key with different content is refused.
2. **Run** (outbox handler `agent.execution_requested`): a duplicate or late event finds the execution in a state that is not
   runnable and does nothing. The run continues from the next unrecorded step, so a restart resumes rather than repeats.
3. **Boundary checks** before each step: cancellation, deadline, and revalidation (membership, `agents.run`, agent published,
   AI capability through the policy check). A failed check ends the run at that boundary with its reason. No later step runs.
4. **Step**: model, tool, knowledge or approval, as described above. Each step is recorded before the run moves on.
5. **Finish**: the final result is the last model step's structured output, bounded by `max_output_characters`. An approval-before-
   result policy pauses the run once more before the result is released.

A step that was started but not recorded as finished (a restart mid-step) fails the run as `interrupted_step`. The runtime never
repeats a step whose effects are unknown.

## Lifecycle and versioning

- **Draft**: one mutable configuration per agent. Edits change only the draft. The published version is never changed.
- **Publish**: validates the draft against every publish rule, then writes the next immutable version with its validation snapshot,
  and points the agent at it. Publish rules: all limits set; a category, purpose and instructions; the publisher holds each tool's
  permission and `documents.read` when knowledge is used; each knowledge source exists, is available, eligible and scanned; a text
  model is routed; the AI capability is switched on (`execution_gates_pending` is not a blocker, see below).
- **Versions** are never updated. Rollback moves the agent's pointer to an earlier version after revalidating it. No version is copied
  or edited, and no new version is created.
- **Executions are pinned** to the version they started with. Publishing, rolling back or editing the draft never changes a run in
  progress. Pausing or archiving the agent does stop a run, at its next boundary.
- **Pause and resume**: pausing stops new runs and in-flight runs at their next boundary. Resuming revalidates the current version.
- **Archive** is terminal. No run starts, and an in-flight run stops at its next boundary.
- **Preview** describes the plan and whether the draft could be published. It calls no tool, no model and no provider.

`execution_gates_pending` means the production approvals for AI execution are still missing. Publishing and preview allow it,
because a draft can be prepared before approval. Every execution is still refused at the execution gate until the approvals exist.

## Permission model

| Permission | Allows |
|---|---|
| `agents.read` | View agents, versions, executions and steps; preview; list the approved tools |
| `agents.manage` | Create agents and edit drafts |
| `agents.publish` | Publish, roll back, pause, resume and archive; cancel another member's run |
| `agents.run` | Start a run and cancel your own run |
| `agents.approve` | Approve or reject an approval step (never your own run) |

The system Owner role holds all five. No other role receives them automatically. Tool steps additionally need each tool's own
permission, checked at the step, and knowledge steps need `documents.read`. A member can never grant permissions through an agent.

## Tenant security

- Every query and write is scoped by the verified organization. A record in another organization returns the same answer as a
  missing one.
- Arguments never carry an organization, tenant or authorization claim; the schema refuses unknown fields.
- Audit records are written in the organization, attributed to the acting user, and hold names and reason codes, not values.

## Approvals

Approval steps are recorded on the execution's own step row and decided through `agents.approve`. They do not use the governance
approval requests (E13), because those are keyed to a single exact payload hash and require their capability to be marked
as approval-required, which would force an approval on every agent step. Unifying the two is a follow-up.

## CRM action steps (DFR1-021)

A plan step may be a `crm_action`. It names one key from the fixed catalogue in `app/agents/crm_action_catalogue.py`:
`intake.process`, `intake.resolve_identity`, `lead.calculate_priority` and `qualification.record`. The arguments are references only:
`$input.name` for a declared input, or `$step.N.field` for a field of an earlier step's output. A literal value is refused when the
configuration is saved.

Each action runs as the initiating member. The runtime checks the action's permissions before the handler runs, and a refused permission
stops the execution with `crm_permission_denied`. Actions write only through the intake service, the DFR1-020 priority service and the
qualification service. They never change a lead's own fields. A failed action ends the execution with its reason and is not retried, so a
repeat cannot duplicate a write.

Templates for the receptionist, identity resolver, lead scoring and lead qualification agents live in `app/agents/templates.py`. A
template is a starting configuration. It names no permission, and creating from one stores an ordinary draft.

## Known limits of this release

- Execution history (`agent_executions`, `agent_execution_steps`) is not yet covered by privacy export or deletion. It is recorded as
  `not_covered` in the table inventory and must be covered before production runs.
- The worker holds the execution's row lock for the length of a run, which serializes runs of one execution and keeps decisions
  consistent. Long runs hold a database connection for their duration.
- Budget exhaustion is enforced by the gateway (tokens and images). Tool calls and agent executions are counted and rate-limited but
  are not metered as AI credits; the usage ledger has no unit for them.
- Event triggers are not available. Runs are started manually.
- The frontend page is reachable at `/agents` and is not yet in the workspace navigation menu.
