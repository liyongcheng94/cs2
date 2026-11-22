// 死亡散点：死亡位置（红）+ 击杀者位置（灰），连线表示击杀方向；地图底图二期接入
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { FourDimAnalysisShape } from "../types";

export function DeathScatter({ analysis }: { analysis: FourDimAnalysisShape | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    if (!chartRef.current) chartRef.current = echarts.init(ref.current);
    const chart = chartRef.current;
    const events = (analysis?.deaths?.events ?? []) as Record<string, number>[];
    const pts: [number, number, string][] = [];
    const links: { coords: [number, number][] }[] = [];
    let placed = 0;
    events.forEach((e) => {
      if (e.victim_x == null || e.victim_y == null) return;
      placed += 1;
      pts.push([e.victim_x, e.victim_y, "death"]);
      if (e.killer_x != null && e.killer_y != null) {
        pts.push([e.killer_x, e.killer_y, "killer"]);
        links.push({ coords: [[e.killer_x, e.killer_y], [e.victim_x, e.victim_y]] });
      }
    });

    chart.setOption({
      title: { text: "死亡位置散点（无底图，二期配雷达图）", left: "center", textStyle: { fontSize: 13 } },
      tooltip: { show: false },
      xAxis: { type: "value", name: "X (game units)", axisLabel: { fontSize: 10 } },
      yAxis: { type: "value", name: "Y (game units)", axisLabel: { fontSize: 10 } },
      series: [
        {
          type: "lines", coordinateSystem: "cartesian2d", data: links.map((l) => ({ coords: l.coords })),
          lineStyle: { color: "#888", width: 1, opacity: 0.5, curveness: 0 }, silent: true,
        },
        {
          type: "scatter", data: pts.filter((p) => p[2] === "killer"),
          symbolSize: 7, itemStyle: { color: "#95a5a6" }, name: "击杀者位置",
        },
        {
          type: "scatter", data: pts.filter((p) => p[2] === "death"),
          symbolSize: 10, itemStyle: { color: "#c0392b" }, name: "你的死亡位置",
        },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [analysis]);

  const events = analysis?.deaths?.events ?? [];
  const hasCoords = events.some((e) => (e as Record<string, number>).victim_x != null);
  if (!hasCoords) {
    return <div style={{ color: "#999", fontSize: 12 }}>死亡散点需含坐标的解析结果（重新分析后生成）</div>;
  }
  return <div ref={ref} style={{ width: "100%", height: 300 }} />;
}
