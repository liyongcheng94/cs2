// AI 教练对话：多轮 + 历史持久化（后端存 SQLite），上下文自动注入画像/最近复盘
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Input, List, Popconfirm, Space, Typography } from "antd";
import { apiDelete, apiGet, apiPost } from "../api/client";

const { Text } = Typography;

interface SessionItem {
  id: number;
  title: string;
  created_at: string;
}
interface MessageItem {
  id: number;
  role: "user" | "assistant" | string;
  content: string;
}

export function CoachChat() {
  const qc = useQueryClient();
  const [activeId, setActiveId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const sessions = useQuery({
    queryKey: ["chat-sessions"],
    queryFn: () => apiGet<SessionItem[]>("/chat/sessions"),
  });
  const messages = useQuery({
    queryKey: ["chat-messages", activeId],
    queryFn: () => apiGet<MessageItem[]>(`/chat/sessions/${activeId}/messages`),
    enabled: activeId !== null,
  });
  const send = useMutation({
    mutationFn: (content: string) => apiPost<{ session_id: number; reply: string }>("/chat", { session_id: activeId, content }),
    onSuccess: (res) => {
      setActiveId(res.session_id);
      setInput("");
      qc.invalidateQueries({ queryKey: ["chat-messages", res.session_id] });
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
  });
  const del = useMutation({
    mutationFn: (id: number) => apiDelete(`/chat/sessions/${id}`),
    onSuccess: () => {
      setActiveId(null);
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
  });

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.data?.length, send.isPending]);

  const onSend = () => {
    if (!input.trim()) return;
    send.mutate(input.trim());
  };

  const history: MessageItem[] = (messages.data ?? []) as MessageItem[];

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card size="small" title="会话列表" style={{ maxWidth: 960 }}>
        <Space wrap>
          <Button
            type="primary"
            onClick={() => {
              apiPost<{ id: number }>("/chat/sessions").then((s) => {
                setActiveId(s.id);
                qc.invalidateQueries({ queryKey: ["chat-sessions"] });
              });
            }}
          >
            新对话
          </Button>
          {(sessions.data ?? []).map((s) => (
            <Space key={s.id}>
              <Button
                type={activeId === s.id ? "primary" : "default"}
                ghost={activeId === s.id}
                onClick={() => setActiveId(s.id)}
              >
                {s.title}
              </Button>
              <Popconfirm title="删除该会话？" onConfirm={() => del.mutate(s.id)}>
                <Button size="small" danger>×</Button>
              </Popconfirm>
            </Space>
          ))}
        </Space>
      </Card>

      <Card size="small" style={{ maxWidth: 960, minHeight: 320 }}>
        {activeId == null ? (
          <Text type="secondary">新建或选择一个会话开始与教练对话（上下文自动注入你的画像与最近复盘）</Text>
        ) : (
          <List
            dataSource={history}
            renderItem={(m) => (
              <List.Item style={{ justifyContent: m.role === "user" ? "flex-end" : "flex-start" }}>
                <div
                  style={{
                    maxWidth: "80%",
                    background: m.role === "user" ? "#1f3a5f" : "#262626",
                    padding: "8px 12px",
                    borderRadius: 8,
                    whiteSpace: "pre-wrap",
                  }}
                >
                  <Text style={{ fontSize: 11, color: "#888" }}>
                    {m.role === "user" ? "你" : "教练"}
                  </Text>
                  <div>{m.content}</div>
                </div>
              </List.Item>
            )}
          />
        )}
        {send.isPending ? <Text type="secondary">教练思考中…</Text> : null}
        <div ref={bottomRef} />
        <Space.Compact style={{ width: "100%", marginTop: 12 }}>
          <Input
            placeholder="问教练（如：这周道具优先练什么）"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={onSend}
            disabled={activeId == null}
          />
          <Button type="primary" loading={send.isPending} onClick={onSend} disabled={activeId == null}>
            发送
          </Button>
        </Space.Compact>
      </Card>
    </Space>
  );
}
