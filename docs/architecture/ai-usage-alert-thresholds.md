# AI usage alert thresholds (WS6 WP2)

Status: implemented in WS6 WP2. Owner: DealFlow backend and governance UI. Builds on the AI usage
ledger hardened in WP1 (`ai-usage-reservations.md`).

## 1. What this changes

Before WP2, every organization's budget alerts were fixed at 70, 85 and 100 percent. WP2 lets an
organization choose its three alert percentages. The ledger, the budget model, the outbox and the
alert delivery are reused. No second ledger or budget system is introduced.

WP2 does not change budget amounts, usage units, prices, plan entitlements, or provider cost and
customer credit separation. An organization with no saved setting keeps the defaults, so existing
behaviour is unchanged.

## 2. Rules

Enforced on the server, in `app/governance/alert_thresholds.py`:

- Exactly three values.
- Each a whole number from 1 to 100. Booleans and strings are refused.
- Strictly increasing, which rules out duplicates and reordering.
- The highest value must be 100, so the final alert still means the budget is exhausted.

The top-value rule is a product choice made for WP2 and is open for review. Without it, an
organization could remove the "budget exhausted" alert.

## 3. Storage and migration

Revision `f2a8c4e6b0d3`, on top of `e6b1d7a4c9f2`.

- `organization_usage_alert_settings`: one optional row per organization, with `threshold_low`,
  `threshold_mid`, `threshold_high`, a `version` counter, and the updater. A check constraint enforces
  the same ordering and the top value of 100.
- `organization_usage_budgets.alerted_thresholds` (JSON list of whole numbers): the configured thresholds
  already covered by a delivered alert, for one budget and period. It is backfilled from
  `last_alert_percent`. Old code only ever stored 70, 85 or 100 there, so the backfill is exact: a budget
  with `last_alert_percent = 85` gets `[70, 85]`, and one at 100 gets `[70, 85, 100]`. A budget with no
  delivered alert gets `[]`.

  **Why JSON rather than JSONB or a PostgreSQL array.** The list is at most three whole numbers from 1 to
  100. It is read only to decide the next alert, and never searched, indexed or filtered by element. JSON
  maps to the same Python list on PostgreSQL and SQLite, so the model compiles on the SQLite engine that
  some test modules use. A PostgreSQL array does not compile there, and it caused the first WP2 suite
  failure. JSONB would add binary storage and key ordering that this use does not need, and would restrict
  the model to PostgreSQL. Values are validated before they are written, and the backfill writes them in
  ascending order.
- `last_alert_percent` is kept and still holds the highest delivered threshold, so WP1 readers see the
  same values.

No existing organization gets a settings row. Its defaults apply without any backfill.

Downgrade drops the settings table and the new column. Delivered alerts stay recorded through
`last_alert_percent`. Organizations that had configured thresholds lose them and get the defaults back.

## 4. Why delivered state is tracked per threshold

The WP1 code compared a single number, `last_alert_percent`, to decide whether an alert was due. That
is wrong once thresholds can change. Suppose an organization delivered its 85 alert, and then changed its
thresholds to 50, 80 and 100. A number comparison would suppress the 50 and 80 alerts, which were never
delivered under the new settings. Using `alerted_thresholds` avoids that: each configured threshold is
tracked on its own.

Eligibility is state-based, not crossing-based. A configured threshold `t` is pending when
`used * 100 >= t * limit` and `t` is not in `alerted_thresholds`. Only the highest pending threshold is
queued, so one change that reaches several thresholds produces one alert. This matches the WP1 behaviour,
which the existing tests lock in.

## 5. When thresholds are evaluated

Pending thresholds are checked at every point where usage or the limit changes:

- a reservation, a settlement, or a direct record;
- a budget limit change, which can put current usage over a threshold with no new usage;
- a threshold change, which announces any threshold the current usage already reaches.

## 6. Delivery and idempotency

- Each queued alert uses the outbox key `usage-threshold:{budget}:{threshold}`. A repeat returns the
  queued event, so retries and concurrent usage queue at most one alert per threshold.
- The handler creates in-app notifications for the administrators (holders of
  `governance.budgets.manage` through the system Owner role). Notification keys include the event key
  and the recipient, so a redelivery creates no duplicate.
- Delivery marks the threshold covered, and also every configured threshold below it. Those lower alerts
  are superseded, as before. A lower threshold configured later is still announced, because it is not in
  the covered list.
- A queued alert is not marked covered. Only a delivered alert is.

## 7. Concurrency

- Usage changes lock the budget row first, then read the thresholds.
- A threshold change locks the current-period budgets first, in id order, then writes the settings row
  with an upsert. A usage change therefore either sees the old thresholds, or waits and then sees the new
  ones.
- Both paths queue the same idempotent keys, so a race never queues a duplicate and never skips an
  eligible threshold.

## 8. Permissions and audit

| Action | Permission | Who |
|---|---|---|
| Read thresholds | `governance.usage.read` | Anyone who can view usage |
| Change thresholds | `governance.budgets.manage` | System Owner only (owner-only key) |

A custom role holding `governance.budgets.manage` cannot change thresholds. The owner-only rule is
enforced by `permission_granted`, as for budgets.

Every change writes an audit event with the action `governance.alert_thresholds.updated`, the actor, the
before and after values, and both versions. A change to the same values writes nothing.

## 9. Notification wording

Alerts are in-app notifications only. The panel and the API say so. No email, SMS or external message is
sent by this work. A notification being queued is not the same as it being delivered: the UI describes the
setting, not a delivery guarantee.

## 10. Known limitations

- The top threshold must be 100. This is a product decision and can be revisited.
- Thresholds apply to every unit for the organization, not per unit.
- The highest-only rule means a change that reaches several thresholds announces one alert. The lower
  reached thresholds are covered when that alert is delivered, so they are not announced separately.
- The governance UI uses native controls and the shared confirmation dialog, matching the existing
  governance screens. This frontend has no Quark component library.
- A queued alert that is dead-lettered (for example, no administrator) is not retried automatically. It
  is replayed by an operator after the configuration is corrected, as before.
