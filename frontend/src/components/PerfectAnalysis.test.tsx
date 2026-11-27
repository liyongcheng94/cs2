// 完美风格完整对局分析组件场景测试
// 场景：
// 1. 渲染后默认拉取 side=ALL，综合数据展示击杀数
// 2. 切到 T 后请求带 side=T，回合数随之变化
// 3. 残局列表渲染胜/保枪着色
// 4. 409（demo 未下载）显示下载提示而非报错
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PerfectAnalysis, type PerfectAnalysisData } from "./PerfectAnalysis";


// antd 在 jsdom 里需要 matchMedia（responsiveObserver）
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false, media: query, onchange: null,
    addListener: () => {}, removeListener: () => {},
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false,
  }),
});

const mockGet = vi.fn();
vi.mock("../api/client", () => ({ apiGet: (...args: unknown[]) => mockGet(...args) }));

function fixture(side: string): PerfectAnalysisData {
  return {
    side,
    summary: { rounds: side === "T" ? 5 : 17, round_wins: 13, kills: 21, deaths: 9, assists: 3, hs_kills: 3, adr: 121.3, opening_kills: 3, opening_deaths: 0 },
    aim: { shots: 245, hits: 41, hit_rate: 0.167, avg_kill_distance: 15.4 },
    entry: { entry_kills: 3, entry_deaths: 0 },
    trade: { trade_kills: 4, trade_opportunities: 42, created_opportunities: 2 },
    utility: { flash_enemies: 5, flash_teammates: 1, flash_assists: 0, util_damage: 1 },
    clutch: {
      attempts: [
        { round_no: 9, vs_count: 3, outcome: "saved", kills_in_clutch: 0 },
        { round_no: 13, vs_count: 2, outcome: "win", kills_in_clutch: 2 },
      ],
    },
    matchup: {
      rows: [{ opponent_id: "222", opponent_name: "agezdi", my_kills: 3, my_deaths: 2, my_damage: 300, their_damage: 250 }],
    },
  };
}

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PerfectAnalysis matchId={68} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  mockGet.mockReset();
  mockGet.mockImplementation((path: string) => {
    if (path.includes("side=T")) return Promise.resolve(fixture("T"));
    return Promise.resolve(fixture("ALL"));
  });
});

describe("PerfectAnalysis", () => {
  it("场景1：默认 ALL 视角，展示综合数据击杀", async () => {
    renderIt();
    await waitFor(() => expect(screen.getByTestId("stat-击杀").textContent).toContain("21"));
    expect(mockGet.mock.calls[0][0]).toContain("side=ALL");
  });

  it("场景2：切 T 后按 side=T 重新请求，回合数变为 T 的值", async () => {
    const user = userEvent.setup();
    renderIt();
    await waitFor(() => expect(screen.getByTestId("stat-回合").textContent).toContain("17"));
    await user.click(screen.getByText("T"));
    await waitFor(() => expect(screen.getByTestId("stat-回合").textContent).toContain("5"));
    expect(mockGet.mock.calls.some((c) => String(c[0]).includes("side=T"))).toBe(true);
  });

  it("场景3：残局 tab 展示胜/保枪", async () => {
    const user = userEvent.setup();
    renderIt();
    await waitFor(() => expect(screen.getByTestId("stat-击杀")).toBeTruthy());
    await user.click(screen.getByText("残局分析"));
    await waitFor(() => {
      expect(screen.getByText("保枪")).toBeTruthy();
      expect(screen.getByText("胜利")).toBeTruthy();
    });
  });

  it("场景4：409 时提示先下载 demo", async () => {
    mockGet.mockRejectedValue(new Error("HTTP 409: demo 不可用"));
    renderIt();
    await waitFor(() => expect(screen.getByText(/请先在对局列表下载 demo/)).toBeTruthy());
  });
});
