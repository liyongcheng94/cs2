// 赛季总览：rating 趋势折线 + 核心指标卡 + 热图地图
import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { Card, Col, Row, Statistic, Space, Tag } from "antd";

export function SeasonTrends({ data }: { data: Record<string, any> }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const dates: string[] = data.historyDates ?? [];
  const ratings: number[] = data.historyRatings ?? [];
  const pwRatings: number[] = data.historyPwRatings ?? [];

  useEffect(() => {
    if (!ref.current) return;
    if (!chartRef.current) chartRef.current = echarts.init(ref.current);
    const chart = chartRef.current;
    chart.setOption({
      title: { text: "rating 趋势（近场）", left: "center", textStyle: { fontSize: 13 } },
      tooltip: { trigger: "axis" },
      legend: { data: ["rating", "pwRating"], bottom: 0 },
      grid: { left: 50, right: 20, top: 40, bottom: 50 },
      xAxis: { type: "category", data: dates.map((d) => d.slice(5, 10)) },
      yAxis: { type: "value", scale: true },
      series: [
        { name: "rating", type: "line", data: ratings, smooth: true, showSymbol: false },
        { name: "pwRating", type: "line", data: pwRatings, smooth: true, showSymbol: false, lineStyle: { type: "dashed" } },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [data]);

  const pct = (v: unknown) => (typeof v === "number" ? `${(v * 100).toFixed(0)}%` : "—");
  const num = (v: unknown) => (typeof v === "number" ? v.toFixed(1) : "—");

  return (
    <Card size="small">
      <Row gutter={16}>
        <Col span={6}><Statistic title="ADR" value={num(data.adr)} /></Col>
        <Col span={6}><Statistic title="KD" value={num(data.kd)} /></Col>
        <Col span={6}><Statistic title="胜率" value={pct(data.winRate)} /></Col>
        <Col span={6}><Statistic title="爆头率" value={pct(data.headShotRatio)} /></Col>
        <Col span={6}><Statistic title="首杀率" value={pct(data.entryKillRatio)} /></Col>
        <Col span={6}><Statistic title="RWS" value={num(data.rws)} /></Col>
        <Col span={6}><Statistic title="MVP 次数" value={data.mvpCount ?? "—"} /></Col>
        <Col span={6}><Statistic title="赛季" value={data.seasonId ?? "—"} /></Col>
      </Row>
      <div ref={ref} style={{ width: "100%", height: 260, marginTop: 12 }} />
      {Array.isArray(data.hotMaps) && data.hotMaps.length ? (
        <Space style={{ marginTop: 8 }}>
          {data.hotMaps.map((m: { map?: string; mapImage?: string }) => (
            <Tag key={m.map}>{m.map}</Tag>
          ))}
        </Space>
      ) : null}
    </Card>
  );
}
