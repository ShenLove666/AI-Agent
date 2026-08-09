import { useCallback, useEffect, useMemo, useState } from "react";
import { RotateCcw, Save, Undo2 } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { useAuthStore } from "@/stores/authStore";
import type { RuntimeSettingItem, SystemSettings } from "@/services/settingsService";
import { getSystemSettings, patchSystemSettings } from "@/services/settingsService";
import { getErrorMessage } from "@/utils/error";

export function SystemSettingsPage() {
  const permissions = useAuthStore((state) => state.user?.permissions ?? []);
  const canWrite = permissions.includes("settings.write");
  const [settings, setSettings] = useState<SystemSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [resetting, setResetting] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);

  const loadSettings = useCallback(async () => {
    try {
      setLoading(true);
      const data = await getSystemSettings();
      setSettings(data);
      const initial: Record<string, string> = {};
      for (const item of data.items) {
        if (item.valueType !== "secret") {
          initial[item.key] = String(item.value ?? "");
        }
      }
      setDraft(initial);
      setResetting(new Set());
    } catch (error) {
      toast.error(getErrorMessage(error, "加载系统配置失败"));
      console.error(error);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  const dirtyKeys = useMemo(() => {
    if (!settings) return new Set<string>();
    return new Set(
      settings.items
        .filter((item) => item.valueType !== "secret")
        .filter((item) => draft[item.key] !== String(item.value ?? ""))
        .map((item) => item.key)
    );
  }, [settings, draft]);

  const updateDraft = (key: string, value: string) =>
    setDraft((previous) => ({ ...previous, [key]: value }));

  const toggleReset = (key: string) =>
    setResetting((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const save = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      const changes = settings.items
        .filter((item) => item.valueType === "secret" || dirtyKeys.has(item.key))
        .filter((item) => {
          if (item.valueType === "secret") return draft[item.key] !== undefined && draft[item.key] !== "";
          return true;
        })
        .map((item) => ({ key: item.key, value: draft[item.key] ?? "" }));
      const resetKeys = settings.items
        .filter((item) => resetting.has(item.key))
        .map((item) => item.key);
      if (changes.length === 0 && resetKeys.length === 0) {
        toast.info("没有需要保存的修改");
        return;
      }
      const result = await patchSystemSettings(settings.version, changes, resetKeys);
      toast.success(`配置已保存（版本 v${result.version}）`);
      await loadSettings();
    } catch (error) {
      const message = getErrorMessage(error, "保存失败");
      if (message.includes("已被其他操作修改")) {
        toast.error(`${message}，正在刷新最新配置…`);
        await loadSettings();
      } else {
        toast.error(message);
      }
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="admin-page">
        <div className="text-sm text-muted-foreground">加载中...</div>
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="admin-page">
        <div className="text-sm text-muted-foreground">暂无可展示的配置</div>
      </div>
    );
  }

  const immediateItems = settings.items.filter((item) => item.scope === "immediate");
  const restartItems = settings.items.filter((item) => item.scope === "restart");

  const renderItem = (item: RuntimeSettingItem) => {
    const isSecret = item.valueType === "secret";
    const value = isSecret ? "" : draft[item.key] ?? "";
    const original = isSecret ? (item.configured ? "已配置" : "未配置") : String(item.value ?? "");
    const dirty = isSecret ? value !== "" : value !== original;
    return (
      <TableRow key={item.key} className={dirty ? "bg-amber-50/60" : undefined}>
        <TableCell className="align-top">
          <div className="font-medium text-slate-800">{item.label}</div>
          <div className="mt-0.5 max-w-[420px] text-xs leading-5 text-slate-500">
            {item.description}
          </div>
          <div className="mt-1 flex items-center gap-2">
            <code className="text-[11px] text-slate-400">{item.key}</code>
            {item.overridden && (
              <Badge variant="outline" className="text-[10px] text-amber-700">
                已修改
              </Badge>
            )}
          </div>
        </TableCell>
        <TableCell>
          <div className="flex items-center gap-2">
            {isSecret ? (
              <Input
                type="password"
                placeholder={item.configured ? "已配置（输入新值以替换）" : "未配置（输入密钥）"}
                value={value}
                onChange={(event) => updateDraft(item.key, event.target.value)}
                disabled={!canWrite}
                className="w-64"
              />
            ) : (
              <Input
                value={value}
                onChange={(event) => updateDraft(item.key, event.target.value)}
                disabled={!canWrite}
                className="w-36"
              />
            )}
            {!isSecret && (
              <Button
                size="sm"
                variant="outline"
                disabled={!canWrite || !item.overridden || resetting.has(item.key)}
                onClick={() => toggleReset(item.key)}
                title="恢复默认"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>
        </TableCell>
        <TableCell className="align-top">
          <div className="text-xs text-slate-400">
            {isSecret
              ? item.configured
                ? "已配置（不回显明文）"
                : "未配置"
              : `默认 ${String(item.default ?? "")}`}
          </div>
          {resetting.has(item.key) && (
            <div className="mt-1 rounded bg-amber-100 px-2 py-1 text-[11px] text-amber-800">
              将恢复默认
            </div>
          )}
        </TableCell>
        <TableCell className="align-top text-xs text-slate-500">
          {dirty ? (
            <div className="rounded bg-amber-50 px-2 py-1">
              修改前：<span className="text-slate-400">{original}</span>
              <br />
              修改后：<span className="font-medium text-amber-800">{value || "（留空）"}</span>
            </div>
          ) : (
            <span className="text-slate-300">-</span>
          )}
        </TableCell>
      </TableRow>
    );
  };

  return (
    <div className="admin-page">
      <div className="admin-page-header">
        <div>
          <h1 className="admin-page-title">系统配置</h1>
          <p className="admin-page-subtitle">
            运行时配置 · 当前版本 v{settings.version}
            {canWrite ? " · 可编辑" : " · 只读（需要 settings.write 权限）"}
          </p>
        </div>
        {canWrite && (
          <div className="flex gap-2">
            <Button variant="outline" disabled={saving} onClick={() => void loadSettings()}>
              <Undo2 className="mr-2 h-4 w-4" />
              撤销修改
            </Button>
            <Button onClick={() => void save()} disabled={saving}>
              <Save className="mr-2 h-4 w-4" />
              保存配置
            </Button>
          </div>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>立即生效参数</CardTitle>
          <CardDescription>保存后无需重启，下一次对话/检索立即使用新值</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[320px]">配置项</TableHead>
                <TableHead className="w-[220px]">当前值</TableHead>
                <TableHead className="w-[160px]">默认值</TableHead>
                <TableHead>修改对比</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>{immediateItems.map(renderItem)}</TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>需重启生效参数</CardTitle>
          <CardDescription>
            保存后写入配置库，服务重启时自动合并生效；API Key 仅显示是否已配置，不回显明文
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[320px]">配置项</TableHead>
                <TableHead className="w-[220px]">当前值</TableHead>
                <TableHead className="w-[160px]">默认值</TableHead>
                <TableHead>修改对比</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>{restartItems.map(renderItem)}</TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>配置审计</CardTitle>
          <CardDescription>最近 20 条修改记录：操作者、时间、旧值、新值</CardDescription>
        </CardHeader>
        <CardContent>
          {settings.audits.length === 0 ? (
            <div className="py-6 text-center text-sm text-slate-400">暂无修改记录</div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>配置项</TableHead>
                  <TableHead>操作</TableHead>
                  <TableHead>操作者</TableHead>
                  <TableHead>旧值 → 新值</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {settings.audits.map((audit) => (
                  <TableRow key={`${audit.createdAt}-${audit.key}-${audit.operation}`}>
                    <TableCell className="whitespace-nowrap text-xs text-slate-500">
                      {audit.createdAt.replace("T", " ").slice(0, 19)}
                    </TableCell>
                    <TableCell className="text-xs font-medium text-slate-700">{audit.key}</TableCell>
                    <TableCell>
                      <Badge variant={audit.operation === "reset" ? "outline" : "default"}>
                        {audit.operation === "reset" ? "恢复默认" : "更新"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs text-slate-500">{audit.operatorName ?? "-"}</TableCell>
                    <TableCell className="max-w-[360px] truncate text-xs text-slate-500">
                      {audit.operation === "reset"
                        ? `${audit.oldValue ?? "默认"} → 默认`
                        : `${audit.oldValue ?? "默认"} → ${audit.newValue ?? ""}`}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <aside className="rounded-2xl border border-slate-200 bg-slate-50 px-5 py-4 text-xs leading-6 text-slate-600">
        <strong>说明：</strong>所有修改会记录操作者、时间、旧值与新值；保存时携带版本号，若其他
        操作已修改配置会提示冲突并刷新，避免相互覆盖。API Key 保存后不再回显明文，仅显示已配置。
      </aside>
    </div>
  );
}
