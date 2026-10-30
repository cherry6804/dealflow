
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  LockKeyhole,
  Pencil,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react";

import {
  teamApi,
  type PermissionCatalogueItem,
  type TeamRole,
} from "../../../services/teamApi";
import "./OrganizationRolesPanel.css";

interface OrganizationRolesPanelProps {
  onChanged?: () => void | Promise<void>;
}

interface RoleForm {
  name: string;
  description: string;
  permissionKeys: string[];
}

const EMPTY_FORM: RoleForm = {
  name: "",
  description: "",
  permissionKeys: [],
};

function getErrorMessage(error: unknown): string {
  return error instanceof Error && error.message.trim()
    ? error.message
    : "Something went wrong. Please try again.";
}

function isProtected(role: TeamRole): boolean {
  return (
    role.is_system === true ||
    role.name.trim().toLocaleLowerCase() === "dealflow owner"
  );
}

function groupPermissions(
  permissions: PermissionCatalogueItem[],
): Array<[string, PermissionCatalogueItem[]]> {
  const groups = new Map<string, PermissionCatalogueItem[]>();

  for (const permission of permissions) {
    const current = groups.get(permission.group) ?? [];
    current.push(permission);
    groups.set(permission.group, current);
  }

  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export default function OrganizationRolesPanel({
  onChanged,
}: OrganizationRolesPanelProps) {
  const [roles, setRoles] = useState<TeamRole[]>([]);
  const [permissions, setPermissions] = useState<PermissionCatalogueItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [busyRoleId, setBusyRoleId] = useState<string | null>(null);
  const [editingRole, setEditingRole] = useState<TeamRole | null>(null);
  const [form, setForm] = useState<RoleForm>(EMPTY_FORM);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadRoles = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [roleResult, permissionResult] = await Promise.all([
        teamApi.listManageableRoles(),
        teamApi.listPermissions(),
      ]);

      setRoles(roleResult);
      setPermissions(permissionResult);
    } catch (cause) {
      setError(getErrorMessage(cause));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRoles();
  }, [loadRoles]);

  const permissionGroups = useMemo(
    () => groupPermissions(permissions),
    [permissions],
  );

  const visibleRoles = useMemo(() => {
    const query = search.trim().toLowerCase();

    if (!query) return roles;

    return roles.filter((role) =>
      [role.name, role.description ?? ""].some((value) =>
        value.toLowerCase().includes(query),
      ),
    );
  }, [roles, search]);

  function openCreateDialog() {
    setEditingRole(null);
    setForm(EMPTY_FORM);
    setError(null);
    setNotice(null);
    setDialogOpen(true);
  }

  function openEditDialog(role: TeamRole) {
    if (isProtected(role) || !role.is_active) return;

    setEditingRole(role);
    setForm({
      name: role.name,
      description: role.description ?? "",
      permissionKeys: (role.permission_keys ?? []).filter((key) =>
        permissions.some((permission) => permission.key === key && permission.assignable),
      ),
    });
    setError(null);
    setNotice(null);
    setDialogOpen(true);
  }

  function closeDialog() {
    if (saving) return;

    setDialogOpen(false);
    setEditingRole(null);
    setForm(EMPTY_FORM);
  }

  function togglePermission(key: string, checked: boolean) {
    setForm((current) => ({
      ...current,
      permissionKeys: checked
        ? [...new Set([...current.permissionKeys, key])]
        : current.permissionKeys.filter((item) => item !== key),
    }));
  }

  function togglePermissionGroup(
    groupPermissions: PermissionCatalogueItem[],
    checked: boolean,
  ) {
    const keys = groupPermissions
      .filter((permission) => permission.assignable)
      .map((permission) => permission.key);

    setForm((current) => ({
      ...current,
      permissionKeys: checked
        ? [...new Set([...current.permissionKeys, ...keys])]
        : current.permissionKeys.filter((key) => !keys.includes(key)),
    }));
  }

  async function handleSave(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (saving) return;

    const name = form.name.trim();
    if (name.length < 2) {
      setError("Role name must contain at least two characters.");
      return;
    }

    setSaving(true);
    setError(null);
    setNotice(null);

    try {
      const payload = {
        name,
        description: form.description.trim() || null,
        permission_keys: form.permissionKeys,
      };

      if (editingRole) {
        await teamApi.updateRole(editingRole.id, payload);
        setNotice(`Role "${name}" updated successfully.`);
      } else {
        await teamApi.createRole(payload);
        setNotice(`Role "${name}" created successfully.`);
      }

      setDialogOpen(false);
      setEditingRole(null);
      setForm(EMPTY_FORM);

      await loadRoles();
      await onChanged?.();
    } catch (cause) {
      setError(getErrorMessage(cause));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeactivate(role: TeamRole) {
    if (isProtected(role) || !role.is_active) return;

    const confirmed = window.confirm(
      `Deactivate "${role.name}"? This cannot proceed while members are assigned to it or invitations are pending. Reassign members and resolve invitations first.`,
    );

    if (!confirmed) return;

    setBusyRoleId(role.id);
    setError(null);
    setNotice(null);

    try {
      await teamApi.deactivateRole(role.id);
      setNotice(`Role "${role.name}" deactivated.`);
      await loadRoles();
      await onChanged?.();
    } catch (cause) {
      setError(getErrorMessage(cause));
    } finally {
      setBusyRoleId(null);
    }
  }

  const activeCount = roles.filter((role) => role.is_active).length;
  const customCount = roles.filter((role) => !isProtected(role)).length;

  return (
    <section className="org-roles" aria-label="Organization roles">
      <header className="org-roles__header">
        <div>
          <span className="org-roles__eyebrow">ACCESS CONTROL</span>
          <h2>Roles &amp; permissions</h2>
          <p>
            Control what each role can access in this organization.
            System roles are protected.
          </p>
        </div>

        <div className="org-roles__header-actions">
          <button
            type="button"
            className="org-roles__button org-roles__button--secondary"
            onClick={() => void loadRoles()}
            disabled={loading}
          >
            <RefreshCw size={15} />
            Refresh
          </button>

          <button
            type="button"
            className="org-roles__button org-roles__button--primary"
            onClick={openCreateDialog}
            disabled={loading || permissions.length === 0}
          >
            <Plus size={16} />
            Create role
          </button>
        </div>
      </header>

      {error && (
        <div className="org-roles__alert org-roles__alert--error" role="alert">
          <AlertCircle size={17} />
          <span>{error}</span>
          <button type="button" aria-label="Dismiss error" onClick={() => setError(null)}>
            <X size={15} />
          </button>
        </div>
      )}

      {notice && (
        <div className="org-roles__alert org-roles__alert--success" role="status">
          <CheckCircle2 size={17} />
          <span>{notice}</span>
          <button type="button" aria-label="Dismiss message" onClick={() => setNotice(null)}>
            <X size={15} />
          </button>
        </div>
      )}

      <div className="org-roles__summary">
        <article>
          <span>Active roles</span>
          <strong>{loading ? "—" : activeCount}</strong>
        </article>
        <article>
          <span>Custom roles</span>
          <strong>{loading ? "—" : customCount}</strong>
        </article>
        <article>
          <span>Available permissions</span>
          <strong>{loading ? "—" : permissions.filter((item) => item.assignable).length}</strong>
        </article>
      </div>

      <div className="org-roles__toolbar">
        <label>
          <span className="org-roles__sr-only">Search roles</span>
          <input
            type="search"
            placeholder="Search roles…"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <span>{visibleRoles.length} of {roles.length} roles</span>
      </div>

      {loading ? (
        <div className="org-roles__state" role="status">
          Loading roles and permissions…
        </div>
      ) : visibleRoles.length === 0 ? (
        <div className="org-roles__state">
          <ShieldCheck size={24} />
          <strong>{search ? "No matching roles" : "No roles available"}</strong>
          <p>{search ? "Try another search term." : "Create a custom role to define tailored access."}</p>
        </div>
      ) : (
        <div className="org-roles__list">
          {visibleRoles.map((role) => {
            const protectedRole = isProtected(role);
            const permissionCount = role.permission_keys?.length ?? 0;

            return (
              <article className="org-roles__card" key={role.id}>
                <div className="org-roles__card-main">
                  <span className={`org-roles__role-icon${protectedRole ? " is-protected" : ""}`}>
                    {protectedRole ? <LockKeyhole size={18} /> : <ShieldCheck size={18} />}
                  </span>

                  <div className="org-roles__role-info">
                    <div className="org-roles__role-title">
                      <h3>{role.name}</h3>
                      {protectedRole && <span className="org-roles__badge">System role</span>}
                      {!role.is_active && <span className="org-roles__badge is-inactive">Inactive</span>}
                    </div>
                    <p>{role.description || "No description provided."}</p>
                    <div className="org-roles__metadata">
                      <span>{permissionCount} permissions</span>
                      <span>{role.is_active ? "Active" : "Deactivated"}</span>
                    </div>
                  </div>
                </div>

                <div className="org-roles__card-actions">
                  {protectedRole ? (
                    <span className="org-roles__protected-note">
                      <LockKeyhole size={14} />
                      Protected
                    </span>
                  ) : role.is_active ? (
                    <>
                      <button
                        type="button"
                        className="org-roles__icon-button"
                        aria-label={`Edit ${role.name}`}
                        title="Edit role"
                        onClick={() => openEditDialog(role)}
                      >
                        <Pencil size={15} />
                      </button>
                      <button
                        type="button"
                        className="org-roles__icon-button is-danger"
                        aria-label={`Deactivate ${role.name}`}
                        title="Deactivate role"
                        disabled={busyRoleId === role.id}
                        onClick={() => void handleDeactivate(role)}
                      >
                        <Trash2 size={15} />
                      </button>
                    </>
                  ) : (
                    <span className="org-roles__protected-note">Inactive</span>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      <aside className="org-roles__security-note">
        <LockKeyhole size={17} />
        <p>
          <strong>Security enforced by the backend.</strong> Protected
          permissions cannot be granted by custom roles. Organization
          boundaries are validated on every role-management request.
        </p>
      </aside>

      {dialogOpen && (
        <div
          className="org-roles__overlay"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeDialog();
          }}
        >
          <section
            className="org-roles__dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="org-role-dialog-title"
          >
            <header className="org-roles__dialog-header">
              <div>
                <span className="org-roles__eyebrow">ROLE CONFIGURATION</span>
                <h2 id="org-role-dialog-title">
                  {editingRole ? "Edit role" : "Create role"}
                </h2>
                <p>Choose a clear name and grant only the permissions required.</p>
              </div>
              <button
                type="button"
                className="org-roles__icon-button"
                aria-label="Close dialog"
                onClick={closeDialog}
                disabled={saving}
              >
                <X size={18} />
              </button>
            </header>

            <form onSubmit={handleSave}>
              <div className="org-roles__dialog-body">
                {error && (
                  <div className="org-roles__alert org-roles__alert--error" role="alert">
                    <AlertCircle size={17} />
                    <span>{error}</span>
                  </div>
                )}

                <div className="org-roles__form-grid">
                  <label className="org-roles__field">
                    <span>Role name <b>*</b></span>
                    <input
                      autoFocus
                      required
                      minLength={2}
                      maxLength={80}
                      value={form.name}
                      onChange={(event) => setForm((current) => ({
                        ...current,
                        name: event.target.value,
                      }))}
                      placeholder="e.g. Sales Executive"
                    />
                  </label>

                  <label className="org-roles__field">
                    <span>Description</span>
                    <textarea
                      rows={3}
                      maxLength={500}
                      value={form.description}
                      onChange={(event) => setForm((current) => ({
                        ...current,
                        description: event.target.value,
                      }))}
                      placeholder="Describe the responsibilities of this role"
                    />
                  </label>
                </div>

                <div className="org-roles__permission-heading">
                  <div>
                    <h3>Permissions</h3>
                    <p>Select the operations this role is allowed to perform.</p>
                  </div>
                  <span>{form.permissionKeys.length} selected</span>
                </div>

                <div className="org-roles__permission-groups">
                  {permissionGroups.map(([group, groupItems]) => {
                    const assignableItems = groupItems.filter((item) => item.assignable);
                    const selectedCount = assignableItems.filter((item) =>
                      form.permissionKeys.includes(item.key),
                    ).length;
                    const allSelected =
                      assignableItems.length > 0 &&
                      selectedCount === assignableItems.length;

                    return (
                      <fieldset className="org-roles__permission-group" key={group}>
                        <legend>
                          <span>{group.replaceAll("_", " ")}</span>
                          <label className="org-roles__select-group">
                            <input
                              type="checkbox"
                              checked={allSelected}
                              disabled={assignableItems.length === 0}
                              onChange={(event) =>
                                togglePermissionGroup(assignableItems, event.target.checked)
                              }
                            />
                            Select group
                          </label>
                        </legend>

                        {groupItems.map((permission) => (
                          <label
                            className={`org-roles__permission${permission.assignable ? "" : " is-disabled"}`}
                            key={permission.key}
                          >
                            <input
                              type="checkbox"
                              checked={form.permissionKeys.includes(permission.key)}
                              disabled={!permission.assignable}
                              onChange={(event) =>
                                togglePermission(permission.key, event.target.checked)
                              }
                            />
                            <span>
                              <strong>{permission.key}</strong>
                              <small>{permission.description}</small>
                              {!permission.assignable && (
                                <em>Protected permission</em>
                              )}
                            </span>
                          </label>
                        ))}
                      </fieldset>
                    );
                  })}
                </div>
              </div>

              <footer className="org-roles__dialog-footer">
                <button
                  type="button"
                  className="org-roles__button org-roles__button--secondary"
                  onClick={closeDialog}
                  disabled={saving}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="org-roles__button org-roles__button--primary"
                  disabled={saving}
                >
                  {saving ? "Saving…" : editingRole ? "Save changes" : "Create role"}
                </button>
              </footer>
            </form>
          </section>
        </div>
      )}
    </section>
  );
}
