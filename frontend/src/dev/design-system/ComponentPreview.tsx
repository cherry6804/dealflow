import { useState } from "react";

import {
  Badge,
  Button,
  Checkbox,
  Dialog,
  Menu,
  Notification,
  Popover,
  RadioGroup,
  SelectField,
  Tabs,
  TextField,
  TextareaField,
  Tooltip,
} from "../../components/ui";
import "./ComponentPreview.css";
import { ThemeToggle } from "../../theme/ThemeToggle";

/**
 * Development-only component preview. The route is registered only when import.meta.env.DEV is true, so it is not
 * part of production builds. It uses fixture values only: no data is loaded, and no authentication is bypassed.
 * Use the theme control in the header to check each state in light and dark themes.
 */
export default function ComponentPreview() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [plan, setPlan] = useState("starter");
  const [notice, setNotice] = useState(true);
  const [checked, setChecked] = useState(false);

  return (
    <main className="df-preview" aria-labelledby="df-preview-title">
      <header className="df-preview-header">
        <h1 id="df-preview-title" className="df-preview-title">Component preview</h1>
        <p className="df-preview-note">Development only. Fixture values. Toggle the theme in the header to check both themes.</p>
        <ThemeToggle />
      </header>

      <section className="df-preview-section" aria-labelledby="df-preview-buttons">
        <h2 id="df-preview-buttons">Buttons</h2>
        <div className="df-preview-row">
          <Button variant="primary">Add deal</Button>
          <Button variant="secondary">Export</Button>
          <Button variant="tertiary">Cancel</Button>
          <Button variant="danger">Delete</Button>
          <Button variant="primary" loading>Saving</Button>
          <Button variant="primary" disabled>Disabled</Button>
          <Button variant="secondary" size="sm">Small</Button>
          <Button variant="secondary" iconOnly aria-label="Add filter" icon={<span aria-hidden="true">+</span>}>Add filter</Button>
        </div>
        <p className="df-preview-note">Hover and focus: move the pointer over a button or press Tab to see the focus ring.</p>
      </section>

      <section className="df-preview-section" aria-labelledby="df-preview-fields">
        <h2 id="df-preview-fields">Fields</h2>
        <div className="df-preview-grid">
          <TextField label="Full name" placeholder="Elena Ruiz" />
          <TextField label="Contact email" required defaultValue="elena@" error="Enter a complete email, for example elena@company.com" />
          <TextField label="Deal value" helper="Enter the amount in USD" />
          <TextField label="Read-only reference" disabled defaultValue="DF-1048" />
          <SelectField
            label="Stage"
            value={plan}
            onChange={(event) => setPlan(event.target.value)}
            options={[
              { value: "starter", label: "Starter" },
              { value: "pro", label: "Pro" },
              { value: "legacy", label: "Legacy (disabled)", disabled: true },
            ]}
          />
          <TextareaField label="Notes" helper="Visible to your team only" />
        </div>
      </section>

      <section className="df-preview-section" aria-labelledby="df-preview-choices">
        <h2 id="df-preview-choices">Checkboxes and radio controls</h2>
        <div className="df-preview-row">
          <Checkbox label="Send weekly summary" checked={checked} onChange={(event) => setChecked(event.target.checked)} />
          <Checkbox label="Select all (partly selected)" indeterminate onChange={() => undefined} />
          <Checkbox label="Unavailable option" disabled onChange={() => undefined} />
        </div>
        <RadioGroup
          name="preview-plan"
          label="Plan"
          value={plan}
          onChange={setPlan}
          options={[
            { value: "starter", label: "Starter" },
            { value: "pro", label: "Pro" },
            { value: "enterprise", label: "Enterprise (not available)", disabled: true },
          ]}
        />
      </section>

      <section className="df-preview-section" aria-labelledby="df-preview-badges">
        <h2 id="df-preview-badges">Badges</h2>
        <div className="df-preview-row">
          <Badge tone="neutral">Draft</Badge>
          <Badge tone="success">Won</Badge>
          <Badge tone="active">Active</Badge>
          <Badge tone="pending">Pending</Badge>
          <Badge tone="danger">Overdue</Badge>
          <Badge tone="automated">AI enriched</Badge>
        </div>
      </section>

      <section className="df-preview-section" aria-labelledby="df-preview-notifications">
        <h2 id="df-preview-notifications">Notifications</h2>
        <div className="df-preview-stack">
          <Notification tone="info" title="Import queued" />
          <Notification tone="success" title="Changes saved" />
          <Notification tone="warning" title="Two records need an owner" />
          <Notification tone="danger" title="Deals could not be loaded">
            Check your connection and try again.
          </Notification>
          {notice ? (
            <Notification
              tone="info"
              title="Dismissible notice"
              dismissLabel="Dismiss notice"
              onDismiss={() => setNotice(false)}
            />
          ) : null}
        </div>
      </section>

      <section className="df-preview-section" aria-labelledby="df-preview-overlays">
        <h2 id="df-preview-overlays">Menus, popovers, tooltips and dialogs</h2>
        <div className="df-preview-row">
          <Menu
            triggerLabel="Actions"
            items={[
              { id: "edit", label: "Edit deal", onSelect: () => undefined },
              { id: "duplicate", label: "Duplicate", onSelect: () => undefined },
              { id: "delete", label: "Delete deal", destructive: true, onSelect: () => undefined },
            ]}
          />
          <Popover triggerLabel="Details">
            <p className="df-preview-note">Popovers hold rich content. Escape closes and returns focus.</p>
          </Popover>
          <Tooltip label="Customise visible columns">
            <Button variant="secondary" iconOnly aria-label="Columns" icon={<span aria-hidden="true">▦</span>}>Columns</Button>
          </Tooltip>
          <Button variant="secondary" onClick={() => setDialogOpen(true)}>Open dialog</Button>
        </div>
        <Dialog
          open={dialogOpen}
          onClose={() => setDialogOpen(false)}
          title="Delete deal?"
          closeLabel="Close dialog"
          description="Meridian Tower HQ lease and its notes will be deleted. This cannot be undone."
          footer={
            <>
              <Button variant="secondary" onClick={() => setDialogOpen(false)}>Cancel</Button>
              <Button variant="danger" onClick={() => setDialogOpen(false)}>Delete deal</Button>
            </>
          }
        >
          <p className="df-preview-note">Focus moves to the first control in the dialog and returns to the trigger on close. Escape closes without deleting.</p>
        </Dialog>
      </section>

      <section className="df-preview-section" aria-labelledby="df-preview-tabs">
        <h2 id="df-preview-tabs">Tabs</h2>
        <Tabs
          label="Deal sections"
          tabs={[
            { id: "people", label: "People", content: <p>Primary contacts for this deal.</p> },
            { id: "companies", label: "Companies", content: <p>Companies linked to this deal.</p> },
            { id: "segments", label: "Segments", content: <p>Not available yet.</p>, disabled: true },
          ]}
        />
      </section>
    </main>
  );
}
