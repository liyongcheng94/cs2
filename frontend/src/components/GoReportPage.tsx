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
  matches_analyzed: number;
}

const DIM_ORDER = ["瞄准能力", "补枪能力", "突破能力", "道具能力", "残局能力", "火力值"];

const LABEL_COLOR: Record<string, string> = { 优势: "green", 劣势: "red", 均衡: "default" };

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
    </Space>
  );
}
