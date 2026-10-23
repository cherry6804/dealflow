
import { api } from "../lib/api";

export interface AuthenticatedUser {
  id: string;
  email: string;
  display_name: string;
}

export interface Organization {
  id: string;
  name: string;
}

export interface LoginResponse {
  user: AuthenticatedUser;
}

export interface SignupInput {
  display_name: string;
  email: string;
  organization_name: string;
  password: string;
}

export interface SignupResponse {
  user: AuthenticatedUser;
  organization: Organization;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface PasswordResetRequest {
  email: string;
}

export interface PasswordResetConfirmRequest {
  token: string;
  new_password: string;
}

export interface PasswordResetResponse {
  message: string;
}

export const authApi = {
  signup(input: SignupInput): Promise<SignupResponse> {
    return api.post<SignupResponse>("/auth/signup", input);
  },

  login(input: LoginInput): Promise<LoginResponse> {
    return api.post<LoginResponse>("/auth/login", input);
  },

  getCurrentUser(): Promise<LoginResponse> {
    return api.get<LoginResponse>("/auth/me");
  },

  logout(): Promise<void> {
    return api.post<void>("/auth/logout");
  },

  requestPasswordReset(
    input: PasswordResetRequest,
  ): Promise<PasswordResetResponse> {
    return api.post<PasswordResetResponse>(
      "/auth/password-reset/request",
      input,
    );
  },

  confirmPasswordReset(
    input: PasswordResetConfirmRequest,
  ): Promise<PasswordResetResponse> {
    return api.post<PasswordResetResponse>(
      "/auth/password-reset/confirm",
      input,
    );
  },
};
