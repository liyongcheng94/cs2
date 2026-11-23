import { test } from "@e2e-dev/web";
import { expect } from "e2e";

test.describe("学道具页视觉验收", () => {
  test("卡片墙 + 道具库分组渲染", async ({ app, agent, screen }) => {
    await app.open("/");
    await agent.act("点击顶部「学道具」标签页");
    // L1: 卡片墙已渲染（有封面图卡片）
    await expect(screen.getByText("已学视频")).toBeVisible({ timeout: 15000 });
    await agent.assert("「已学视频」区域显示了视频卡片（封面图+标题），下方「道具库」区域按地图显示分组按钮（含「全部」与地图名）");
    await app.screenshot(".e2e/learn-page.png");
  });
});
