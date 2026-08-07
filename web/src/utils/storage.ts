import type { User } from "@/types";

const TOKEN_KEY = "ragent_token";
const USER_KEY = "ragent_user";
const THEME_KEY = "ragent_theme";

function safeGet(key: string, target: Storage = window.localStorage) {
  try {
    return target.getItem(key);
  } catch {
    return null;
  }
}

function safeSet(key: string, value: string, target: Storage = window.localStorage) {
  try {
    target.setItem(key, value);
  } catch {
    return;
  }
}

function safeRemove(key: string, target: Storage = window.localStorage) {
  try {
    target.removeItem(key);
  } catch {
    return;
  }
}

export const storage = {
  getToken(): string | null {
    return safeGet(TOKEN_KEY) ?? safeGet(TOKEN_KEY, window.sessionStorage);
  },
  setToken(token: string, persistent = true) {
    const target = persistent ? window.localStorage : window.sessionStorage;
    const other = persistent ? window.sessionStorage : window.localStorage;
    safeRemove(TOKEN_KEY, other);
    safeSet(TOKEN_KEY, token, target);
  },
  clearToken() {
    safeRemove(TOKEN_KEY);
    safeRemove(TOKEN_KEY, window.sessionStorage);
  },
  getUser(): User | null {
    const raw = safeGet(USER_KEY) ?? safeGet(USER_KEY, window.sessionStorage);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as User;
    } catch {
      return null;
    }
  },
  setUser(user: User, persistent = Boolean(safeGet(TOKEN_KEY))) {
    const target = persistent ? window.localStorage : window.sessionStorage;
    const other = persistent ? window.sessionStorage : window.localStorage;
    safeRemove(USER_KEY, other);
    safeSet(USER_KEY, JSON.stringify(user), target);
  },
  clearUser() {
    safeRemove(USER_KEY);
    safeRemove(USER_KEY, window.sessionStorage);
  },
  clearAuth() {
    safeRemove(TOKEN_KEY);
    safeRemove(USER_KEY);
    safeRemove(TOKEN_KEY, window.sessionStorage);
    safeRemove(USER_KEY, window.sessionStorage);
  },
  getTheme(): string | null {
    return safeGet(THEME_KEY);
  },
  setTheme(theme: string) {
    safeSet(THEME_KEY, theme);
  }
};
