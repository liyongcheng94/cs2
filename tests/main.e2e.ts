// CS2HQ 端到端实测：docker 栈（frontend 5174 nginx → backend 8101 → MindVault 8300）
//
// 场景（Given/When/Then，见各 test 注释）：
// 1. 总览：加载玩家画像 + 跑 Mock 全链路（UI 触发 → 弹窗显示 pushed 成功）
// 2. 对局：Mock 产生的对局出现在表格，可打开详情
// 3. 任务：任务列表渲染且状态可见
// 4. 设置：MindVault 地址已持久化（docker 注入的 base_url）
import { test } from "@e2e-dev/web";
import { expect } from "e2e";

test.describe("CS2HQ 主流程", () => {
  test("总览加载画像并跑 Mock 全链路推送 MindVault", async ({ app, agent, screen, browser }) => {
    // Given: docker 栈在线（MV 依赖已由 backend 配置 mv.base_url + password）
    await app.open("/");

    // When: 进入总览（默认 Tab），执行 Mock 全链路
    await agent.act("点击「跑一次 Mock 全链路」按钮并等结果弹窗出现");

    // Then: 弹窗显示推送 MindVault 成功
    await expect(screen.getByText("Mock 全链路结果")).toBeVisible({ timeout: 30000 });
    await agent.assert("弹窗里「推送 MindVault」一项显示绿色成功标签（含 mv_uuid），不是红色失败");
    // Mock 对局 match_id 以 PVP@MOCK- 开头
    await agent.assert("弹窗里「假对局」一项的 match_id 以 PVP@MOCK- 开头");
  });

  test("对局表格展示 Mock 对局且详情可打开", async ({ app, agent, screen, browser }) => {
    // Given: 上一个测试已通过 Mock 产生对局数据
    await app.open("/");

    // When: 切到「对局」Tab，打开第一行详情
    await agent.act("点击顶部「对局」标签页，然后点击表格第一行的「详情」链接");

    // Then: 详情弹窗出现（antd Modal），显示对局信息
    await agent.assert("页面出现对局详情弹窗，含地图名或比分信息");
  });

  test("任务页渲染任务列表（Mock 全链路产生的任务或空表）", async ({ app, agent, screen }) => {
    await app.open("/");
    await agent.act("点击顶部「任务」标签页");
    // Then: 任务表格区域渲染（表头 ID/类型/优先级/状态 可见）
    await agent.assert("任务表格已渲染，能看到表头（ID、类型、优先级、状态）");
  });

  test("设置页显示已持久化的 MindVault 地址", async ({ app, agent, screen }) => {
    // Given: backend settings 已写入 mv.base_url = http://host.docker.internal:8300
    await app.open("/");
    await agent.act("点击顶部「设置」标签页");
    // Then: MindVault 地址输入框已带出持久化值（host.docker.internal:8300）
    await agent.assert("「MindVault 地址」输入框的值包含 host.docker.internal:8300");
  });
});
