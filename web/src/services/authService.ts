import { api } from "@/services/api";
import type { CurrentUser, User } from "@/types";

interface PythonToken {
  access_token: string;
  user_id: number;
  username: string;
  role: string;
}

export interface LoginResponse extends User {}
export interface CurrentUserResponse extends CurrentUser {}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const data = await api.post<unknown, PythonToken>("/auth/login", { username, password });
  return {
    userId: String(data.user_id),
    username: data.username,
    role: data.role,
    token: data.access_token
  };
}

export async function logout() {
  return Promise.resolve();
}

export async function getCurrentUser(): Promise<CurrentUserResponse> {
  return api.get<CurrentUserResponse, CurrentUserResponse>("/auth/me");
}
