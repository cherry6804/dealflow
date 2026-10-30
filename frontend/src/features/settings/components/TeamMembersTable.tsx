
import { Users } from "lucide-react";

import type { TeamMember, TeamRole } from "../../../services/teamApi";
import TeamMemberActions from "./TeamMemberActions";

interface TeamMembersTableProps {
  members: TeamMember[];
  totalCount: number;
  roles: TeamRole[];
  busyId: string | null;
  search: string;
  onRoleChange: (member: TeamMember, roleId: string) => void;
  onRemove: (member: TeamMember) => void;
  onClearSearch: () => void;
}

function formatDate(value: string): string {
  const date = new Date(value);

  if (Number.isNaN(date.getTime())) return "—";

  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function initials(name: string, email: string): string {
  const source = name.trim() || email.trim() || "U";
  const parts = source.split(/\s+/).filter(Boolean);

  return parts.length > 1
    ? `${parts[0][0]}${parts[1][0]}`.toUpperCase()
    : source.slice(0, 2).toUpperCase();
}

export default function TeamMembersTable({
  members,
  totalCount,
  roles,
  busyId,
  search,
  onRoleChange,
  onRemove,
  onClearSearch,
}: TeamMembersTableProps) {
  return (
    <div className="ta-grid-container">
      <div className="ta-grid-scroll">
        <table className="ta-grid">
          <thead>
            <tr>
              <th scope="col">Member</th>
              <th scope="col">Assigned role</th>
              <th scope="col">Joined</th>
              <th scope="col" className="ta-grid__actions-heading">Actions</th>
            </tr>
          </thead>

          <tbody>
            {members.map((member) => (
              <tr key={member.membership_id}>
                <td>
                  <div className="ta-person">
                    <span className="ta-avatar" aria-hidden="true">
                      {initials(member.display_name, member.email)}
                    </span>
                    <span className="ta-person__text">
                      <strong>{member.display_name || "Unnamed member"}</strong>
                      <small>{member.email}</small>
                    </span>
                  </div>
                </td>

                <td>
                  {member.roles.length > 0 ? (
                    <div className="ta-role-list">
                      {member.roles.map((role) => (
                        <span className="ta-role-pill" key={role.id}>
                          {role.name}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <span className="ta-muted">No assigned role</span>
                  )}
                </td>

                <td>
                  <span className="ta-date">{formatDate(member.joined_at)}</span>
                </td>

                <td className="ta-grid__actions">
                  <TeamMemberActions
                    member={member}
                    roles={roles}
                    busy={busyId === member.membership_id}
                    onRoleChange={onRoleChange}
                    onRemove={onRemove}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {members.length === 0 && (
        <div className="ta-empty">
          <span className="ta-empty__icon"><Users size={23} /></span>
          <strong>{search ? "No matching members" : "No team members found"}</strong>
          <p>
            {search
              ? "Try another name, email address, or role."
              : "Active members of this workspace will appear here."}
          </p>
          {search && (
            <button type="button" className="ta-text-button" onClick={onClearSearch}>
              Clear search
            </button>
          )}
        </div>
      )}

      <footer className="ta-grid-footer">
        <span>
          Showing <strong>{members.length}</strong> of <strong>{totalCount}</strong> members
        </span>
        <span>Workspace members only</span>
      </footer>
    </div>
  );
}
