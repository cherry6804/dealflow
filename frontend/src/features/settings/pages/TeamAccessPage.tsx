
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Mail,
  RefreshCw,
  ShieldCheck,
  Users,
  UserPlus,
  X,
} from "lucide-react";

import {
  teamApi,
  type TeamInvitation,
  type TeamMember,
  type TeamRole,
} from "../../../services/teamApi";
import TeamMembersTable from "../components/TeamMembersTable";
import PendingInvitations from "../components/PendingInvitations";
import InviteMemberDialog from "../components/InviteMemberDialog";
import RemoveMemberDialog from "../components/RemoveMemberDialog";
import OrganizationRolesPanel from "../components/OrganizationRolesPanel";
import "./TeamAccessPage.css";
import {
  removalErrorMessage,
  removalPendingMessage,
  removalSuccessMessage,
} from "../teamRemoval";

type ActiveTab = "members" | "invitations" | "roles";

const REQUEST_TIMEOUT_MS = 15000;

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return "Something went wrong. Please try again.";
}

function withTimeout<T>(
  request: Promise<T>,
  requestName: string,
  timeoutMs = REQUEST_TIMEOUT_MS,
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      reject(
        new Error(
          `${requestName} timed out. Please check your connection and try again.`,
        ),
      );
    }, timeoutMs);

    request.then(
      (result) => {
        clearTimeout(timeoutId);
        resolve(result);
      },
      (error: unknown) => {
        clearTimeout(timeoutId);
        reject(error);
      },
    );
  });
}

function isPending(invitation: TeamInvitation): boolean {
  return (
    invitation.status.toLowerCase() === "pending" &&
    new Date(invitation.expires_at).getTime() > Date.now()
  );
}

function isArrayResult<T>(value: unknown): value is T[] {
  return Array.isArray(value);
}

export default function TeamAccessPage() {
  const [members, setMembers] = useState<TeamMember[]>([]);
  const [invitations, setInvitations] = useState<TeamInvitation[]>([]);
  const [roles, setRoles] = useState<TeamRole[]>([]);

  const [activeTab, setActiveTab] = useState<ActiveTab>("members");
  const [search, setSearch] = useState("");
  const [invitationFilter, setInvitationFilter] = useState("all");

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogSubmitting, setDialogSubmitting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [removalTarget, setRemovalTarget] = useState<TeamMember | null>(null);
  const [removalSubmitting, setRemovalSubmitting] = useState(false);
  const [removalError, setRemovalError] = useState<string | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const loadTeam = useCallback(async (quiet = false) => {
    if (quiet) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    setError(null);

    try {
      const results = await Promise.allSettled([
        withTimeout(teamApi.listMembers(), "Loading team members"),
        withTimeout(teamApi.listRoles(), "Loading team roles"),
        withTimeout(
          teamApi.listInvitations(),
          "Loading team invitations",
        ),
      ]);

      const errors: string[] = [];

      const [membersResult, rolesResult, invitationsResult] = results;

      if (membersResult.status === "fulfilled") {
        if (isArrayResult<TeamMember>(membersResult.value)) {
          setMembers(membersResult.value);
        } else {
          errors.push("The members API returned an unexpected response.");
        }
      } else {
        errors.push(`Members: ${errorMessage(membersResult.reason)}`);
      }

      if (rolesResult.status === "fulfilled") {
        if (isArrayResult<TeamRole>(rolesResult.value)) {
          setRoles(rolesResult.value);
        } else {
          errors.push("The roles API returned an unexpected response.");
        }
      } else {
        errors.push(`Roles: ${errorMessage(rolesResult.reason)}`);
      }

      if (invitationsResult.status === "fulfilled") {
        if (isArrayResult<TeamInvitation>(invitationsResult.value)) {
          setInvitations(invitationsResult.value);
        } else {
          errors.push(
            "The invitations API returned an unexpected response.",
          );
        }
      } else {
        errors.push(
          `Invitations: ${errorMessage(invitationsResult.reason)}`,
        );
      }

      if (errors.length > 0) {
        setError(errors.join(" "));
      }
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void loadTeam();
  }, [loadTeam]);

  const pendingCount = useMemo(
    () => invitations.filter(isPending).length,
    [invitations],
  );

  const visibleMembers = useMemo(() => {
    const query = search.trim().toLowerCase();

    if (!query) {
      return members;
    }

    return members.filter((member) =>
      [
        member.display_name,
        member.email,
        ...member.roles.map((role) => role.name),
      ].some((value) => value.toLowerCase().includes(query)),
    );
  }, [members, search]);

  const visibleInvitations = useMemo(() => {
    const query = search.trim().toLowerCase();

    return invitations.filter((invitation) => {
      const matchesSearch = invitation.email
        .toLowerCase()
        .includes(query);

      const pending = isPending(invitation);
      const status = invitation.status.toLowerCase();

      const matchesFilter =
        invitationFilter === "all" ||
        (invitationFilter === "pending" && pending) ||
        (invitationFilter === "accepted" && status === "accepted") ||
        (invitationFilter === "revoked" && status === "revoked") ||
        (invitationFilter === "expired" &&
          status === "pending" &&
          !pending);

      return matchesSearch && matchesFilter;
    });
  }, [invitations, invitationFilter, search]);

  function changeTab(tab: ActiveTab) {
    setActiveTab(tab);
    setSearch("");

    if (tab !== "invitations") {
      setInvitationFilter("all");
    }

    setError(null);
    setNotice(null);
  }

  async function handleInvite(email: string, roleId: string) {
    setDialogSubmitting(true);
    setError(null);
    setNotice(null);

    try {
      await teamApi.invite({
        email: email.trim().toLowerCase(),
        role_id: roleId,
      });

      setDialogOpen(false);
      setActiveTab("invitations");
      setSearch("");
      setInvitationFilter("all");
      setNotice(`Invitation sent to ${email.trim()}.`);

      await loadTeam(true);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setDialogSubmitting(false);
    }
  }

  async function handleRoleChange(
    member: TeamMember,
    roleId: string,
  ) {
    if (!roleId || member.roles[0]?.id === roleId) {
      return;
    }

    setBusyId(member.membership_id);
    setError(null);
    setNotice(null);

    try {
      await teamApi.updateMemberRole(member.membership_id, roleId);

      setNotice(`Role updated for ${member.display_name}.`);
      await loadTeam(true);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  function handleRemove(member: TeamMember) {
    setRemovalTarget(member);
    setRemovalError(null);
  }

  async function handleConfirmRemoval(reason: string) {
    const member = removalTarget;
    if (!member) return;

    setRemovalSubmitting(true);
    setRemovalError(null);
    setError(null);
    setBusyId(member.membership_id);
    setNotice(removalPendingMessage(member.display_name));

    try {
      const result = await teamApi.removeMember(member.membership_id, reason);

      setNotice(removalSuccessMessage(member.display_name, result));
      setRemovalTarget(null);
      await loadTeam(true);
    } catch (cause) {
      setNotice(null);
      setRemovalError(removalErrorMessage(member.display_name, cause));
    } finally {
      setRemovalSubmitting(false);
      setBusyId(null);
    }
  }

  async function handleResend(invitation: TeamInvitation) {
    setBusyId(invitation.id);
    setError(null);
    setNotice(null);

    try {
      await teamApi.resendInvitation(invitation.id);

      setNotice(
        `A new invitation email was queued for ${invitation.email}.`,
      );
      await loadTeam(true);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  async function handleRevoke(invitation: TeamInvitation) {
    if (
      !window.confirm(
        `Revoke the invitation for ${invitation.email}?`,
      )
    ) {
      return;
    }

    setBusyId(invitation.id);
    setError(null);
    setNotice(null);

    try {
      await teamApi.revokeInvitation(invitation.id);

      setNotice(`Invitation for ${invitation.email} was revoked.`);
      await loadTeam(true);
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main className="team-access">
      <header className="team-access__header">
        <div>
          <span className="team-access__eyebrow">
            WORKSPACE SETTINGS
          </span>
          <h1>Team &amp; access</h1>
          <p>
            Manage your workspace members, invitations, and roles.
          </p>
        </div>

        <div className="team-access__header-actions">
          <button
            type="button"
            className="ta-button ta-button--secondary"
            onClick={() => void loadTeam(true)}
            disabled={loading || refreshing}
          >
            <RefreshCw
              size={16}
              className={refreshing ? "ta-spin" : ""}
            />
            Refresh
          </button>

          {activeTab !== "roles" && (
            <button
              type="button"
              className="ta-button ta-button--primary"
              onClick={() => {
                setError(null);
                setNotice(null);
                setDialogOpen(true);
              }}
              disabled={loading || roles.length === 0}
            >
              <UserPlus size={16} />
              Invite member
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="ta-alert ta-alert--error" role="alert">
          <AlertCircle size={18} />
          <span>{error}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setError(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}

      {notice && (
        <div
          className="ta-alert ta-alert--success"
          role="status"
          aria-live="polite"
        >
          <CheckCircle2 size={18} />
          <span>{notice}</span>
          <button
            type="button"
            aria-label="Dismiss message"
            onClick={() => setNotice(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}

      <section className="ta-summary" aria-label="Team overview">
        <article className="ta-summary__card">
          <span className="ta-summary__icon">
            <Users size={19} />
          </span>
          <span className="ta-summary__label">Active members</span>
          <strong>{loading ? "—" : members.length}</strong>
          <small>Current workspace access</small>
        </article>

        <article className="ta-summary__card">
          <span className="ta-summary__icon ta-summary__icon--amber">
            <Mail size={19} />
          </span>
          <span className="ta-summary__label">
            Pending invitations
          </span>
          <strong>{loading ? "—" : pendingCount}</strong>
          <small>Awaiting acceptance</small>
        </article>

        <article className="ta-summary__card">
          <span className="ta-summary__icon ta-summary__icon--green">
            <ShieldCheck size={19} />
          </span>
          <span className="ta-summary__label">Assignable roles</span>
          <strong>{loading ? "—" : roles.length}</strong>
          <small>Owner role excluded</small>
        </article>
      </section>

      <section className="ta-panel">
        <div className="ta-toolbar">
          <div
            className="ta-tabs"
            role="tablist"
            aria-label="Team sections"
          >
            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "members"}
              className={activeTab === "members" ? "is-active" : ""}
              onClick={() => changeTab("members")}
            >
              Members <span>{members.length}</span>
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "invitations"}
              className={
                activeTab === "invitations" ? "is-active" : ""
              }
              onClick={() => changeTab("invitations")}
            >
              Invitations <span>{invitations.length}</span>
            </button>

            <button
              type="button"
              role="tab"
              aria-selected={activeTab === "roles"}
              className={activeTab === "roles" ? "is-active" : ""}
              onClick={() => changeTab("roles")}
            >
              Roles <span>{roles.length}</span>
            </button>
          </div>

          {activeTab !== "roles" && (
            <div className="ta-toolbar__controls">
              <label className="ta-search">
                <span className="ta-sr-only">
                  {activeTab === "members"
                    ? "Search members"
                    : "Search invitations"}
                </span>
                <input
                  type="search"
                  placeholder={
                    activeTab === "members"
                      ? "Search members…"
                      : "Search invitations…"
                  }
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
                {search && (
                  <button
                    type="button"
                    aria-label="Clear search"
                    onClick={() => setSearch("")}
                  >
                    <X size={14} />
                  </button>
                )}
              </label>

              {activeTab === "invitations" && (
                <select
                  className="ta-select"
                  aria-label="Filter invitations"
                  value={invitationFilter}
                  onChange={(event) =>
                    setInvitationFilter(event.target.value)
                  }
                >
                  <option value="all">All statuses</option>
                  <option value="pending">Pending</option>
                  <option value="accepted">Accepted</option>
                  <option value="expired">Expired</option>
                  <option value="revoked">Revoked</option>
                </select>
              )}
            </div>
          )}
        </div>

        {loading ? (
          <div className="ta-state" role="status" aria-live="polite">
            <span className="ta-spinner" />
            <strong>Loading team data…</strong>
            <p>
              Fetching members, roles, and invitations. This will stop
              if a request fails or takes too long.
            </p>
          </div>
        ) : activeTab === "members" ? (
          <TeamMembersTable
            members={visibleMembers}
            totalCount={members.length}
            roles={roles}
            busyId={busyId}
            search={search}
            onRoleChange={handleRoleChange}
            onRemove={handleRemove}
            onClearSearch={() => setSearch("")}
          />
        ) : activeTab === "invitations" ? (
          <PendingInvitations
            invitations={visibleInvitations}
            totalCount={invitations.length}
            roles={roles}
            busyId={busyId}
            search={search}
            onResend={handleResend}
            onRevoke={handleRevoke}
            onInvite={() => {
              setError(null);
              setNotice(null);
              setDialogOpen(true);
            }}
            onClearSearch={() => {
              setSearch("");
              setInvitationFilter("all");
            }}
          />
        ) : (
          <OrganizationRolesPanel
            onChanged={async () => {
              await loadTeam(true);
            }}
          />
        )}
      </section>

      {activeTab !== "roles" && (
        <aside className="ta-security-note">
          <ShieldCheck size={18} />
          <p>
            <strong>Workspace access is protected.</strong> Permissions
            are enforced by the backend. The owner role cannot be assigned
            through this screen.
          </p>
        </aside>
      )}

      <RemoveMemberDialog
        open={removalTarget !== null}
        memberName={removalTarget?.display_name ?? ""}
        submitting={removalSubmitting}
        error={removalError}
        onClose={() => {
          if (!removalSubmitting) {
            setRemovalTarget(null);
          }
        }}
        onSubmit={handleConfirmRemoval}
      />

      <InviteMemberDialog
        open={dialogOpen}
        roles={roles}
        submitting={dialogSubmitting}
        onClose={() => {
          if (!dialogSubmitting) {
            setDialogOpen(false);
          }
        }}
        onSubmit={handleInvite}
      />
    </main>
  );
}
