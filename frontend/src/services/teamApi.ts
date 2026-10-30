
import { api } from "../lib/api";

export interface TeamRole {
  id: string;
  name: string;
  organization_id?: string | null;
  description: string | null;
  is_system?: boolean;
  is_active?: boolean;
  permission_keys?: string[];
}

export interface PermissionCatalogueItem {
  key: string;
  description: string;
  group: string;
  assignable: boolean;
}

export interface TeamMember {
  user_id: string;
  display_name: string;
  email: string;
  membership_id: string;
  roles: TeamRole[];
  joined_at: string;
}

export interface TeamInvitation {
  id: string;
  organization_id: string;
  email: string;
  role_id: string;
  status: "pending" | "accepted" | "revoked" | "expired" | string;
  invited_by_user_id: string;
  accepted_by_user_id: string | null;
  created_at: string;
  expires_at: string;
  accepted_at: string | null;
  revoked_at: string | null;
}

export interface InviteTeamMemberInput {
  email: string;
  role_id: string;
}

export interface AcceptInvitationInput {
  token: string;
}

export interface AcceptInvitationResponse {
  organization_id: string;
  membership_id: string;
  message: string;
}

export interface TeamRoleCreateInput {
  name: string;
  description: string | null;
  permission_keys: string[];
}

export interface TeamRoleUpdateInput {
  name?: string;
  description?: string | null;
  permission_keys?: string[];
}

/** SIBVO's answer about the member's Dealsflo seat. Only confirmed outcomes are reported. */
export type RemovalSeatOutcome =
  | "released"
  | "already_released"
  | "not_held"
  | "not_linked";

export interface TeamMemberRemovalResponse {
  membership_id: string;
  is_active: boolean;
  seat_outcome: RemovalSeatOutcome;
  already_removed: boolean;
  message: string;
}

export const teamApi = {
  listMembers(): Promise<TeamMember[]> {
    return api.get<TeamMember[]>("/team/members");
  },

  listRoles(): Promise<TeamRole[]> {
    return api.get<TeamRole[]>("/team/roles");
  },

  listManageableRoles(): Promise<TeamRole[]> {
    return api.get<TeamRole[]>("/team/roles/manage");
  },

  listPermissions(): Promise<PermissionCatalogueItem[]> {
    return api.get<PermissionCatalogueItem[]>("/team/permissions");
  },

  createRole(input: TeamRoleCreateInput): Promise<TeamRole> {
    return api.post<TeamRole>("/team/roles", input);
  },

  updateRole(
    roleId: string,
    input: TeamRoleUpdateInput,
  ): Promise<TeamRole> {
    return api.put<TeamRole>(`/team/roles/${roleId}`, input);
  },

  deactivateRole(roleId: string): Promise<TeamRole> {
    return api.post<TeamRole>(`/team/roles/${roleId}/deactivate`);
  },

  listInvitations(): Promise<TeamInvitation[]> {
    return api.get<TeamInvitation[]>("/team/invitations");
  },

  invite(input: InviteTeamMemberInput): Promise<TeamInvitation> {
    return api.post<TeamInvitation>("/team/invitations", input);
  },

  resendInvitation(invitationId: string): Promise<TeamInvitation> {
    return api.post<TeamInvitation>(
      `/team/invitations/${invitationId}/resend`,
    );
  },

  revokeInvitation(invitationId: string): Promise<TeamInvitation> {
    return api.post<TeamInvitation>(
      `/team/invitations/${invitationId}/revoke`,
    );
  },

  updateMemberRole(
    membershipId: string,
    roleId: string,
  ): Promise<TeamMember> {
    return api.put<TeamMember>(
      `/team/members/${membershipId}/role`,
      { role_id: roleId },
    );
  },

  removeMember(
    membershipId: string,
    reason = "",
  ): Promise<TeamMemberRemovalResponse> {
    return api.post<TeamMemberRemovalResponse>(
      `/team/members/${membershipId}/remove`,
      { reason },
    );
  },

  acceptInvitation(
    input: AcceptInvitationInput,
  ): Promise<AcceptInvitationResponse> {
    return api.post<AcceptInvitationResponse>(
      "/team/invitations/accept",
      input,
    );
  },
};
