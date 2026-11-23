// 对枪矩阵热力图：X=距离分桶（0-5m/5-15m/15m+），Y=武器类，色深=胜率（绿胜红负）
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import type { FourDimAnalysisShape } from "../types";

const BUCKETS = ["0-5m", "5-15m", "15m+"];

interface DuelCell {
  distance: string;
  weapon: string;
  kills?: number | null;
  deaths?: number | null;
  win_rate?: number | null;
}

interface DuelsLike {
  by_weapon_distance?: DuelCell[];
}

export function DuelHeatmap({ analysis }: { analysis: FourDimAnalysisShape | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current);
    }
    const chart = chartRef.current;

    const duels: DuelsLike | undefined = analysis?.duels;
    const cells = duels?.by_weapon_distance ?? [];
    const weapons = Array.from(new Set(cells.map((c) => c.weapon)));
    const hasRate = cells.some((c) => c.win_rate != null);

    const data: [number, number, number | null][] = [];
    cells.forEach((c) => {
      const x = BUCKETS.indexOf(c.distance);
      const y = weapons.indexOf(c.weapon);
      if (x >= 0 && y >= 0) data.push([x, y, c.win_rate ?? null]);
    });

    chart.setOption({
      title: { text: "对枪矩阵（胜率）", left: "center", textStyle: { fontSize: 13 } },
      tooltip: {
        formatter: (p: { data: [number, number, number | null] }) => {
          const cell = cells.find(
            (c) => BUCKETS.indexOf(c.distance) === p.data[0] && weapons.indexOf(c.weapon) === p.data[1],
          );
          const wr = p.data[2] == null ? "无数据" : `${(p.data[2] * 100).toFixed(0)}%`;
          return `${cell?.weapon ?? ""} @ ${BUCKETS[p.data[0]]}<br/>击杀 ${cell?.kills ?? 0} / 死亡 ${cell?.deaths ?? 0}<br/>胜率 ${wr}`;
        },
      },
      grid: { left: 80, right: 20, top: 40, bottom: 30 },
      xAxis: { type: "category", data: BUCKETS, splitArea: { show: true } },
      yAxis: { type: "category", data: weapons, splitArea: { show: true } },
      visualMap: hasRate
        ? {
            min: 0,
            max: 1,
            calculable: false,
            orient: "horizontal",
            left: "center",
            bottom: 0,
            inRange: { color: ["#c0392b", "#e67e22", "#27ae60"] },
            show: false,
          }
        : undefined,
      series: [
        {
          type: "heatmap",
          data,
          itemStyle: { borderColor: "#141414", borderWidth: 2 },
          label: {
            show: true,
            formatter: (p: { data: [number, number, number | null] }) =>
              p.data[2] == null ? "-" : `${(p.data[2] * 100).toFixed(0)}%`,
          },
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

  if (!analysis?.duels?.by_weapon_distance?.length) {
    return <div style={{ color: "#999", fontSize: 12 }}>暂无对枪数据（demo 解析后生成）</div>;
  }
  return <div ref={ref} style={{ width: "100%", height: 320 }} />;
}
