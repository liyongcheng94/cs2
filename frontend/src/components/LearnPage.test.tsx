/**
 * LearnPage 重设计（grill-me L1+L2）组件场景：
 * 1. Given 已学视频带封面与总结 When 渲染 Then 卡片显示封面图 + 已总结 Tag + 查看入口
 * 2. Given 点开卡片 When Modal 打开 Then 渲染 summary_md（marked → HTML）
 * 3. Given 道具卡 When 渲染 Then 道具类型有图标徽章、按地图分组按钮可切换
 * 4. Given 输入框 When 输入 BV/数字/文本 Then 分别走 bvid/up_mid/keyword 三种 payload
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { LearnPage } from "./LearnPage";

// mock api client（组件经 apiGet/apiPost 取数）
vi.mock("../api/client", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
}));

import { apiGet, apiPost } from "../api/client";
const apiGetMock = vi.mocked(apiGet);
const apiPostMock = vi.mocked(apiPost);

// antd 在 jsdom 里需要 matchMedia（responsiveObserver）
beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  });
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LearnPage />
    </QueryClientProvider>,
  );
}

const VIDEOS = [
  {
    bvid: "BV1wallcardA",
    title: "Mirage 突破手教学",
    owner: "DED1E123",
    subtitle_status: "subtitle",
    created_at: "2026-11-23T00:00:00",
    summary_md: "## 总体思路\nVIP 烟是重中之重",
    cover: "http://i1.hdslb.com/bfs/x.jpg",
    duration: 648,
  },
  {
    bvid: "BV1nosumaryB",
    title: "无总结视频",
    owner: null,
    subtitle_status: "no_subtitle",
    created_at: "2026-11-23T00:00:00",
    summary_md: null,
    cover: null,
    duration: null,
  },
];

const GRENADES = [
  {
    id: 1,
    map_name: "Mirage",
    point: "VIP（T方10号位）",
    grenade_type: "烟雾弹",
    stance: "跳跃",
    timing: "开局",
    video_ts: "未提供",
    bvid: "BV1wallcardA",
    content_md: "跳时切狙保留移速。",
  },
  {
    id: 2,
    map_name: "炼狱小镇",
    point: "香蕉道",
    grenade_type: "燃烧弹",
    stance: "石板后",
    timing: "rush B",
    video_ts: "03:24",
    bvid: "BV1wallcardA",
    content_md: "烧香蕉道延缓进攻。",
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  apiGetMock.mockImplementation((path: string) => {
    if (path === "/bili/videos") return Promise.resolve(VIDEOS);
    if (path === "/bili/grenades") return Promise.resolve(GRENADES);
    return Promise.resolve([]);
  });
  apiPostMock.mockResolvedValue({ id: 1, status: "success" } as never);
});

describe("LearnPage L1 视频卡片墙", () => {
  test("有封面与总结的视频渲染封面图与「已总结」Tag", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByAltText("Mirage 突破手教学")).toBeTruthy());
    const img = screen.getByAltText("Mirage 突破手教学") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("http://i1.hdslb.com/bfs/x.jpg");
    expect(img.getAttribute("referrerpolicy")).toBe("no-referrer"); // 防盗链关键
    expect(screen.getByText("已总结")).toBeTruthy();
    expect(screen.getByText("10:48")).toBeTruthy(); // duration 648s → 10:48
  });

  test("无总结视频显示占位不炸，点卡片开 Modal 后渲染总结正文", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("无总结视频")).toBeTruthy());
    // 点有总结的卡片
    fireEvent.click(screen.getByAltText("Mirage 突破手教学").closest(".ant-card")!);
    await waitFor(() => expect(screen.getByText(/VIP 烟是重中之重/)).toBeTruthy());
    // Modal 渲染了 markdown 标题
    expect(screen.getByText("总体思路").tagName).toBe("H2");
  });

  test("Modal 底部有打开原视频链接", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByAltText("Mirage 突破手教学")).toBeTruthy());
    fireEvent.click(screen.getByAltText("Mirage 突破手教学").closest(".ant-card")!);
    await waitFor(() => expect(screen.getByText("打开原视频")).toBeTruthy());
    const link = screen.getByText("打开原视频").closest("a") as HTMLAnchorElement;
    expect(link?.getAttribute("href") ?? "").toContain("https://www.bilibili.com/video/BV1wallcardA");
  });
});

describe("LearnPage L2 道具库", () => {
  test("道具类型渲染图标徽章，地图分组按钮可过滤", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText("Mirage · VIP（T方10号位）")).toBeTruthy());
    // 烟雾弹徽章 + 图标
    expect(screen.getByText(/💨 烟雾弹/)).toBeTruthy();
    expect(screen.getByText(/🔥 燃烧弹/)).toBeTruthy();
    // 分组过滤
    fireEvent.click(screen.getByText("炼狱小镇（1）"));
    expect(screen.queryByText("Mirage · VIP（T方10号位）")).toBeNull();
    expect(screen.getByText("炼狱小镇 · 香蕉道")).toBeTruthy();
  });

  test("video_ts=未提供 时跳转链接不带 t 参数", async () => {
    renderPage();
    await waitFor(() => expect(document.querySelectorAll("a").length).toBeGreaterThan(0));
    const anchors = [...document.querySelectorAll("a")] as HTMLAnchorElement[];
    const vip = anchors.find((a) => (a.getAttribute("href") ?? "").includes("bilibili.com/video/BV1wallcardA") && !(a.getAttribute("href") ?? "").includes("t="));
    expect(vip).toBeTruthy(); // video_ts=未提供 → 不带 t 参数
    const fire = anchors.find((a) => (a.getAttribute("href") ?? "").includes("t=0324"));
    expect(fire).toBeTruthy(); // 03:24 → t=0324
  });
});

describe("LearnPage 学习入口", () => {
  test("BV 前缀走 bvid、纯数字走 up_mid、其余走 keyword", async () => {    renderPage();
    await waitFor(() => expect(screen.getByPlaceholderText("关键词 / BV 号 / UP主 mid 号")).toBeTruthy());
    const input = screen.getByPlaceholderText("关键词 / BV 号 / UP主 mid 号") as HTMLInputElement;
    const btn = screen.getByRole("button", { name: "学 习" });

    fireEvent.change(input, { target: { value: "BV1abcdefgHiJ" } });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith("/tasks", {
        type: "bili_learn",
        payload: { bvid: "BV1abcdefgHiJ" },
      }),
    );

    fireEvent.change(input, { target: { value: "12345" } });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith("/tasks", {
        type: "bili_learn",
        payload: { up_mid: 12345 },
      }),
    );

    fireEvent.change(input, { target: { value: "Mirage 道具" } });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith("/tasks", {
        type: "bili_learn",
        payload: { keyword: "Mirage 道具" },
      }),
    );
  });

  test("含 BV 的完整视频链接 / b23.tv 短链也走 bvid（否则误入 keyword 检索）", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: "学 习" })).toBeTruthy());
    const input = screen.getByPlaceholderText("关键词 / BV 号 / UP主 mid 号") as HTMLInputElement;
    const btn = screen.getByRole("button", { name: "学 习" });

    fireEvent.change(input, { target: { value: "https://www.bilibili.com/video/BV1b1aMziEuE" } });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith("/tasks", {
        type: "bili_learn",
        payload: { bvid: "https://www.bilibili.com/video/BV1b1aMziEuE" },
      }),
    );

    fireEvent.change(input, { target: { value: "https://b23.tv/abc123" } });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith("/tasks", {
        type: "bili_learn",
        payload: { bvid: "https://b23.tv/abc123" },
      }),
    );
  });
});
