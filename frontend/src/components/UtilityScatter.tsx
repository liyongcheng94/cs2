// 道具散点：烟/火落点 + 被闪位置，复用 awpy-data 雷达底图与 DeathScatter 的官方坐标映射
// 像素 = (游戏坐标 - pos) / scale；Y 轴翻转（游戏 Y 向上，图像 Y 向下）
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { loadMapData } from "./DeathScatter";
import type { FourDimAnalysisShape } from "../types";

const KIND_COLOR: Record<string, string> = {
  smoke: "#95a5a6", // 烟：灰绿
  fire: "#e67e22", // 火：橙
  blind: "#f1c40f", // 闪：黄
};
const KIND_NAME: Record<string, string> = { smoke: "烟雾落点", fire: "燃烧落点", blind: "被闪位置" };

export function UtilityScatter({ analysis, mapEn }: { analysis: FourDimAnalysisShape | null; mapEn?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    let cancelled = false;
    const spots = (analysis?.utility?.spots ?? []) as { kind: string; x: number; y: number }[];

    (async () => {
      const meta = mapEn ? await loadMapData().then((d) => d[mapEn]) : undefined;
      if (cancelled) return;
      if (!ref.current) return;
      if (!chartRef.current) chartRef.current = echarts.init(ref.current);
      const chart = chartRef.current;

      if (!meta) {
        chart.clear();
        chart.setOption({
          title: {
            text: mapEn ? `暂无 ${mapEn} 雷达底图` : "道具散点需含坐标的解析结果",
            left: "center", top: "middle", textStyle: { fontSize: 13, color: "#999" },
          },
        });
        return;
      }

      const toPx = (x: number, y: number): [number, number] => [
        (x - meta.pos_x) / meta.scale,
        (meta.pos_y - y) / meta.scale,
      ];
      const byKind: Record<string, [number, number][]> = { smoke: [], fire: [], blind: [] };
      spots.forEach((s) => {
        if (byKind[s.kind] && s.x != null && s.y != null) byKind[s.kind].push(toPx(s.x, s.y));
      });

      chart.setOption({
        title: { text: "道具落点（烟雾/燃烧/致盲）", left: "center", textStyle: { fontSize: 13, color: "#ccc" } },
        legend: { bottom: 0, textStyle: { color: "#ccc", fontSize: 11 } },
        xAxis: { type: "value", min: 0, max: meta.width, show: false },
        yAxis: { type: "value", min: 0, max: meta.height, show: false, inverse: true },
        graphic: [
          {
            type: "image",
            style: { image: `/radar/${mapEn}.png`, x: 0, y: 0, width: meta.width, height: meta.height },
            silent: true,
          },
        ],
        series: (["smoke", "fire", "blind"] as const).map((kind) => ({
          type: "scatter" as const,
          name: KIND_NAME[kind],
          data: byKind[kind],
          symbolSize: kind === "smoke" ? 14 : 10,
          itemStyle: {
            color: KIND_COLOR[kind],
            opacity: 0.75,
            borderColor: "#222",
            borderWidth: 1,
          },
          z: kind === "blind" ? 30 : 20,
        })),
      });
    })();

    const onResize = () => chartRef.current?.resize();
    window.addEventListener("resize", onResize);
    return () => {
      cancelled = true;
      window.removeEventListener("resize", onResize);
      chartRef.current?.dispose();
      chartRef.current = null;
    };
  }, [analysis, mapEn]);

  const spots = analysis?.utility?.spots ?? [];
  if (!spots.length) {
    return <div style={{ color: "#999", fontSize: 12 }}>道具落点需含坐标的解析结果（重新分析后生成）</div>;
  }
  return <div ref={ref} style={{ width: "100%", height: 340 }} />;
}
