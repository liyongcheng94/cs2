// CS2HQ 端到端实测：docker 栈（frontend 5174 nginx → backend 8101 → MindVault 8300）
//
// 场景（Given/When/Then，见各 test 注释）：
// 1. 总览：加载玩家画像 + 赛季趋势卡渲染
// 2. 对局：对局表格渲染，可打开详情
// 3. 任务：任务列表渲染且状态可见
// 4. 设置：MindVault 地址已持久化（docker 注入的 base_url）
// （Mock 全链路 UI 已随 /test/mock-flow 删除，见 commit "remove mock flow"）
import { test } from "@e2e-dev/web";
import { expect } from "e2e";

test.describe("CS2HQ 主流程", () => {
  test("总览加载玩家画像与赛季趋势", async ({ app, agent, screen, browser }) => {
    // Given: docker 栈在线
    await app.open("/");

    // When: 进入总览（默认 Tab）
    await agent.act("等待总览页加载完成，不做任何操作");

    // Then: 玩家画像卡片渲染（eDPI/主玩地图等统计）
    await expect(screen.getByText("玩家基线画像（来自 DeepSeek 对话还原）")).toBeVisible({ timeout: 30000 });
    await agent.assert("总览页显示了玩家画像统计（如 eDPI、主玩地图、爆头率），无报错弹窗");
  });

  test("对局表格渲染且详情可打开", async ({ app, agent, screen, browser }) => {
    await app.open("/");

    // When: 切到「对局」Tab，打开第一行详情（如表格有数据）
    await agent.act("点击顶部「对局」标签页，若表格有数据则点击第一行的「详情」链接");

    // Then: 详情弹窗出现（antd Modal），显示对局信息
    await agent.assert("对局页正常渲染；若打开了详情，弹窗里含地图名或比分信息");
  });

  test("任务页渲染任务列表", async ({ app, agent, screen }) => {
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
