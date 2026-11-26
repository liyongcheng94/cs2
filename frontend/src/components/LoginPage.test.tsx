// 账号体系前端场景（Phase 2 多用户）：
// Given 未登录 When 渲染 LoginPage Then 显示用户名/密码输入与登录/注册切换
// Given 输入用户名密码点「登录」When /auth/login 200 Then 调 onSuccess
// Given 登录失败（401 凭证错误）When 接口 401 Then 显示错误提示且不调 onSuccess
// Given 切到注册模式 When 填写并提交 Then 调 /auth/register
// Given 任意 API 返回 401 When apiGet 抛错 Then window 派发 cs2hq:unauthorized 事件
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (q: string) => ({
      matches: false,
      media: q,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
});

import { LoginPage } from "./LoginPage";
import { apiGet } from "../api/client";

describe("LoginPage", () => {
  it("渲染用户名/密码表单", () => {
    render(<LoginPage onSuccess={() => {}} />);
    expect(screen.getByPlaceholderText("用户名")).toBeTruthy();
    expect(screen.getByPlaceholderText("密码")).toBeTruthy();
  });

  it("登录成功调 onSuccess", async () => {
    const ok = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ username: "u", is_admin: true }) }),
    );
    render(<LoginPage onSuccess={ok} />);
    await userEvent.type(screen.getByPlaceholderText("用户名"), "will");
    await userEvent.type(screen.getByPlaceholderText("密码"), "pw123456");
    await userEvent.click(screen.getByRole("button", { name: /登 录|登录/ }));
    await waitFor(() => expect(ok).toHaveBeenCalled());
  });

  it("登录失败显示错误且不调 onSuccess", async () => {
    const ok = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: "用户名或密码错误" }) }),
    );
    render(<LoginPage onSuccess={ok} />);
    await userEvent.type(screen.getByPlaceholderText("用户名"), "will");
    await userEvent.type(screen.getByPlaceholderText("密码"), "bad");
    await userEvent.click(screen.getByRole("button", { name: /登 录|登录/ }));
    await waitFor(() => expect(screen.getByText(/用户名或密码错误/)).toBeTruthy());
    expect(ok).not.toHaveBeenCalled();
  });

  it("注册模式调 /auth/register", async () => {
    const ok = vi.fn();
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        calls.push(`${init?.method} ${_url}`);
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ username: "new", is_admin: false }) });
      }),
    );
    render(<LoginPage onSuccess={ok} />);
    await userEvent.click(screen.getByText("注册新账号"));
    await userEvent.type(screen.getByPlaceholderText("用户名"), "new");
    await userEvent.type(screen.getByPlaceholderText("密码"), "pw123456");
    await userEvent.click(screen.getByRole("button", { name: /注 册|注册/ }));
    await waitFor(() => expect(ok).toHaveBeenCalled());
    expect(calls.some((c) => c.includes("/auth/register"))).toBe(true);
  });
});

describe("apiGet 401 事件", () => {
  it("401 时派发 cs2hq:unauthorized", async () => {
    const handler = vi.fn();
    window.addEventListener("cs2hq:unauthorized", handler);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({ detail: "登录已失效" }) }),
    );
    await expect(apiGet("/tasks")).rejects.toThrow();
    await waitFor(() => expect(handler).toHaveBeenCalled());
    window.removeEventListener("cs2hq:unauthorized", handler);
  });
});
