// AI 教练图片对话（OCR 间接路线）前端场景：
// Given 点击上传按钮选择截图 When 上传成功 Then 预览缩略图出现在输入区（pending）
// And   发送消息带 image_ids → 发送后预览清空，消息气泡显示图片
// Given 上传失败 When 接口 400 Then 显示错误提示且不进入 pending
// Given 会话历史含 image_ids When 打开会话 Then 气泡渲染缩略图（Image.PreviewGroup）
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---- jsdom + antd 环境补丁（与 LearnPage.test.tsx 相同） ----
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
  // jsdom 未实现 scrollIntoView（antd useEffect 触底滚动需要）
  Element.prototype.scrollIntoView = vi.fn();
});

import { CoachChat } from "./CoachChat";

// ---- API 桩 ----
const apiGet = vi.fn();
const apiPost = vi.fn();
const apiUpload = vi.fn();
const apiDelete = vi.fn();

vi.mock("../api/client", () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPost: (...a: unknown[]) => apiPost(...a),
  apiUpload: (...a: unknown[]) => apiUpload(...a),
  apiDelete: (...a: unknown[]) => apiDelete(...a),
}));

// SSE fetch 桩：立即 done（避免流式逻辑悬挂）
vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 200 })));

function renderChat() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CoachChat />
    </QueryClientProvider>
  );
}

const IMG = { id: 9, url: "/api/chat/uploads/9/x.png", filename: "x.png", ocr_text: "爆头率 31.9%" };

// 训练处方卡桩（beforeEach 里可覆盖）
let trainingCards: Array<{
  id: number;
  session_id: number;
  title: string;
  detail: string;
  duration_min: number | null;
  check: string;
  task_id: number | null;
}> = [];

describe("CoachChat 图片上传（OCR 间接路线）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => {
      const stream = new ReadableStream({
        start(c) {
          c.enqueue(new TextEncoder().encode('data: {"delta":"教练回复"}\n\n'));
          c.enqueue(new TextEncoder().encode('data: {"done":true}\n\n'));
          c.close();
        },
      });
      return Promise.resolve(new Response(stream, { status: 200 }));
    }));
    apiGet.mockImplementation((path: string) => {
      if (path === "/chat/sessions") return Promise.resolve([{ id: 1, title: "新对话", created_at: "t" }]);
      if (path === "/chat/training-cards") return Promise.resolve(trainingCards);
      return Promise.resolve([
        { id: 1, role: "user", content: "看我的数据", image_ids: [9] },
        { id: 2, role: "assistant", content: "教练回复", image_ids: [] },
      ]);
    });
    apiUpload.mockResolvedValue([IMG]);
    apiPost.mockResolvedValue({ id: 2 }); // 新对话按钮 → 立即拿到 activeId，Upload 不再 disabled
    trainingCards = [];
  });

  it("上传成功 → pending 缩略图出现，发送后清空（图片随消息绑定）", async () => {
    renderChat();
    await userEvent.click(screen.getByRole("button", { name: "新对话" }));
    const file = new File(["fake"], "shot.png", { type: "image/png" });
    await waitFor(() => {
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      expect(input && !input.disabled).toBe(true);
    });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, file);
    await waitFor(() => expect(apiUpload).toHaveBeenCalled());
    const [calledPath, calledFiles] = apiUpload.mock.calls[0];
    expect(calledPath).toBe("/chat/images");
    expect((calledFiles as File[]).map((f) => f.name)).toEqual(["shot.png"]);
    await waitFor(() => expect(screen.getByTestId("pending-images")).toBeTruthy());
    // 发送 → pending 清空
    apiPost.mockResolvedValue({ id: 1 });
    await userEvent.click(screen.getByRole("button", { name: /发\s*送/ }));
    await waitFor(() => expect(screen.queryByTestId("pending-images")).toBeNull());
  });

  it("上传失败（非图片 400）→ 提示错误且不进入 pending", async () => {
    apiUpload.mockRejectedValue(new Error("仅支持图片（jpeg/png/webp），收到 text/plain"));
    renderChat();
    await userEvent.click(screen.getByRole("button", { name: "新对话" }));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["x"], "a.txt", { type: "text/plain" }));
    await waitFor(() => expect(screen.queryByTestId("pending-images")).toBeNull());
  });

  it("历史消息含 image_ids → 气泡渲染缩略图（可预览）", async () => {
    renderChat();
    await userEvent.click(screen.getByRole("button", { name: "新对话" }));
    await waitFor(() => {
      const imgs = Array.from(document.querySelectorAll("img"));
      expect(imgs.some((i) => (i.getAttribute("src") || "").includes("/api/chat/uploads/9/"))).toBe(true);
    });
  });

  it("空输入但有待发图片 → 发送兜底文案「看图分析」", async () => {
    renderChat();
    await userEvent.click(screen.getByRole("button", { name: "新对话" }));
    await waitFor(() => {
      const input = document.querySelector('input[type="file"]') as HTMLInputElement;
      expect(input && !input.disabled).toBe(true);
    });
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await userEvent.upload(input, new File(["fake"], "s.png", { type: "image/png" }));
    await waitFor(() => expect(screen.getByTestId("pending-images")).toBeTruthy());
    await userEvent.click(screen.getByRole("button", { name: /发\s*送/ }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("/api/chat/stream"),
        expect.objectContaining({
          body: expect.stringContaining('"image_ids":[9]'),
        })
      )
    );
    const body = JSON.parse((fetch as ReturnType<typeof vi.fn>).mock.calls[0][1].body);
    expect(body.content).toBe("看图分析");
  });
});

describe("CoachChat 训练处方卡（v3）", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 200 })));
    apiGet.mockImplementation((path: string) => {
      if (path === "/chat/sessions") return Promise.resolve([{ id: 1, title: "新对话", created_at: "t" }]);
      if (path === "/chat/training-cards") return Promise.resolve(trainingCards);
      return Promise.resolve([]);
    });
    trainingCards = [];
  });

  it("处方卡列表渲染：标题/时长/详情/验收标准", async () => {
    trainingCards = [
      { id: 1, session_id: 1, title: "Aim Botz 爆头流", detail: "只点头 200 个", duration_min: 30, check: "爆头击杀 200", task_id: null },
    ];
    renderChat();
    await waitFor(() => expect(screen.getByText("Aim Botz 爆头流")).toBeTruthy());
    expect(screen.getByText(/30 分钟/)).toBeTruthy();
    expect(screen.getByText(/只点头 200 个/)).toBeTruthy();
    expect(screen.getByText(/验收：爆头击杀 200/)).toBeTruthy();
  });

  it("一键入任务：点击「加入任务」调 to-task，成功后按钮变「已入任务」", async () => {
    trainingCards = [
      { id: 7, session_id: 1, title: "急停爆头训练", detail: "d", duration_min: 20, check: "c", task_id: null },
    ];
    // 注意：Promise.resolve(trainingCards) 在 queryFn 调用时已捕获数组引用，事后改变量无效；
    // 必须在 apiPost 时点切换 apiGet 的 mockImplementation（新数组字面量），refetch 才拿到已入任务状态
    apiPost.mockImplementation(() => {
      apiGet.mockImplementation((path: string) => {
        if (path === "/chat/sessions") return Promise.resolve([{ id: 1, title: "新对话", created_at: "t" }]);
        if (path === "/chat/training-cards")
          return Promise.resolve([{ id: 7, session_id: 1, title: "急停爆头训练", detail: "d", duration_min: 20, check: "c", task_id: 55 }]);
        return Promise.resolve([]);
      });
      return Promise.resolve({ task_id: 55 });
    });
    renderChat();
    const btn = await screen.findByRole("button", { name: /加\s*入\s*任\s*务/ });
    await userEvent.click(btn);
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith("/chat/training-cards/7/to-task"));
    // invalidation 后重拉列表 → 已入任务（antd Tag 文本跨元素拆分，用容器文本匹配）
    const cardsBox = await screen.findByTestId("training-cards");
    await waitFor(() => expect(cardsBox.textContent).toContain("已入任务"));
  });

  it("已入任务的卡显示「已入任务」标签且不再出现加入按钮", async () => {
    trainingCards = [
      { id: 7, session_id: 1, title: "急停爆头训练", detail: "d", duration_min: 20, check: "c", task_id: 55 },
    ];
    renderChat();
    await waitFor(() => expect(screen.getByText(/已入任务/)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /加\s*入\s*任\s*务/ })).toBeNull();
  });

  it("无处方卡 → 显示占位说明", async () => {
    renderChat();
    await waitFor(() =>
      expect(screen.getByText(/教练给出的训练安排会自动生成卡片/)).toBeTruthy()
    );
  });
});
