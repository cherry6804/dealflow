
import { UserMinus } from "lucide-react";

import type { TeamMember, TeamRole } from "../../../services/teamApi";

interface TeamMemberActionsProps {
  member: TeamMember;
  roles: TeamRole[];
  busy: boolean;
  onRoleChange: (member: TeamMember, roleId: string) => void;
  onRemove: (member: TeamMember) => void;
}

export default function TeamMemberActions({
  member,
  roles,
  busy,
  onRoleChange,
  onRemove,
}: TeamMemberActionsProps) {
  const selectedRoleId = member.roles[0]?.id ?? "";

  return (
    <div className="ta-member-actions">
      <label className="ta-sr-only" htmlFor={`member-role-${member.membership_id}`}>
        Change role for {member.display_name || member.email}
      </label>

      <select
        id={`member-role-${member.membership_id}`}
        className="ta-select ta-select--role"
        value={selectedRoleId}
        disabled={busy || roles.length === 0}
        onChange={(event) => onRoleChange(member, event.target.value)}
        aria-label={`Role for ${member.display_name || member.email}`}
      >
        <option value="" disabled>
          Select role
        </option>
        {roles.map((role) => (
          <option value={role.id} key={role.id}>
            {role.name}
          </option>
        ))}
      </select>

      <button
        type="button"
        className="ta-icon-button ta-icon-button--danger"
        disabled={busy}
        aria-label={`Remove ${member.display_name || member.email} from workspace`}
        title="Remove member"
        onClick={() => onRemove(member)}
      >
        <UserMinus size={16} />
      </button>

      {busy && (
        <span className="ta-sr-only" role="status">
          Updating member…
        </span>
      )}
    </div>
  );
}
