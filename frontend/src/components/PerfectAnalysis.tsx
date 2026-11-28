// 完美风格完整对局分析：ALL/T/CT 切换 + 综合/瞄准/突破/补枪/道具/残局/对位 七维度
// 场景：切换 side 后重新拉取 /matches/{id}/perfect?side=；无 demo 时给 409 提示
import { useQuery } from "@tanstack/react-query";
import { Descriptions, Radio, Spin, Table, Tabs, Typography } from "antd";
import { useState } from "react";
import { apiGet } from "../api/client";

const { Text } = Typography;

export interface PerfectAnalysisData {
  side: string;
  summary: {
    rounds: number; round_wins: number; kills: number; deaths: number;
    assists: number; hs_kills: number; adr: number;
    opening_kills: number; opening_deaths: number;
  };
  aim: { shots: number; hits: number; hit_rate: number; avg_kill_distance: number };
  entry: { entry_kills: number; entry_deaths: number };
  trade: { trade_kills: number; trade_opportunities: number; created_opportunities: number };
  utility: { flash_enemies: number; flash_teammates: number; flash_assists: number; util_damage: number };
  clutch: { attempts: { round_no: number; vs_count: number; outcome: string; kills_in_clutch: number }[] };
  matchup: { rows: { opponent_id: string; opponent_name: string; my_kills: number; my_deaths: number; my_damage: number; their_damage: number }[] };
}

const pct = (v: number) => `${(v * 100).toFixed(0)}%`;

function usePerfect(matchId: number | undefined, side: string) {
  return useQuery({
    queryKey: ["perfect", matchId, side],
    enabled: matchId !== undefined,
    queryFn: () => apiGet<PerfectAnalysisData>(`/matches/${matchId}/perfect?side=${side}`),
  });
}

function Stat({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div style={{ textAlign: "center", padding: "8px 4px" }} data-testid={`stat-${label}`}>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
      <Text type="secondary" style={{ fontSize: 12 }}>{label}</Text>
      {hint ? <div style={{ fontSize: 11, color: "#888" }}>{hint}</div> : null}
    </div>
  );
}

function SummaryTab({ d }: { d: PerfectAnalysisData }) {
  const s = d.summary;
  const wr = s.rounds ? Math.round((s.round_wins / s.rounds) * 100) : 0;
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-around", flexWrap: "wrap" }}>
        <Stat label="回合" value={s.rounds} hint={`胜率 ${wr}%`} />
        <Stat label="击杀" value={s.kills} />
        <Stat label="死亡" value={s.deaths} />
        <Stat label="助攻" value={s.assists} />
        <Stat label="ADR" value={s.adr} hint="回合均伤" />
        <Stat label="爆头击杀" value={s.hs_kills} />
        <Stat label="首杀" value={s.opening_kills} />
        <Stat label="首死" value={s.opening_deaths} />
      </div>
    </div>
  );
}

function AimTab({ d }: { d: PerfectAnalysisData }) {
  const a = d.aim;
  return (
    <Descriptions size="small" column={2} bordered>
      <Descriptions.Item label="开枪次数">{a.shots}</Descriptions.Item>
      <Descriptions.Item label="命中次数">{a.hits}</Descriptions.Item>
      <Descriptions.Item label="命中率">{pct(a.hit_rate)}</Descriptions.Item>
      <Descriptions.Item label="平均击杀距离">{a.avg_kill_distance} m</Descriptions.Item>
    </Descriptions>
  );
}

function EntryTab({ d }: { d: PerfectAnalysisData }) {
  const e = d.entry;
  const total = e.entry_kills + e.entry_deaths;
  return (
    <Descriptions size="small" column={2} bordered>
      <Descriptions.Item label="首杀成功">{e.entry_kills}</Descriptions.Item>
      <Descriptions.Item label="首死">{e.entry_deaths}</Descriptions.Item>
      <Descriptions.Item label="首杀成功率" span={2}>
        {total ? pct(e.entry_kills / total) : "-"}
      </Descriptions.Item>
    </Descriptions>
  );
}

function TradeTab({ d }: { d: PerfectAnalysisData }) {
  const t = d.trade;
  return (
    <Descriptions size="small" column={2} bordered>
      <Descriptions.Item label="补枪成功">{t.trade_kills}</Descriptions.Item>
      <Descriptions.Item label="补枪机会（队友死时我 ≤20m）">{t.trade_opportunities}</Descriptions.Item>
      <Descriptions.Item label="补枪率">{t.trade_opportunities ? pct(t.trade_kills / t.trade_opportunities) : "-"}</Descriptions.Item>
      <Descriptions.Item label="为队友创造补枪机会">{t.created_opportunities}</Descriptions.Item>
    </Descriptions>
  );
}

function UtilityTab({ d }: { d: PerfectAnalysisData }) {
  const u = d.utility;
  return (
    <Descriptions size="small" column={2} bordered>
      <Descriptions.Item label="有效致盲敌人">{u.flash_enemies}</Descriptions.Item>
      <Descriptions.Item label="致盲队友">{u.flash_teammates}</Descriptions.Item>
      <Descriptions.Item label="道具伤害">{u.util_damage}</Descriptions.Item>
      <Descriptions.Item label="闪敌:闪友">{u.flash_teammates ? (u.flash_enemies / u.flash_teammates).toFixed(1) : u.flash_enemies}</Descriptions.Item>
    </Descriptions>
  );
}

const OUTCOME_TEXT: Record<string, { label: string; color: string }> = {
  win: { label: "胜利", color: "#52c41a" },
  loss: { label: "失败", color: "#ff4d4f" },
  saved: { label: "保枪", color: "#faad14" },
};

function ClutchTab({ d }: { d: PerfectAnalysisData }) {
  const attempts = d.clutch.attempts;
  const wins = attempts.filter((a) => a.outcome === "win").length;
  const cols = [
    { title: "回合", dataIndex: "round_no", width: 60 },
    { title: "残局", key: "vs", render: (_: unknown, r: { vs_count: number }) => `1v${r.vs_count}` },
    { title: "残局击杀", dataIndex: "kills_in_clutch", width: 80 },
    {
      title: "结果", dataIndex: "outcome", width: 80,
      render: (o: string) => <span style={{ color: OUTCOME_TEXT[o]?.color }}>{OUTCOME_TEXT[o]?.label ?? o}</span>,
    },
  ];
  return (
    <div>
      <div style={{ margin: "4px 0" }}>
        残局 {attempts.length} 次 · 胜 {wins} 次 · 胜率 {attempts.length ? pct(wins / attempts.length) : "-"}
      </div>
      <Table rowKey={(r) => `${r.round_no}-${r.vs_count}`} size="small" pagination={false}
        dataSource={attempts} columns={cols} />
    </div>
  );
}

function MatchupTab({ d }: { d: PerfectAnalysisData }) {
  const cols = [
    { title: "对手", dataIndex: "opponent_name", ellipsis: true },
    { title: "我杀他", dataIndex: "my_kills", width: 70 },
    { title: "他杀我", dataIndex: "my_deaths", width: 70 },
    { title: "我打伤害", dataIndex: "my_damage", width: 90, render: (v: number) => Math.round(v) },
    { title: "他打伤害", dataIndex: "their_damage", width: 90, render: (v: number) => Math.round(v) },
    {
      title: "对位", key: "duel", width: 90,
      render: (_: unknown, r: { my_kills: number; my_deaths: number }) => {
        const t = r.my_kills + r.my_deaths;
        return t ? (
          <span style={{ color: r.my_kills >= r.my_deaths ? "#52c41a" : "#ff4d4f" }}>
            {Math.round((r.my_kills / t) * 100)}%
          </span>
        ) : "-";
      },
    },
  ];
  return <Table rowKey="opponent_id" size="small" pagination={false} dataSource={d.matchup.rows} columns={cols} />;
}

export function PerfectAnalysis({ matchId }: { matchId: number }) {
  const [side, setSide] = useState("ALL");
  const q = usePerfect(matchId, side);

  if (q.isLoading) return <Spin />;
  if (q.isError) {
    const msg = (q.error as Error).message;
    return <Text type="secondary">{msg.includes("409") ? "demo 未下载，请先在对局列表下载 demo" : `载入失败：${msg}`}</Text>;
  }
  if (!q.data) return <Text type="secondary">暂无数据</Text>;
  const d = q.data;

  return (
    <div data-testid="perfect-analysis">
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 8 }}>
        <Radio.Group value={side} onChange={(e) => setSide(e.target.value)} size="small" optionType="button" buttonStyle="solid">
          <Radio.Button value="ALL">ALL</Radio.Button>
          <Radio.Button value="T">T</Radio.Button>
          <Radio.Button value="CT">CT</Radio.Button>
        </Radio.Group>
      </div>
      <Tabs
        size="small"
        items={[
          { key: "summary", label: "综合数据", children: <SummaryTab d={d} /> },
          { key: "aim", label: "瞄准分析", children: <AimTab d={d} /> },
          { key: "entry", label: "突破分析", children: <EntryTab d={d} /> },
          { key: "trade", label: "补枪分析", children: <TradeTab d={d} /> },
          { key: "utility", label: "道具分析", children: <UtilityTab d={d} /> },
          { key: "clutch", label: "残局分析", children: <ClutchTab d={d} /> },
          { key: "matchup", label: "对位分析", children: <MatchupTab d={d} /> },
        ]}
      />
    </div>
  );
}
