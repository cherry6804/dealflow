
import { Clock3, Mail, RefreshCw, UserPlus, X } from "lucide-react";

import type { TeamInvitation, TeamRole } from "../../../services/teamApi";

interface PendingInvitationsProps {
  invitations: TeamInvitation[];
  totalCount: number;
  roles: TeamRole[];
  busyId: string | null;
  search: string;
  onResend: (invitation: TeamInvitation) => void;
  onRevoke: (invitation: TeamInvitation) => void;
  onInvite: () => void;
  onClearSearch: () => void;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "—";

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function isPending(invitation: TeamInvitation): boolean {
  return (
    invitation.status.toLowerCase() === "pending" &&
    new Date(invitation.expires_at).getTime() > Date.now()
  );
}

function getStatus(invitation: TeamInvitation): string {
  if (invitation.status.toLowerCase() === "pending" && !isPending(invitation)) {
    return "Expired";
  }

  return invitation.status.charAt(0).toUpperCase() + invitation.status.slice(1);
}

function statusClass(status: string): string {
  const normalized = status.toLowerCase();

  if (normalized === "accepted") return "ta-status--accepted";
  if (normalized === "pending") return "ta-status--pending";

  return "ta-status--inactive";
}

export default function PendingInvitations({
  invitations,
  totalCount,
  roles,
  busyId,
  search,
  onResend,
  onRevoke,
  onInvite,
  onClearSearch,
}: PendingInvitationsProps) {
  const roleName = (roleId: string) =>
    roles.find((role) => role.id === roleId)?.name ?? "Role unavailable";

  return (
    <div className="ta-grid-container">
      <div className="ta-grid-scroll">
        <table className="ta-grid ta-grid--invitations">
          <thead>
            <tr>
              <th scope="col">Invitee</th>
              <th scope="col">Role</th>
              <th scope="col">Status</th>
              <th scope="col">Expires</th>
              <th scope="col" className="ta-grid__actions-heading">Actions</th>
            </tr>
          </thead>

          <tbody>
            {invitations.map((invitation) => {
              const pending = isPending(invitation);
              const status = getStatus(invitation);
              const busy = busyId === invitation.id;

              return (
                <tr key={invitation.id}>
                  <td>
                    <div className="ta-person">
                      <span className="ta-avatar ta-avatar--invite" aria-hidden="true">
                        <Mail size={16} />
                      </span>
                      <span className="ta-person__text">
                        <strong>{invitation.email}</strong>
                        <small>Invited {formatDate(invitation.created_at)}</small>
                      </span>
                    </div>
                  </td>

                  <td>
                    <span className="ta-role-pill">{roleName(invitation.role_id)}</span>
                  </td>

                  <td>
                    <span className={`ta-status ${statusClass(status)}`}>
                      <span aria-hidden="true" />
                      {status}
                    </span>
                  </td>

                  <td>
                    <span className="ta-date">
                      <Clock3 size={14} />
                      {formatDate(invitation.expires_at)}
                    </span>
                  </td>

                  <td className="ta-grid__actions">
                    {pending && (
                      <div className="ta-inline-actions">
                        <button
                          type="button"
                          className="ta-icon-button"
                          aria-label={`Resend invitation to ${invitation.email}`}
                          title="Resend invitation"
                          disabled={busy}
                          onClick={() => onResend(invitation)}
                        >
                          <RefreshCw size={15} />
                        </button>
                        <button
                          type="button"
                          className="ta-icon-button ta-icon-button--danger"
                          aria-label={`Revoke invitation for ${invitation.email}`}
                          title="Revoke invitation"
                          disabled={busy}
                          onClick={() => onRevoke(invitation)}
                        >
                          <X size={16} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {invitations.length === 0 && (
        <div className="ta-empty">
          <span className="ta-empty__icon"><Mail size={23} /></span>
          <strong>{search ? "No matching invitations" : "No invitations found"}</strong>
          <p>
            {search
              ? "Try another email address or change the status filter."
              : "Invite a teammate to give them access to this workspace."}
          </p>
          {search ? (
            <button type="button" className="ta-text-button" onClick={onClearSearch}>
              Clear filters
            </button>
          ) : (
            <button type="button" className="ta-button ta-button--primary" onClick={onInvite}>
              <UserPlus size={15} /> Invite member
            </button>
          )}
        </div>
      )}

      <footer className="ta-grid-footer">
        <span>
          Showing <strong>{invitations.length}</strong> of <strong>{totalCount}</strong> invitations
        </span>
        <span>Invitation links expire after seven days</span>
      </footer>
    </div>
  );
}
