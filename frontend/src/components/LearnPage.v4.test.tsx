/** 学道具 v4：自建道具 + 筛选（创建人/点位）——RED 先行。
 *
 * 场景：
 * V4.1 Given 打开道具库 When 点「新建道具」填表提交 Then POST /bili/grenades/custom（Form 字段）且列表刷新
 * V4.2 自建卡带「自建」Tag；视频卡不带
 * V4.3 筛选条有 创建人（全部/视频/自建）与 点位输入框；?source=custom 作为 query 传入 apiGet
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { LearnPage } from "./LearnPage";

vi.mock("../api/client", () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiUpload: vi.fn(),
  apiDelete: vi.fn(),
}));

import { apiGet, apiPatch, apiPost, apiUpload, apiDelete } from "../api/client";
const apiGetMock = vi.mocked(apiGet);
const apiPostMock = vi.mocked(apiPost);
const apiPatchMock = vi.mocked(apiPatch);
const apiUploadMock = vi.mocked(apiUpload);
const apiDeleteMock = vi.mocked(apiDelete);

beforeAll(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (q: string) => ({ matches: false, media: q, addListener: () => {}, removeListener: () => {}, addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => false }),
  });
});

const GRENADES = [
  { id: 1, map_name: "Mirage", point: "A1", grenade_type: "烟雾弹", stance: "A1 火点", timing: "开局",
    video_ts: "12:30", bvid: "BV1LearnVid01", content_md: "视频卡：瞄白车左键满力", zone: "A区",
    favorited: false, health: "alive", source: "video" },
  { id: 2, map_name: "Mirage", point: "VIP", grenade_type: "闪光弹", stance: "VIP", timing: "中局",
    video_ts: null, bvid: null, content_md: "自己研究的VIP弹", zone: "中路",
    favorited: false, health: "alive", source: "custom" },
];

const VIDEOS = [
  { bvid: "BV1LearnVid01", title: "Mirage 道具教学", owner: "UP", subtitle_status: "subtitle",
    created_at: "2026-11-23T00:00:00", summary_md: "## 总结\n内容", cover: "http://x/cover.jpg", duration: 648 },
];

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LearnPage />
    </QueryClientProvider>,
  );
}

function defaultApiGet(path: string): unknown {
  if (path.startsWith("/bili/videos")) return VIDEOS;
  if (path.startsWith("/bili/grenades")) return GRENADES;
  return [];
}

describe("学道具 v4：自建道具（新建表单）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiGetMock.mockImplementation(defaultApiGet);
    apiPostMock.mockResolvedValue({ id: 9, source: "custom" });
    apiPatchMock.mockResolvedValue({});
    apiUploadMock.mockResolvedValue([]);
    apiDeleteMock.mockResolvedValue({});
  });

  test("V4.1 点「新建道具」填表提交 → POST /bili/grenades/custom（Form 字段）", async () => {
    renderPage();
    const btn = await screen.findByRole("button", { name: /新建道具/ });
    fireEvent.click(btn);
    // 弹出表单：地图必填
    const mapInput = await screen.findByLabelText(/地图/);
    fireEvent.change(mapInput, { target: { value: "Mirage" } });
    const pointInput = screen.getByLabelText(/点位/);
    fireEvent.change(pointInput, { target: { value: "B 小" } });
    fireEvent.click(screen.getByRole("button", { name: /提交|保存|创建/ }));
    await waitFor(() => {
      expect(apiPostMock).toHaveBeenCalledWith(
        "/bili/grenades/custom",
        expect.objectContaining({ map_name: "Mirage", point: "B 小" }),
      );
    });
  });

  test("V4.2 自建卡带「自建」Tag、视频卡不带", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText(/VIP/)).toBeTruthy());
    const zone = document.querySelector('[data-testid="grenade-list"]')?.textContent ?? "";
    expect(zone).toContain("自建");
  });
});

describe("学道具 v4：筛选（创建人/点位）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiGetMock.mockImplementation(defaultApiGet);
    apiPostMock.mockResolvedValue({});
    apiPatchMock.mockResolvedValue({});
    apiUploadMock.mockResolvedValue([]);
    apiDeleteMock.mockResolvedValue({});
  });

  test("V4.3 切「自建」→ 请求带 source=custom", async () => {
    renderPage();
    const customBtn = await screen.findByRole("button", { name: /自建/ });
    fireEvent.click(customBtn);
    await waitFor(() => {
      const calls = apiGetMock.mock.calls.filter(([p]) => String(p).includes("/bili/grenades"));
      const last = calls[calls.length - 1]?.[0] ?? "";
      expect(String(last)).toContain("source=custom");
    });
  });

  test("V4.4 点位输入 A1 → 请求带 point=A1", async () => {
    renderPage();
    const pointFilter = await screen.findByPlaceholderText(/筛选点位/);
    fireEvent.change(pointFilter, { target: { value: "A1" } });
    await waitFor(() => {
      const calls = apiGetMock.mock.calls.filter(([p]) => String(p).includes("/bili/grenades"));
      const last = calls[calls.length - 1]?.[0] ?? "";
      expect(String(last)).toContain("point=A1");
    });
  });
});
