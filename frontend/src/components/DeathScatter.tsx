// 死亡散点：真实雷达底图（awpy-data 提供 PNG + 官方坐标映射 pos_x/pos_y/scale）
// 像素 = (游戏坐标 - pos) / scale；Y 轴翻转（游戏 Y 向上，图像 Y 向下）
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { FourDimAnalysisShape } from "../types";

interface MapMeta {
  pos_x: number;
  pos_y: number;
  scale: number;
  width: number;
  height: number;
}

let MAP_DATA: Record<string, MapMeta> | null = null;
export async function loadMapData(): Promise<Record<string, MapMeta>> {
  if (MAP_DATA) return MAP_DATA;
  const resp = await fetch("/radar/map_data.json");
  MAP_DATA = (await resp.json()) as Record<string, MapMeta>;
  return MAP_DATA;
}

export function DeathScatter({ analysis, mapEn }: { analysis: FourDimAnalysisShape | null; mapEn?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    let cancelled = false;
    const events = (analysis?.deaths?.events ?? []) as Record<string, number>[];

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
            text: mapEn ? `暂无 ${mapEn} 雷达底图` : "散点需含坐标的解析结果",
            left: "center", top: "middle", textStyle: { fontSize: 13, color: "#999" },
          },
        });
        return;
      }

      const toPx = (x: number, y: number): [number, number] => [
        (x - meta.pos_x) / meta.scale,
        (meta.pos_y - y) / meta.scale, // Y 翻转：图像 Y 向下
      ];
      const deathPts: [number, number][] = [];
      const killerPts: [number, number][] = [];
      const links: { coords: [number, number][] }[] = [];
      events.forEach((e) => {
        if (e.victim_x == null || e.victim_y == null) return;
        const v = toPx(e.victim_x, e.victim_y);
        deathPts.push(v);
        if (e.killer_x != null && e.killer_y != null) {
          const k = toPx(e.killer_x, e.killer_y);
          killerPts.push(k);
          links.push({ coords: [k, v] });
        }
      });

      chart.setOption({
        title: { text: "死亡位置（雷达底图）", left: "center", textStyle: { fontSize: 13, color: "#ccc" } },
        tooltip: { show: false },
        xAxis: { type: "value", min: 0, max: meta.width, show: false },
        yAxis: { type: "value", min: 0, max: meta.height, show: false, inverse: true },
        graphic: [
          {
            type: "image",
            style: { image: `/radar/${mapEn}.png`, x: 0, y: 0, width: meta.width, height: meta.height },
            silent: true,
          },
        ],
        series: [
          {
            type: "lines", coordinateSystem: "cartesian2d",
            data: links.map((l) => ({ coords: l.coords })),
            lineStyle: { color: "#ff9800", width: 1.5, opacity: 0.7 }, silent: true, z: 10,
          },
          {
            type: "scatter", data: killerPts, symbolSize: 8,
            itemStyle: { color: "#ecf0f1", borderColor: "#333", borderWidth: 1 }, z: 20, name: "击杀者",
          },
          {
            type: "scatter", data: deathPts, symbolSize: 12,
            itemStyle: { color: "#c0392b", borderColor: "#fff", borderWidth: 1 }, z: 30, name: "你的死亡位置",
          },
        ],
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

  const events = analysis?.deaths?.events ?? [];
  if (!events.some((e) => (e as Record<string, number>).victim_x != null)) {
    return <div style={{ color: "#999", fontSize: 12 }}>死亡散点需含坐标的解析结果（重新分析后生成）</div>;
  }
  return <div ref={ref} style={{ width: "100%", height: 340 }} />;
}
