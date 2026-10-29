
import { api } from "../lib/api";

export interface AuthenticatedUser {
  id: string;
  email: string;
  display_name: string;
}

export interface LoginResponse {
  user: AuthenticatedUser;
}

export interface VerifyEmailInput {
  token: string;
}

export interface MessageResponse {
  message: string;
}

export interface ResendVerificationInput {
  email: string;
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
  verifyEmail(input: VerifyEmailInput): Promise<MessageResponse> {
    return api.post<MessageResponse>("/auth/verify-email", input);
  },

  resendVerification(
    input: ResendVerificationInput,
  ): Promise<MessageResponse> {
    return api.post<MessageResponse>("/auth/resend-verification", input);
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
