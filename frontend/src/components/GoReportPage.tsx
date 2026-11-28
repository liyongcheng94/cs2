// GO指导定位分析页（Phase 3）：六维 mine vs 房均 + 3×3 位置网格（优势/劣势区）
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card, Radio, Space, Table, Tag, Typography } from "antd";
import { apiGet } from "../api/client";

const { Text } = Typography;

interface DimValue {
  mine: number | null;
  room_avg: number | null;
}
interface GoReport {
  five_dim: Record<string, DimValue>;
  positions: { grid_row: number; grid_col: number; kills: number; deaths: number; win_rate: number | null; label: string }[];
  callouts?: { place: string; kills: number; deaths: number; win_rate: number | null; label: string }[];
  matches_analyzed: number;
}

const DIM_ORDER = ["瞄准能力", "补枪能力", "突破能力", "道具能力", "残局能力", "火力值"];

const LABEL_COLOR: Record<string, string> = { 优势: "green", 劣势: "red", 均衡: "default" };

// nav mesh place names → 玩家惯用叫法（未列出的显示原名）
const PLACE_ZH: Record<string, string> = {
  BombsiteA: "A 包点", BombsiteB: "B 包点", CTSpawn: "警家", TSpawn: "匪口/老家",
  Middle: "中路", TopofMid: "中路顶台", Connector: "拱门连接", Jungle: "Jungle（警家坡上）",
  PalaceAlley: "A1（宫殿坡道）", PalaceInterior: "宫殿二楼", Apartments: "B2 楼（公寓）",
  TRamp: "A1 坡道", Ramp: "A1 坡道", SnipersNest: "狙位（警家窗）", TicketBooth: "检票亭",
  Catwalk: "B 小（侧道）", SideAlley: "侧道", BackAlley: "后巷", Shop: "商店",
  House: "房子", Tunnel: "B 通道", TunnelStairs: "B 通道楼梯", Stairs: "楼梯",
  Scaffolding: "脚手架", Balcony: "阳台", Ladder: "梯子", Truck: "卡车",
  Short: "B 短", Long: "A 长", Pit: "Pit（A 包点坑）", Site: "包点",
  Chicken: "鸡位", Window: "窗口", Vip: "VIP 位", Sandbags: "沙袋",
  Heaven: "天位", Hell: "地位", Default: "默认位", Barrels: "桶位",
  Triple: "三箱位", Car: "车位", Library: "图书馆", Gates: "大门",
  Coffee: "咖啡位", Kitchen: "厨房", Garage: "车库", Fountain: "喷泉",
};

function placeZh(p: string): string {
  return PLACE_ZH[p] ? `${PLACE_ZH[p]}（${p}）` : p;
}

export function GoReportPage() {
  const [n, setN] = useState<number>(10);
  const report = useQuery({
    queryKey: ["go-report", n],
    queryFn: () => apiGet<GoReport>(`/matches/go-report?n=${n}`),
  });

  const dimRows = Object.entries(report.data?.five_dim ?? {})
    .filter(([k]) => DIM_ORDER.includes(k))
    .map(([k, v]) => ({
      key: k,
      dim: k,
      mine: v.mine,
      room_avg: v.room_avg,
      diff: v.mine !== null && v.room_avg !== null ? v.mine - v.room_avg : null,
    }));

  const posRows = (report.data?.positions ?? []).map((p) => ({
    key: `${p.grid_row}-${p.grid_col}`,
    zone: `区域(${p.grid_row},${p.grid_col})`,
    ...p,
  }));

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Space>
        <Radio.Group value={n} onChange={(e) => setN(e.target.value)} optionType="button">
          <Radio.Button value={5}>最近 5 场</Radio.Button>
          <Radio.Button value={10}>最近 10 场</Radio.Button>
          <Radio.Button value={30}>最近 30 场</Radio.Button>
        </Radio.Group>
        {report.data ? <Text type="secondary">分析 {report.data.matches_analyzed} 场</Text> : null}
      </Space>

      <Card title="高阶数据 · 我的评分 vs 房均">
        <Table
          rowKey="key"
          size="small"
          loading={report.isLoading}
          dataSource={dimRows}
          pagination={false}
          columns={[
            { title: "维度", dataIndex: "dim", key: "dim" },
            { title: "我的评分", dataIndex: "mine", key: "mine", render: (v: number | null) => v ?? "-" },
            { title: "房均", dataIndex: "room_avg", key: "room_avg", render: (v: number | null) => v ?? "-" },
            {
              title: "差值",
              dataIndex: "diff",
              key: "diff",
              render: (v: number | null) =>
                v === null ? (
                  "-"
                ) : (
                  <Tag color={v >= 0 ? "green" : "volcano"}>
                    {v >= 0 ? "+" : ""}
                    {v.toFixed(1)}
                  </Tag>
                ),
            },
          ]}
        />
      </Card>

      <Card title="位置网格 · 对枪优劣势区（3×3，样本 ≥3 场交战才贴标签）">
        {posRows.length === 0 && !report.isLoading ? (
          <Text type="secondary">暂无定位数据——对最近的对局执行「分析demo」后自动生成（新解析才携带位置网格）</Text>
        ) : (
          <Table
            rowKey="key"
            size="small"
            loading={report.isLoading}
            dataSource={posRows}
            pagination={false}
            columns={[
              { title: "区域", dataIndex: "zone", key: "zone" },
              { title: "击杀", dataIndex: "kills", key: "kills" },
              { title: "死亡", dataIndex: "deaths", key: "deaths" },
              { title: "对枪胜率", dataIndex: "win_rate", key: "win_rate", render: (v: number | null) => (v === null ? "-" : `${(v * 100).toFixed(1)}%`) },
              { title: "标签", dataIndex: "label", key: "label", render: (l: string) => <Tag color={LABEL_COLOR[l] ?? "default"}>{l}</Tag> },
            ]}
          />
        )}
      </Card>

      <Card title="具体点位 · 对枪优劣势（按 nav 地名，样本 ≥3 才贴标签）">
        {(report.data?.callouts ?? []).length === 0 && !report.isLoading ? (
          <Text type="secondary">暂无点位数据——对最近的对局重新「分析demo」后自动生成</Text>
        ) : (
          <Table
            rowKey="place"
            size="small"
            loading={report.isLoading}
            dataSource={report.data?.callouts ?? []}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: "点位", dataIndex: "place", key: "place", render: (p: string) => placeZh(p) },
              { title: "击杀", dataIndex: "kills", key: "kills" },
              { title: "死亡", dataIndex: "deaths", key: "deaths" },
              { title: "对枪胜率", dataIndex: "win_rate", key: "win_rate", render: (v: number | null) => (v === null ? "-" : `${(v * 100).toFixed(1)}%`) },
              { title: "标签", dataIndex: "label", key: "label", render: (l: string) => <Tag color={LABEL_COLOR[l] ?? "default"}>{l}</Tag> },
            ]}
          />
        )}
      </Card>
    </Space>
  );
}
