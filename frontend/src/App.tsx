import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Drawer,
  Form,
  Input,
  Layout,
  message,
  Modal,
  Row,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { apiGet, apiPost, apiPut } from "./api/client";
import { WanmeiLogin } from "./components/WanmeiLogin";
import type { MatchDetail, MatchSummary, MockFlowResult, Profile, TaskItem } from "./types";

const { Header, Content } = Layout;
const { Title } = Typography;

// ---------- 总览 ----------
function OverviewPage() {
  const qc = useQueryClient();
  const [mockOpen, setMockOpen] = useState(false);
  const profileQuery = useQuery({
    queryKey: ["profile"],
    queryFn: () => apiGet<Profile>("/profile"),
  });
  const mockFlow = useMutation({
    mutationFn: () => apiPost<MockFlowResult>("/test/mock-flow"),
    onSuccess: () => {
      setMockOpen(true);
      qc.invalidateQueries({ queryKey: ["matches"] });
    },
  });
  const p = profileQuery.data;

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card
        title="玩家基线画像（来自 DeepSeek 对话还原）"
        extra={
          <Button
            type="primary"
            loading={mockFlow.isPending}
            onClick={() => mockFlow.mutate()}
          >
            跑一次 Mock 全链路
          </Button>
        }
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

      <Modal
        title="Mock 全链路结果"
        open={mockOpen}
        onCancel={() => setMockOpen(false)}
        footer={null}
      >
        {mockFlow.data ? (
          <Descriptions column={1} size="small">
            <Descriptions.Item label="假对局">
              {mockFlow.data.match_id}
            </Descriptions.Item>
            <Descriptions.Item label="推送 MindVault">
              {mockFlow.data.pushed ? (
                <Tag color="green">成功 · {mockFlow.data.mv_uuid}</Tag>
              ) : (
                <Tag color="red">失败 · {mockFlow.data.reason}</Tag>
              )}
            </Descriptions.Item>
            <Descriptions.Item label="目标主题">
              {mockFlow.data.topic}
            </Descriptions.Item>
          </Descriptions>
        ) : null}
      </Modal>
    </Space>
  );
}

// ---------- 对局 ----------
function MatchesPage() {
  const [detailId, setDetailId] = useState<number | null>(null);
  const qc = useQueryClient();
  const sync = useMutation({
    mutationFn: async () => {
      const t = await apiPost<{ id: number }>("/tasks", { type: "wanmei_sync" });
      return apiPost<{ status: string; error: string | null }>(`/tasks/${t.id}/run`);
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["matches"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      if (res.status === "NEED_AUTH") {
        message.error("完美平台 token 失效（已熔断），请到设置页重新短信登录");
      } else if (res.status !== "success") {
        message.error(`同步失败：${res.error ?? res.status}`);
      } else {
        message.success("同步完成");
      }
    },
  });
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
      dataIndex: "win",
      key: "win",
      render: (w: boolean) => (w ? <Tag color="green">胜</Tag> : <Tag color="red">负</Tag>),
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
        <a onClick={() => setDetailId(r.id)}>详情</a>
      ),
    },
  ];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Space>
        <Button
          type="primary"
          loading={sync.isPending}
          onClick={() => sync.mutate()}
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
      <Drawer
        title="对局详情"
        width={640}
        open={detailId !== null}
        onClose={() => setDetailId(null)}
      >
        {detail.data ? (
          <Space direction="vertical" style={{ width: "100%" }}>
            {detail.data.report ? (
              <Alert
                type={detail.data.report.pushed ? "success" : "warning"}
                message={`复盘：${detail.data.report.title}`}
                description={detail.data.report.pushed ? "已推送 MindVault" : "未推送"}
              />
            ) : null}
            <pre style={{ fontSize: 12, whiteSpace: "pre-wrap" }}>
              {JSON.stringify(detail.data.analysis, null, 2)}
            </pre>
          </Space>
        ) : (
          "加载中…"
        )}
      </Drawer>
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
          <Button type="primary" htmlType="submit" loading={save.isPending}>
            保存
          </Button>
        </Form>
      </Card>
      <WanmeiLogin />
    </Space>
  );
}

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
            { key: "tasks", label: "任务", children: <TasksPage /> },
            { key: "settings", label: "设置", children: <SettingsPage /> },
          ]}
        />
      </Content>
    </Layout>
  );
}
