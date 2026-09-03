import { apiFetch } from "./client";

export type Role = "owner" | "recruiter" | "hiring_manager";

export type Organization = { id: string; name: string; retention_days: number };

export type Me = {
  id: string;
  email: string;
  full_name: string | null;
  role: Role;
  vacancy_scope: string[] | null;
  organization: Organization;
  permissions: string[];
};

export type Member = {
  id: string;
  user_id: string;
  email: string;
  full_name: string | null;
  role: Role;
  is_active: boolean;
  vacancy_scope: string[] | null;
  created_at: string;
  last_login_at: string | null;
};

export type InviteStatus = "active" | "expired" | "revoked" | "exhausted";

export type Invite = {
  id: string;
  role: Role;
  email: string | null;
  vacancy_scope: string[] | null;
  expires_at: string;
  max_uses: number | null;
  uses_count: number;
  revoked_at: string | null;
  created_at: string;
  status: InviteStatus;
  url: string | null;
};

export type InvitePreview = {
  organization_name: string;
  role: Role;
  email: string | null;
  valid: boolean;
  reason: string | null;
};

export type AuditEntry = {
  id: string;
  actor_user_id: string | null;
  actor_email: string | null;
  action: string;
  target_type: string;
  target_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
};

type TokenResponse = { access_token: string; token_type: string };

export const accountsApi = {
  register: (body: {
    email: string;
    password: string;
    full_name: string;
    organization_name?: string;
    invite_token?: string;
  }) => apiFetch<TokenResponse>("/auth/register", { method: "POST", body, token: null }),

  login: (body: { email: string; password: string }) =>
    apiFetch<TokenResponse>("/auth/login", { method: "POST", body, token: null }),

  me: () => apiFetch<Me>("/auth/me"),

  logoutAll: () => apiFetch<void>("/auth/logout-all", { method: "POST" }),

  changePassword: (body: { current_password: string; new_password: string }) =>
    apiFetch<TokenResponse>("/auth/change-password", { method: "POST", body }),

  previewInvite: (token: string) =>
    apiFetch<InvitePreview>(`/invites/${encodeURIComponent(token)}/preview`, { token: null }),

  acceptInvite: (token: string) =>
    apiFetch<Me>("/invites/accept", { method: "POST", body: { token } }),

  organization: () => apiFetch<Organization>("/organization"),

  updateOrganization: (body: { name?: string; retention_days?: number }) =>
    apiFetch<Organization>("/organization", { method: "PATCH", body }),

  members: () => apiFetch<Member[]>("/organization/members"),

  updateMember: (id: string, body: { role?: Role; vacancy_scope?: string[] | null }) =>
    apiFetch<Member>(`/organization/members/${id}`, { method: "PATCH", body }),

  deactivateMember: (id: string) =>
    apiFetch<Member>(`/organization/members/${id}/deactivate`, { method: "POST" }),

  reactivateMember: (id: string) =>
    apiFetch<Member>(`/organization/members/${id}/reactivate`, { method: "POST" }),

  invites: () => apiFetch<Invite[]>("/organization/invites"),

  createInvite: (body: {
    role: Role;
    email?: string;
    expires_in_days?: number;
    max_uses?: number | null;
    vacancy_scope?: string[] | null;
  }) => apiFetch<Invite>("/organization/invites", { method: "POST", body }),

  revokeInvite: (id: string) =>
    apiFetch<Invite>(`/organization/invites/${id}`, { method: "DELETE" }),

  audit: () => apiFetch<AuditEntry[]>("/organization/audit"),
};
