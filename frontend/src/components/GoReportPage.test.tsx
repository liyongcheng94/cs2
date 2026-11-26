// GO指导定位分析页（Phase 3）：
// Given 进入定位分析页 When 加载 /matches/go-report?n=10 Then 渲染六维 mine vs 房均 表 + 位置网格表
// Given 切换 N=30 When 重新请求 Then URL 带 n=30
// Given 加载失败 When 接口报错 Then 显示空态提示
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (q: string) => ({ matches: false, media: q, onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }),
  });
});

import { GoReportPage } from "./GoReportPage";

const report = {
  five_dim: {
    瞄准能力: { mine: 65.1, room_avg: 73.7 },
    补枪能力: { mine: 72.6, room_avg: 70.0 },
    突破能力: { mine: 63.2, room_avg: 65.0 },
    道具能力: { mine: 69.9, room_avg: 66.0 },
    残局能力: { mine: 67.5, room_avg: 60.0 },
    火力值: { mine: 64.6, room_avg: 68.0 },
  },
  positions: [
    { grid_row: 1, grid_col: 1, kills: 20, deaths: 8, win_rate: 0.714, label: "优势" },
    { grid_row: 0, grid_col: 2, kills: 5, deaths: 14, win_rate: 0.263, label: "劣势" },
  ],
  matches_analyzed: 10,
};

function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <GoReportPage />
    </QueryClientProvider>,
  );
}

describe("GoReportPage", () => {
  it("渲染六维 mine vs 房均 与位置网格", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => report }));
    mount();
    await waitFor(() => expect(screen.getByText("瞄准能力")).toBeTruthy());
    expect(screen.getByText("65.1")).toBeTruthy();
    expect(screen.getByText("73.7")).toBeTruthy();
    expect(screen.getAllByText(/优势/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/劣势/).length).toBeGreaterThan(0);
    expect(screen.getByText(/分析 10 场/)).toBeTruthy();
  });

  it("切 N=30 重新请求带 n=30", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => report });
    vi.stubGlobal("fetch", fetchMock);
    mount();
    await waitFor(() => expect(screen.getByText("瞄准能力")).toBeTruthy());
    await userEvent.click(screen.getByText("最近 30 场"));
    await waitFor(() => expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("go-report?n=30"))).toBe(true));
  });

  it("加载失败显示空态", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({ detail: "err" }) }));
    mount();
    await waitFor(() => expect(screen.getByText(/暂无定位数据/)).toBeTruthy());
  });
});
