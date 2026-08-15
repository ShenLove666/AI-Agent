import { api } from "@/services/api";

export interface RuntimeSettingItem {
  key: string;
  label: string;
  description: string;
  scope: "immediate" | "restart";
  valueType: "int" | "float" | "str" | "secret";
  /** secret 类型只返回是否已配置，永不返回明文 */
  configured: boolean;
  value: string | number | null;
  default: string | number | null;
  overridden: boolean;
  enum?: string[] | null;
}

export interface RuntimeSettingAudit {
  key: string;
  operation: "update" | "reset";
  oldValue: string | null;
  newValue: string | null;
  operatorName: string | null;
  scope: string;
  createdAt: string;
}

export interface SystemSettings {
  /** 全局配置版本号，PATCH 时用于并发冲突检测 */
  version: number;
  items: RuntimeSettingItem[];
  audits: RuntimeSettingAudit[];
}

export async function getSystemSettings(): Promise<SystemSettings> {
  return api.get<SystemSettings, SystemSettings>("/rag/settings");
}

/** Read a numeric runtime setting without inventing a second settings shape on the client. */
export function getNumericRuntimeSetting(
  settings: SystemSettings,
  key: string,
  fallback: number
): number {
  const item = settings.items.find((candidate) => candidate.key === key);
  const value = typeof item?.value === "number" ? item.value : Number(item?.value);
  return Number.isFinite(value) ? value : fallback;
}

export async function patchSystemSettings(
  expectedVersion: number,
  changes: Array<{ key: string; value: string | number }>,
  resetKeys: string[]
): Promise<{ version: number }> {
  return api.patch<unknown, { version: number }>("/rag/settings", {
    expectedVersion,
    changes,
    resetKeys
  });
}
