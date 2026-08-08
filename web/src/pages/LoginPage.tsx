import * as React from "react";
import { ArrowRight, CheckCircle2, Eye, EyeOff, Lock, ShieldCheck, User } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { BrandMark } from "@/components/brand/BrandMark";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { BRAND_NAME, BRAND_SHORT_NAME, DEMO_CREDENTIALS } from "@/config/brand";
import { useAuthStore } from "@/stores/authStore";

export function LoginPage() {
  const navigate = useNavigate();
  const { login, register, isLoading } = useAuthStore();
  const [mode, setMode] = React.useState<"login" | "register">("login");
  const [showPassword, setShowPassword] = React.useState(false);
  const [remember, setRemember] = React.useState(true);
  const [form, setForm] = React.useState({ username: "", password: "", confirm: "" });
  const [error, setError] = React.useState<string | null>(null);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    if (!form.username.trim() || !form.password.trim()) {
      setError("请输入用户名和密码。");
      return;
    }
    if (mode === "register") {
      if (form.username.trim().length < 3) {
        setError("用户名至少 3 个字符。");
        return;
      }
      if (form.password.length < 8) {
        setError("密码至少 8 位。");
        return;
      }
      if (form.password !== form.confirm) {
        setError("两次输入的密码不一致。");
        return;
      }
      try {
        await register(form.username.trim(), form.password);
        navigate("/");
      } catch (err) {
        setError((err as Error).message || "注册失败，请稍后重试。");
      }
      return;
    }
    try {
      await login(form.username.trim(), form.password.trim(), remember);
      navigate("/");
    } catch (err) {
      setError((err as Error).message || "登录失败，请稍后重试。");
    }
  };

  const switchMode = (next: "login" | "register") => {
    setMode(next);
    setError(null);
    setForm({ username: "", password: "", confirm: "" });
  };

  const fillDemoCredentials = () => {
    setError(null);
    setShowPassword(false);
    setForm({
      username: DEMO_CREDENTIALS.username,
      password: DEMO_CREDENTIALS.password,
      confirm: ""
    });
  };

  return (
    <main className="min-h-[100dvh] bg-[var(--merchant-surface-subtle)] p-3 sm:p-6 lg:p-8">
      <div className="mx-auto grid min-h-[calc(100dvh-1.5rem)] w-full max-w-6xl overflow-hidden rounded-[var(--merchant-radius-lg)] border border-[var(--merchant-border)] bg-white shadow-[var(--merchant-shadow-lg)] sm:min-h-[calc(100dvh-3rem)] lg:grid-cols-[minmax(0,0.9fr)_minmax(420px,1.1fr)]">
        <section className="relative hidden overflow-hidden bg-[var(--merchant-navy)] px-10 py-12 text-white lg:flex lg:flex-col lg:justify-between">
          <div
            aria-hidden="true"
            className="absolute right-0 top-0 h-44 w-44 border-b border-l border-white/10"
          />
          <div>
            <div className="flex items-center gap-3">
              <BrandMark inverted />
              <div>
                <p className="text-base font-semibold tracking-wide">{BRAND_SHORT_NAME}</p>
                <p className="text-xs text-slate-300">Merchant Operations Intelligence</p>
              </div>
            </div>
            <p className="mt-20 text-xs font-semibold uppercase tracking-[0.24em] text-[var(--merchant-cyan)]">
              即时零售 AI 运营工作台
            </p>
            <h2 className="mt-5 max-w-md text-4xl font-semibold leading-[1.2] tracking-tight">
              让每一次运营决策，
              <span className="text-[var(--merchant-cyan)]">都有数据依据。</span>
            </h2>
            <p className="mt-5 max-w-md text-sm leading-7 text-slate-300">
              从真实购物篮发现搭配机会，连接 AI 客服、评测标注和优化任务，形成可验证的运营闭环。
            </p>
          </div>
          <ul className="space-y-3 text-sm text-slate-200">
            {["真实购物篮关联洞察", "Agent 评测与人工标注", "优化前后证据可追溯"].map((item) => (
              <li key={item} className="flex items-center gap-3">
                <CheckCircle2 className="h-4 w-4 text-[var(--merchant-cyan)]" />
                {item}
              </li>
            ))}
          </ul>
        </section>

        <section className="flex min-w-0 items-center justify-center px-5 py-8 sm:px-10 lg:px-16">
          <div className="w-full max-w-md">
            <div className="mb-8 flex items-center gap-3 lg:hidden">
              <BrandMark />
              <div>
                <p className="font-semibold text-[var(--merchant-navy)]">{BRAND_SHORT_NAME}</p>
                <p className="text-xs text-[var(--merchant-text-muted)]">商家运营智能工作台</p>
              </div>
            </div>

            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-[var(--merchant-cyan-strong)]">
              Secure merchant access
            </p>
            <h1 className="mt-3 text-3xl font-semibold tracking-tight text-[var(--merchant-navy)]">
              {BRAND_NAME}
            </h1>
            <p className="mt-3 text-sm leading-6 text-[var(--merchant-text-muted)]">
              登录后进入即时零售运营总览、AI 客服与效果优化工作区。
            </p>

            <button
              type="button"
              onClick={fillDemoCredentials}
              aria-label="填入演示账号"
              className="mt-7 flex w-full items-center justify-between rounded-[var(--merchant-radius-md)] border border-[var(--merchant-cyan-border)] bg-[var(--merchant-cyan-soft)] px-4 py-3 text-left text-sm transition-colors hover:border-[var(--merchant-cyan)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--merchant-focus)] focus-visible:ring-offset-2"
            >
              <span>
                <span className="block font-semibold text-[var(--merchant-navy)]">
                  使用商家演示环境
                </span>
                <span className="mt-0.5 block text-xs text-[var(--merchant-text-muted)]">
                  账号仅填入当前表单
                </span>
              </span>
              <span className="inline-flex items-center gap-1 font-semibold text-[var(--merchant-cyan-strong)]">
                填入演示账号
                <ArrowRight className="h-4 w-4" />
              </span>
            </button>

            <form className="mt-7 space-y-5" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <label
                  htmlFor="login-username"
                  className="text-sm font-medium text-[var(--merchant-text)]"
                >
                  用户名
                </label>
                <div className="relative">
                  <User className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--merchant-text-muted)]" />
                  <Input
                    id="login-username"
                    placeholder={
                      mode === "register" ? "设置用户名（至少 3 个字符）" : "请输入用户名"
                    }
                    value={form.username}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, username: event.target.value }))
                    }
                    className="h-12 rounded-[var(--merchant-radius-md)] pl-10"
                    autoComplete="username"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <label
                  htmlFor="login-password"
                  className="text-sm font-medium text-[var(--merchant-text)]"
                >
                  密码
                </label>
                <div className="relative">
                  <Lock className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--merchant-text-muted)]" />
                  <Input
                    id="login-password"
                    type={showPassword ? "text" : "password"}
                    placeholder={mode === "register" ? "设置密码（至少 8 位）" : "请输入密码"}
                    value={form.password}
                    onChange={(event) =>
                      setForm((prev) => ({ ...prev, password: event.target.value }))
                    }
                    className="h-12 rounded-[var(--merchant-radius-md)] pl-10 pr-11"
                    autoComplete={mode === "register" ? "new-password" : "current-password"}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((prev) => !prev)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-1 text-[var(--merchant-text-muted)] hover:text-[var(--merchant-navy)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--merchant-focus)]"
                    aria-label={showPassword ? "隐藏密码" : "显示密码"}
                  >
                    {showPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              {mode === "register" ? (
                <div className="space-y-2">
                  <label
                    htmlFor="login-confirm"
                    className="text-sm font-medium text-[var(--merchant-text)]"
                  >
                    确认密码
                  </label>
                  <div className="relative">
                    <Lock className="absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--merchant-text-muted)]" />
                    <Input
                      id="login-confirm"
                      type={showPassword ? "text" : "password"}
                      placeholder="再次输入密码"
                      value={form.confirm}
                      onChange={(event) =>
                        setForm((prev) => ({ ...prev, confirm: event.target.value }))
                      }
                      className="h-12 rounded-[var(--merchant-radius-md)] pl-10"
                      autoComplete="new-password"
                    />
                  </div>
                </div>
              ) : null}
              <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
                <label className="flex items-center gap-2 text-[var(--merchant-text-muted)]">
                  <Checkbox
                    checked={remember}
                    onCheckedChange={(value) => setRemember(Boolean(value))}
                  />
                  记住登录状态
                </label>
                <span className="inline-flex items-center gap-1 text-xs text-[var(--merchant-text-muted)]">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  账号仅用于本次登录
                </span>
              </div>
              {error ? (
                <p
                  role="alert"
                  className="rounded-[var(--merchant-radius-sm)] border border-orange-200 bg-orange-50 px-3 py-2 text-sm text-orange-800"
                >
                  {error}
                </p>
              ) : null}
              <Button
                type="submit"
                className="h-12 w-full rounded-[var(--merchant-radius-md)] bg-[var(--merchant-navy)] hover:bg-[#0d3b5d]"
                disabled={isLoading}
              >
                {isLoading ? (
                  <span className="inline-flex items-center gap-2">
                    <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white" />
                    {mode === "register" ? "正在创建账号..." : "正在验证并进入工作台..."}
                  </span>
                ) : mode === "register" ? (
                  "创建账号并登录"
                ) : (
                  "登录运营台"
                )}
              </Button>
              <p className="text-center text-sm text-[var(--merchant-text-muted)]">
                {mode === "register" ? (
                  <>
                    已有账号？{" "}
                    <button
                      type="button"
                      onClick={() => switchMode("login")}
                      className="font-semibold text-[var(--merchant-cyan-strong)] hover:underline"
                    >
                      返回登录
                    </button>
                  </>
                ) : (
                  <>
                    还没有账号？{" "}
                    <button
                      type="button"
                      onClick={() => switchMode("register")}
                      className="font-semibold text-[var(--merchant-cyan-strong)] hover:underline"
                    >
                      注册商家账号
                    </button>
                  </>
                )}
              </p>
            </form>
          </div>
        </section>
      </div>
    </main>
  );
}
