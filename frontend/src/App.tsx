import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Layout,
  message,
  Row,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { apiGet, apiPost, apiPut } from "./api/client";
import { LongTermTrends } from "./components/LongTermTrends";
import { CoachChat } from "./components/CoachChat";
import { SeasonTrends } from "./components/SeasonTrends";
import { WanmeiLogin } from "./components/WanmeiLogin";
import { MatchDetailModal } from "./components/MatchDetailModal";
import { LearnPage } from "./components/LearnPage";
import type { MatchDetail, MatchSummary, Profile, TaskItem } from "./types";

const { Header, Content } = Layout;
const { Title } = Typography;

// ---------- 总览 ----------
function OverviewPage() {
  const profileQuery = useQuery({
    queryKey: ["profile"],
    queryFn: () => apiGet<Profile>("/profile"),
  });
  const season = useQuery({
    queryKey: ["season-stats"],
    queryFn: () => apiGet<{ season_id: string; data: Record<string, unknown>; updated_at: string }>("/matches/stats/season"),
    retry: false,
  });
  const p = profileQuery.data;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title="玩家基线画像（来自 DeepSeek 对话还原）"
      >
        {p ? (
          <Row gutter={24}>
            <Col span={6}>
              <Statistic title="eDPI" value={p.data.edpi ?? "-"} />
            </Col>
            <Col span={6}>
              <Statistic title="主玩地图" value={p.data.main_map ?? "-"} />
            </Col>
            <Col span={6}>
              <Statistic title="爆头率" value={((p.data.hs_rate ?? 0) * 100).toFixed(1) + "%"} />
            </Col>
            <Col span={6}>
              <Statistic title="手枪局 WE" value={p.data.pistol_we ?? "-"} />
            </Col>
            <Col span={24} style={{ marginTop: 16 }}>
              <Space wrap>
                {Object.entries(p.data.grades ?? {}).map(([k, v]) => (
                  <Tag key={k} color={v === "A" ? "green" : v === "B" ? "blue" : "volcano"}>
                    {k} {v}
                  </Tag>
                ))}
              </Space>
            </Col>
          </Row>
        ) : (
          "加载中…"
        )}
      </Card>

      {season.data ? (
        <SeasonTrends data={season.data.data as Record<string, any>} />
      ) : (
        <Card size="small">
          <span style={{ color: "#999", fontSize: 12 }}>
            赛季统计尚未同步——点上方任意一次「同步」后自动生成趋势图
          </span>
        </Card>
      )}
    </Space>
  );
}

// ---------- 对局 ----------
function MatchesPage() {
  const [detailId, setDetailId] = useState<number | null>(null);
  const qc = useQueryClient();
  const runTask = useMutation({
    mutationFn: async (req: { type: string; matchId?: string }) => {
      const t = await apiPost<{ id: number }>("/tasks", req.matchId ? { type: req.type, payload: { match_id: req.matchId } } : { type: req.type });
      return apiPost<{ status: string; error: string | null; result: Record<string, unknown> | null }>(`/tasks/${t.id}/run`);
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["matches"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      if (res.status === "NEED_AUTH") {
        message.error("完美平台 token 失效（已熔断），请到设置页重新短信登录");
      } else if (res.status !== "success") {
        message.error(`失败：${res.error ?? res.status}`);
      } else {
        message.success("完成");
      }
    },
  });
  const sync = () => runTask.mutate({ type: "wanmei_sync" });
  const analyze = (matchId: string) => runTask.mutate({ type: "demo_analyze", matchId });
  const matches = useQuery({
    queryKey: ["matches"],
    queryFn: () => apiGet<MatchSummary[]>("/matches"),
  });
  const detail = useQuery({
    queryKey: ["match", detailId],
    queryFn: () => apiGet<MatchDetail>(`/matches/${detailId}`),
    enabled: detailId !== null,
  });

  const columns = [
    { title: "地图", dataIndex: "map_name", key: "map_name" },
    {
      title: "比分",
      key: "score",
      render: (_: unknown, r: MatchSummary) => `${r.score1} : ${r.score2}`,
    },
    {
      title: "胜负",
      key: "result",
      render: (_: unknown, r: MatchSummary & { draw?: boolean }) =>
        r.draw ? <Tag color="orange">平</Tag> : r.win ? <Tag color="green">胜</Tag> : <Tag color="red">败</Tag>,
    },
    { title: "模式", dataIndex: "mode", key: "mode" },
    {
      title: "demo",
      dataIndex: "demo_status",
      key: "demo_status",
      render: (s: string) => <Tag>{s}</Tag>,
    },
    {
      title: "时间",
      dataIndex: "played_at",
      key: "played_at",
      render: (t: string | null) => (t ? new Date(t + "Z").toLocaleString() : "-"),
    },
    {
      title: "操作",
      key: "action",
      render: (_: unknown, r: MatchSummary) => (
        <Space>
          <a onClick={() => setDetailId(r.id)}>详情</a>
          <a onClick={() => analyze(r.match_id)}>分析demo</a>
        </Space>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Space>
        <Button
          type="primary"
          loading={runTask.isPending}
          onClick={sync}
        >
          从完美平台同步
        </Button>
        <span style={{ color: "#999", fontSize: 12 }}>
          拉 3 页 / 次，限速 2s；token 失效会熔断提示重登
        </span>
      </Space>
      <Table
        rowKey="id"
        loading={matches.isLoading}
        dataSource={matches.data ?? []}
        columns={columns}
        pagination={{ pageSize: 15 }}
      />
      <MatchDetailModal open={detailId !== null} detail={detail.data ?? null} onClose={() => setDetailId(null)} />

    </Space>
  );
}

// ---------- 任务 ----------
function TasksPage() {
  // 评审约定：React Query 5s 轮询 tasks，success 自动刷新其他列表
  const qc = useQueryClient();
  const tasks = useQuery({
    queryKey: ["tasks"],
    queryFn: () => apiGet<TaskItem[]>("/tasks"),
    refetchInterval: 5000,
  });
  const runTask = useMutation({
    mutationFn: (id: number) => apiPost(`/tasks/${id}/run`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["matches"] });
    },
  });

  const columns = [
    { title: "ID", dataIndex: "id", key: "id", width: 60 },
    { title: "类型", dataIndex: "type", key: "type" },
    {
      title: "优先级",
      dataIndex: "priority",
      key: "priority",
      width: 80,
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (s: string) => (
        <Tag
          color={
            s === "success"
              ? "green"
              : s === "failed"
                ? "red"
                : s === "NEED_AUTH"
                  ? "volcano"
                  : s === "running"
                    ? "blue"
                    : "default"
          }
        >
          {s}
        </Tag>
      ),
    },
    {
      title: "错误",
      dataIndex: "error",
      key: "error",
      ellipsis: true,
    },
    {
      title: "操作",
      key: "action",
      render: (_: unknown, r: TaskItem) => (
        <a onClick={() => runTask.mutate(r.id)}>执行</a>
      ),
    },
  ];

  const needAuth = (tasks.data ?? []).some((t) => t.status === "NEED_AUTH");

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      {needAuth ? (
        <Alert
          type="error"
          showIcon
          message="有任务 NEED_AUTH：完美平台 token 失效（已熔断，不会自动重试）"
          description="请到「设置」页粘贴新的 access_token。"
        />
      ) : null}
      <Table
        rowKey="id"
        loading={tasks.isLoading}
        dataSource={tasks.data ?? []}
        columns={columns}
        pagination={{ pageSize: 15 }}
      />
    </Space>
  );
}

// ---------- 设置 ----------
function SettingsPage() {
  const [form] = Form.useForm();
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: () => apiGet<Record<string, string>>("/settings"),
  });
  const save = useMutation({
    mutationFn: (values: Record<string, string>) => apiPut("/settings", values),
    onSuccess: () => message.success("已保存（凭证已加密落库）"),
  });

  if (!settings.isLoading) {
    form.setFieldsValue(settings.data ?? {});
  }

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card title="凭证与连接" style={{ maxWidth: 640 }}>
        <Form form={form} layout="vertical" onFinish={(v) => save.mutate(v)}>
          <Form.Item
            name="mv.base_url"
            label="MindVault 地址"
            tooltip="dev 模式默认 http://127.0.0.1:8001；走公网隧道时改隧道 URL"
          >
            <Input placeholder="http://127.0.0.1:8001" />
          </Form.Item>
          <Form.Item
            name="mindvault.password"
            label="MindVault 访问密码"
            tooltip="未设密码可留空；Fernet 加密落库"
          >
            <Input.Password placeholder="留空表示无密码" />
          </Form.Item>
          <Form.Item
            name="bili.sessdata"
            label="B站 SESSDATA"
            tooltip="登录 B 站后从浏览器 cookie 复制；用于字幕抓取"
          >
            <Input.Password placeholder="粘贴即存" />
          </Form.Item>
          <Form.Item
            name="ai.api_key"
            label="AI API Key（DeepSeek）"
            tooltip="复盘总结/道具卡抽取用；MindVault 设置页同一 Key 可复用"
          >
            <Input.Password placeholder="sk-... 粘贴即存" />
          </Form.Item>
          <Form.Item
            name="moments.dir"
            label="完美时刻导出目录"
            tooltip="完美客户端导出时刻 mp4 的文件夹；保存后点「任务」页执行 moments_sync 推送"
          >
            <Input placeholder="例如 D:\PerfectWorld\moments" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={save.isPending}>
            保存
          </Button>
        </Form>
      </Card>
      <WanmeiLogin />
    </Space>
  );
}

// ---------- B站学习 ----------
// LearnPage 已抽到 components/LearnPage.tsx（2026-11-23 L1+L2 重设计）

// ---------- App ----------
export default function App() {
  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Header>
        <Title level={3} style={{ color: "#fff", lineHeight: "48px", margin: 0 }}>
          CS2HQ · 专属 CS2 提升平台
        </Title>
      </Header>
      <Content style={{ padding: 24 }}>
        <Tabs
          items={[
            { key: "overview", label: "总览", children: <OverviewPage /> },
            { key: "matches", label: "对局", children: <MatchesPage /> },
            { key: "trends", label: "趋势", children: <LongTermTrends /> },
            { key: "learn", label: "学道具", children: <LearnPage /> },
            { key: "chat", label: "AI 教练", children: <CoachChat /> },
            { key: "tasks", label: "任务", children: <TasksPage /> },
            { key: "settings", label: "设置", children: <SettingsPage /> },
          ]}
        />
      </Content>
    </Layout>
  );
}
