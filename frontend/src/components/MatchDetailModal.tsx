// 对局详情 Modal（完美平台风格）：PW 式头部 + 综合数据/对枪矩阵/死亡雷达/AI 复盘 四 Tab
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Modal, Spin, Table, Tabs, Tag, Typography } from "antd";
import { marked } from "marked";
import { apiGet } from "../api/client";
import type { MatchDetail } from "../types";
import { DeathScatter } from "./DeathScatter";
import { DuelHeatmap } from "./DuelHeatmap";

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
          { key: "overall", label: "综合数据", children: <OverallTab detail={detail} /> },
          { key: "duels", label: "对枪矩阵", children: <DuelHeatmap analysis={detail.analysis} /> },
          { key: "radar", label: "死亡雷达", children: <DeathScatter analysis={detail.analysis} mapEn={mapEn} /> },
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
