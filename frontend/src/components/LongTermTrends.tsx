// 长期追踪：/api/matches/stats/trends → rating/致盲/ADR 逐场折线 + 地图胜率条形
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { Card, Col, Empty, Row, Statistic, Spin } from "antd";
import { useQuery } from "@tanstack/react-query";
import { apiGet } from "../api/client";

interface TrendPoint {
  match_id: string;
  played_at: string | null;
  map_en: string;
  win: boolean | null;
  rating?: number | null;
  adr?: number | null;
  utility?: { enemy_blind_s?: number | null; team_blind_s?: number | null; waste_rate?: number | null } | null;
  economy?: { eco_win_rate?: number | null; full_buy_lose_rate?: number | null } | null;
}
interface TrendsData {
  points: TrendPoint[];
  by_map: { map_en: string; map_name: string; games: number; wins: number; win_rate: number | null }[];
}

function LineChart({ title, series, dates }: { title: string; series: echarts.SeriesOption[]; dates: string[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  useEffect(() => {
    if (!ref.current) return;
    if (!chartRef.current) chartRef.current = echarts.init(ref.current);
    const chart = chartRef.current;
    chart.setOption({
      title: { text: title, left: "center", textStyle: { fontSize: 13 } },
      tooltip: { trigger: "axis" },
      legend: { bottom: 0, textStyle: { fontSize: 11 } },
      grid: { left: 45, right: 20, top: 36, bottom: 46 },
      xAxis: { type: "category", data: dates },
      yAxis: { type: "value", scale: true },
      series,
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [title, series, dates]);
  return <div ref={ref} style={{ width: "100%", height: 240 }} />;
}

export function LongTermTrends() {
  const { data, isLoading } = useQuery<TrendsData>({
    queryKey: ["trends"],
    queryFn: () => apiGet<TrendsData>("/matches/stats/trends"),
  });

  if (isLoading) return <Spin />;
  if (!data || !data.points.length) return <Empty description="暂无对局数据（先从完美平台同步）" />;

  const pts = [...data.points].reverse(); // 时间正序便于折线
  const dates = pts.map((p) => (p.played_at ?? "").slice(5, 10));
  const hasUtility = pts.some((p) => p.utility?.enemy_blind_s != null);

  return (
    <Card size="small">
      <Row gutter={16}>
        <Col span={6}><Statistic title="对局总数" value={data.points.length} /></Col>
        <Col span={6}>
          <Statistic
            title="总胜率"
            value={
              data.by_map.length
                ? `${(
                    (data.points.filter((p) => p.win).length / Math.max(1, data.points.filter((p) => p.win != null).length)) * 100
                  ).toFixed(0)}%`
                : "—"
            }
          />
        </Col>
        <Col span={6}><Statistic title="地图数" value={data.by_map.length} /></Col>
      </Row>
      <div style={{ marginTop: 12 }}>
        <LineChart
          title="rating / ADR 趋势（逐场）"
          dates={dates}
          series={[
            { name: "rating", type: "line", data: pts.map((p) => p.rating ?? null), smooth: true, showSymbol: false },
            { name: "ADR", type: "line", data: pts.map((p) => p.adr ?? null), smooth: true, showSymbol: false, yAxisIndex: 0 },
          ]}
        />
      </div>
      {hasUtility ? (
        <div style={{ marginTop: 8 }}>
          <LineChart
            title="道具指标趋势（致盲敌方/队友/闪光浪费率）"
            dates={dates}
            series={[
              { name: "致盲敌方(s)", type: "line", data: pts.map((p) => p.utility?.enemy_blind_s ?? null), smooth: true },
              { name: "致盲队友(s)", type: "line", data: pts.map((p) => p.utility?.team_blind_s ?? null), smooth: true },
              { name: "闪光浪费率", type: "line", data: pts.map((p) => p.utility?.waste_rate ?? null), smooth: true },
            ]}
          />
        </div>
      ) : null}
      <div style={{ marginTop: 8 }}>
        <LineChart
          title="地图胜率"
          dates={data.by_map.map((m) => m.map_name)}
          series={[
            {
              name: "胜率",
              type: "bar",
              data: data.by_map.map((m) => m.win_rate),
              label: { show: true, formatter: (p: unknown) => `${((p as { data: number }).data * 100).toFixed(0)}%` },
            },
          ]}
        />
      </div>
    </Card>
  );
}
