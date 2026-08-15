import axios from "axios";
import { toast } from "sonner";

import { storage } from "@/utils/storage";
import { ApiError } from "@/services/ApiError";

/**
 * Keep the REST and streaming clients on the same API root.  The SSE client
 * cannot use Axios' `baseURL`, so this is exported for consumers that build a
 * URL with `fetch` directly.
 */
export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "/api/v1").replace(/\/$/, "");

export const api = axios.create({ baseURL: API_BASE_URL, timeout: 60000 });

export function apiErrorMessage(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    const messages = value
      .map((item) => apiErrorMessage(item))
      .filter((item): item is string => Boolean(item));
    return messages.length > 0 ? messages.join("；") : undefined;
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const message = apiErrorMessage(record.message ?? record.msg ?? record.detail);
    if (!message) return undefined;
    const location = Array.isArray(record.loc)
      ? record.loc.filter((item) => typeof item === "string" || typeof item === "number").join(".")
      : "";
    return location ? `${location}: ${message}` : message;
  }
  return undefined;
}

export function setAuthToken(token: string | null) {
  if (token) api.defaults.headers.common.Authorization = `Bearer ${token}`;
  else delete api.defaults.headers.common.Authorization;
}

api.interceptors.request.use((config) => {
  const token = storage.getToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (response) => {
    const payload = response.data;
    if (payload && typeof payload === "object" && "success" in payload) {
      if (!payload.success) {
        return Promise.reject(
          new ApiError(payload.error?.message || "请求失败", {
            status: response.status,
            code: payload.error?.code,
            details: payload.error?.details,
            traceId: payload.traceId
          })
        );
      }
      return payload.data;
    }
    return payload;
  },
  (error) => {
    if (error?.response?.status === 401) {
      storage.clearAuth();
      if (window.location.pathname !== "/login") window.location.href = "/login";
    }
    const payload = error?.response?.data;
    const message = apiErrorMessage(payload?.error?.message ?? payload?.detail);
    if (message) toast.error(message);
    else if (error?.code === "ERR_NETWORK") toast.error("网络错误，请检查网络连接");
    return Promise.reject(
      new ApiError(message || error?.message || "网络错误", {
        status: error?.response?.status,
        code: payload?.error?.code,
        details: payload?.error?.details,
        traceId: payload?.traceId
      })
    );
  }
);
