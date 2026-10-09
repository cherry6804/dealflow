import { api } from "../lib/api";

export interface AuthenticatedUser {
  id: string;
  email: string;
  display_name: string;
}

export interface LoginResponse {
  user: AuthenticatedUser;
}

export interface LoginInput {
  email: string;
  password: string;
}

export const authApi = {
  login(input: LoginInput): Promise<LoginResponse> {
    return api.post<LoginResponse>("/auth/login", input);
  },

  getCurrentUser(): Promise<LoginResponse> {
    return api.get<LoginResponse>("/auth/me");
  },

  logout(): Promise<void> {
    return api.post<void>("/auth/logout");
  },
};