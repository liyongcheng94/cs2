// 对局详情 Modal（完美平台风格）：PW 式头部 + 综合数据/对枪矩阵/死亡雷达/AI 复盘 四 Tab
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Modal, Spin, Table, Tabs, Tag, Typography } from "antd";
import { marked } from "marked";
import { apiGet } from "../api/client";
import * as echarts from "echarts";
import type { FourDimAnalysisShape, MatchDetail } from "../types";
import { DeathScatter } from "./DeathScatter";
import { UtilityScatter } from "./UtilityScatter";
import { DuelHeatmap } from "./DuelHeatmap";
import { PerfectAnalysis } from "./PerfectAnalysis";

const { Text } = Typography;

// 中文名 → 英文地图 ID（与后端 MAP_NAME_EN 一致）
const MAP_EN: Record<string, string> = {
  荒漠迷城: "de_mirage",
  炙热沙城Ⅱ: "de_dust2",
  炙热沙城: "de_dust2",
  炼狱小镇: "de_inferno",
  核子危机: "de_nuke",
  远古遗迹: "de_ancient",
  阿努比斯: "de_anubis",
  殒命大厦: "de_vertigo",
};

function resultTag(m: MatchDetail["match"]) {
  if (m.draw) return <Tag color="orange" style={{ fontSize: 18, padding: "2px 10px" }}>平</Tag>;
  return m.win ? (
    <Tag color="green" style={{ fontSize: 18, padding: "2px 10px" }}>胜</Tag>
  ) : (
    <Tag color="red" style={{ fontSize: 18, padding: "2px 10px" }}>败</Tag>
  );
}

// ---------- 综合数据（v1 全场 10 人，PW 风格） ----------
function OverallTab({ detail }: { detail: MatchDetail }) {
  const [v1, setV1] = useState<Record<string, any> | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    apiGet<Record<string, any>>(`/matches/${detail.match.id}/detail-v1`)
      .then(setV1)
      .catch((e) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [detail.match.id]);

  const columns = [
    { title: "玩家", dataIndex: "nickName", ellipsis: true },
    { title: "K/D/A", key: "kda", render: (_: unknown, r: any) => `${r.kill}/${r.death}/${r.assist}` },
    { title: "ADR", dataIndex: "adpr", width: 65, render: (v: any) => v ?? "-" },
    { title: "爆头率", dataIndex: "headShotRatio", width: 80, render: (v: any) => (v != null ? `${(v * 100).toFixed(0)}%` : "-") },
    { title: "KAST", dataIndex: "kast", width: 70, render: (v: any) => v ?? "-" },
    { title: "首杀/首死", key: "entry", render: (_: unknown, r: any) => `${r.entryKill ?? 0}/${r.entryDeath ?? 0}` },
    { title: "补枪", dataIndex: "tradeFragCount", width: 55, render: (v: any) => v ?? "-" },
    { title: "Rating", dataIndex: "rating", width: 70, render: (v: any) => (v != null ? v.toFixed(2) : "-") },
    { title: "WE", dataIndex: "we", width: 55, render: (v: any) => v ?? "-" },
  ];

  if (loading) return <Spin />;
  if (err) return <Text type="danger">载入失败：{err}（token 失效请到设置页重登）</Text>;
  if (!v1?.players) return <Text type="secondary">暂无全场数据</Text>;

  const myId = detail.match.player_id ?? "";
  const players = v1.players as any[];
  const team1 = players.filter((p) => String(p.team) === "1");
  const team2 = players.filter((p) => String(p.team) === "2");
  const base = v1.base ?? {};

  const teamTable = (rows: any[], label: string, color: string) => (
    <>
      <div style={{ margin: "8px 0 4px", color, fontWeight: 600 }}>{label}</div>
      <Table
        rowKey="playerId"
        size="small"
        pagination={false}
        dataSource={rows}
        rowClassName={(r) => (String(r.playerId) === myId ? "my-row" : "")}
        columns={columns}
      />
    </>
  );

  return (
    <div>
      <div style={{ marginBottom: 12 }}>
        <Text type="secondary">
          上半场 {base.halfScore1 ?? "-"}:{base.halfScore2 ?? "-"} · 时长 {base.duration ?? "-"} 分钟 ·
          比赛ID {String(base.matchId ?? "").replace("PVP@", "")}
        </Text>
      </div>
      {teamTable(team1, "队伍 1", "#52c41a")}
      {teamTable(team2, "队伍 2", "#f5222d")}
    </div>
  );
}

// ---------- AI 复盘 ----------
function ReviewTab({ matchId }: { matchId: number }) {
  const review = useQuery({
    queryKey: ["report-md", matchId],
    queryFn: () => apiGet<{ title: string; content_md: string; degraded: boolean }>(`/matches/${matchId}/report-md`),
    retry: false,
  });
  if (review.isLoading) return <Spin />;
  if (review.error) return <Text type="secondary">尚未生成复盘：在对局列表点「分析demo」</Text>;
  const html = marked.parse(review.data!.content_md) as string;
  return (
    <div>
      {review.data!.degraded ? (
        <Text type="warning">⚠️ 本次为数据直读版（AI 未通过校验），可在设置页配好 AI 后重新分析</Text>
      ) : null}
      <div className="report-md" dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}

// ---------- Inner（hooks 安全：每次打开重新挂载） ----------
function Inner({ detail }: { detail: MatchDetail }) {
  const m = detail.match;
  const mapEn = MAP_EN[m.map_name] ?? m.map_en ?? "";

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 8 }}>
        {resultTag(m)}
        <span style={{ fontSize: 30, fontWeight: 700, letterSpacing: 2 }}>
          {m.score1} - {m.score2}
        </span>
        <div style={{ display: "flex", flexDirection: "column", fontSize: 12 }}>
          <span>{m.mode || "对局"}</span>
          <Text type="secondary">{m.map_name}</Text>
        </div>
        <div style={{ marginLeft: "auto", textAlign: "right", fontSize: 12 }}>
          <Text type="secondary">
            {m.played_at ? new Date(m.played_at + "Z").toLocaleString() : ""} · 比赛ID {m.match_id.replace("PVP@", "")}
          </Text>
          <div>
            <span style={{ color: "#999" }}>demo: </span>
            <Tag>{m.demo_status}</Tag>
          </div>
        </div>
      </div>

      <Tabs
        items={[
          { key: "perfect", label: "完整分析", children: <PerfectAnalysis matchId={m.id} /> },
          { key: "overall", label: "综合数据", children: <OverallTab detail={detail} /> },
          { key: "duels", label: "对枪矩阵", children: <DuelHeatmap analysis={detail.analysis} /> },
          { key: "util", label: "道具分析", children: <UtilityTab detail={detail} /> },
          { key: "ratings", label: "服务器评价", children: <RatingsTab detail={detail} /> },
          { key: "radar", label: "死亡雷达", children: <div><DeathScatter analysis={detail.analysis} mapEn={mapEn} /><UtilityScatter analysis={detail.analysis} mapEn={mapEn} /></div> },
          { key: "ai", label: "AI 复盘", children: <ReviewTab matchId={m.id} /> },
        ]}
      />
    </>
  );
}

// ---------- 主 Modal ----------
export function MatchDetailModal({
  open,
  detail,
  onClose,
}: {
  open: boolean;
  detail: MatchDetail | null;
  onClose: () => void;
}) {
  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={1080}
      title={null}
      styles={{ body: { maxHeight: "78vh", overflow: "auto" } }}
    >
      {detail ? <Inner detail={detail} /> : null}
    </Modal>
  );
}

// ---------- 道具分析（PW 风格堆叠条：烟/闪/火/雷 + 花费） ----------
function UtilityTab({ detail }: { detail: MatchDetail & { analysis: FourDimAnalysisShape | null } }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const players = (detail.analysis?.utility?.players ?? []) as Record<string, any>[];

  useEffect(() => {
    if (!ref.current || !players.length) return;
    if (!chartRef.current) chartRef.current = echarts.init(ref.current);
    const chart = chartRef.current;
    const names = players.map((p) => p.nick_name || p.player_id);
    chart.setOption({
      title: { text: "道具投掷统计（烟/闪/火/雷）", left: "center", textStyle: { fontSize: 13, color: "#ccc" } },
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { data: ["烟雾弹", "闪光弹", "燃烧瓶", "手雷"], bottom: 0 },
      grid: { left: 110, right: 60, top: 30, bottom: 40 },
      xAxis: { type: "value" },
      yAxis: { type: "category", data: names, axisLabel: { width: 90, overflow: "truncate" } },
      series: [
        { name: "烟雾弹", type: "bar", stack: "t", data: players.map((p) => p.smoke), itemStyle: { color: "#3b82f6" } },
        { name: "闪光弹", type: "bar", stack: "t", data: players.map((p) => p.flash), itemStyle: { color: "#f59e0b" } },
        { name: "燃烧瓶", type: "bar", stack: "t", data: players.map((p) => p.molotov), itemStyle: { color: "#ef4444" } },
        { name: "手雷", type: "bar", stack: "t", data: players.map((p) => p.he), itemStyle: { color: "#22c55e" } },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [players, detail.match.player_id]);

  if (!players.length) return <Text type="secondary">道具统计需 demo 解析（分析后生成）</Text>;

  return (
    <div>
      <div ref={ref} style={{ width: "100%", height: Math.max(280, players.length * 26 + 80) }} />
      <Table
        rowKey="player_id"
        size="small"
        pagination={false}
        style={{ marginTop: 8 }}
        dataSource={players}
        rowClassName={(r) => (String(r.player_id) === detail.match.player_id ? "my-row" : "")}
        columns={[
          { title: "玩家", dataIndex: "nickName", ellipsis: true },
          { title: "烟", dataIndex: "smoke", width: 50 },
          { title: "闪", dataIndex: "flash", width: 50 },
          { title: "火", dataIndex: "molotov", width: 50 },
          { title: "雷", dataIndex: "he", width: 50 },
          { title: "致盲敌方", dataIndex: "flash_enemies", width: 80 },
          { title: "致盲队友", dataIndex: "flash_teammates", width: 80 },
          { title: "道具伤害", dataIndex: "util_dmg", width: 80 },
          { title: "花费", dataIndex: "spend", width: 70 },
        ]}
      />
    </div>
  );
}

// ---------- 服务器评价（六维能力：我 vs 本场均值 + 规则综合评价） ----------
function RatingsTab({ detail }: { detail: MatchDetail & { analysis: FourDimAnalysisShape | null } }) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const ratings = detail.analysis?.utility?.server_ratings;
  const myId = detail.match.player_id ?? "";

  useEffect(() => {
    if (!ref.current || !ratings || !ratings.players || !myId) return;
    if (!chartRef.current) chartRef.current = echarts.init(ref.current);
    const chart = chartRef.current;
    const dims = Object.keys(ratings.averages);
    const mine = dims.map((d) => ratings.players[myId]?.[d] ?? 0);
    const avg = dims.map((d) => ratings.averages[d] ?? 0);
    chart.setOption({
      title: { text: "六维能力（本场内相对评分 0-100）", left: "center", textStyle: { fontSize: 13, color: "#ccc" } },
      tooltip: { trigger: "axis" },
      legend: { data: ["我的评分", "本场均值"], bottom: 0 },
      grid: { left: 50, right: 20, top: 40, bottom: 50 },
      xAxis: { type: "category", data: dims },
      yAxis: { type: "value", max: 100 },
      series: [
        { name: "我的评分", type: "bar", data: mine, itemStyle: { color: "#22d3ee" }, label: { show: true, position: "top", color: "#fff" } },
        { name: "本场均值", type: "bar", data: avg, itemStyle: { color: "#8b5cf6" }, label: { show: true, position: "top", color: "#fff" } },
      ],
    });
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [ratings, myId]);

  if (!ratings || !ratings.players || !myId || !ratings.players[myId]) {
    return <Text type="secondary">六维评分需 demo 解析 + 全场数据（两者就绪后生成）</Text>;
  }

  const mine = ratings.players[myId];
  const below = Object.entries(mine).filter(([d, v]) => v < (ratings.averages[d] ?? 0) - 2).map(([d]) => d);
  const above = Object.entries(mine).filter(([d, v]) => v > (ratings.averages[d] ?? 0) + 2).map(([d]) => d);
  const verdict =
    below.length > 0
      ? `本场你的 ${below.join("、")} 低于本场其他玩家均值，建议专项练习后重新匹配；${above.length ? `你的 ${above.join("、")} 高于均值，保持即可。` : ""}`
      : `本场你所有维度均不低于场均值，${above.length ? `其中 ${above.join("、")} 领先明显，保持状态。` : "整体表现均衡。"}`;

  return (
    <div>
      <div ref={ref} style={{ width: "100%", height: 320 }} />
      <div style={{ marginTop: 12 }}>
        <Text strong>综合评价：</Text>
        <div style={{ color: "#ccc", fontSize: 13, marginTop: 4 }}>{verdict}</div>
      </div>
    </div>
  );
}
