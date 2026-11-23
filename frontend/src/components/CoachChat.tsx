// AI 教练对话：多轮 + 历史持久化（后端存 SQLite），上下文自动注入画像/最近复盘
// v2（2026-11-23）：图片上传（OCR 间接路线——AI 以文字看图）+ 气泡内图片展示 + 会话历史查看
import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Card, Image, Input, List, message, Popconfirm, Space, Upload, Typography } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { apiDelete, apiGet, apiPost, apiUpload } from "../api/client";

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
  image_ids?: number[];
}
interface ChatImageItem {
  id: number;
  url: string;
  filename: string;
  ocr_text: string;
}

export function CoachChat() {
  const qc = useQueryClient();
  const [activeId, setActiveId] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [pendingImages, setPendingImages] = useState<ChatImageItem[]>([]);
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
  const [streaming, setStreaming] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (files: File[]) => apiUpload<ChatImageItem[]>("/chat/images", files),
    onSuccess: (imgs) => {
      setPendingImages((prev) => [...prev, ...imgs]);
      const withText = imgs.filter((i) => i.ocr_text).length;
      message.success(`已上传 ${imgs.length} 张（${withText} 张识别出文本）`);
    },
    onError: (e: Error) => message.error(`上传失败：${e.message}`),
  });

  const send = useMutation({
    mutationFn: async (content: string) => {
      const resp = await fetch(`${import.meta.env.BASE_URL}api/chat/stream`.replace("//api", "/api"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: activeId,
          content,
          image_ids: pendingImages.map((p) => p.id),
        }),
      });
      if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let err: string | null = null;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() ?? "";
        for (const line of parts) {
          if (!line.startsWith("data: ")) continue;
          const e = JSON.parse(line.slice(6));
          if (e.delta) setStreaming((s) => (s ?? "") + e.delta);
          if (e.error) err = e.error;
        }
      }
      if (err) throw new Error(err);
    },
    onSuccess: () => {
      setStreaming(null);
      setInput("");
      setPendingImages([]);
      qc.invalidateQueries({ queryKey: ["chat-messages", activeId ?? undefined] });
      qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    },
    onError: () => setStreaming(null),
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
  }, [messages.data?.length, send.isPending, pendingImages.length]);

  const onSend = () => {
    if (!input.trim() && pendingImages.length === 0) return;
    send.mutate(input.trim() || "看图分析");
  };

  const history: MessageItem[] = (messages.data ?? []) as MessageItem[];

  // 气泡内图片渲染：image_ids → 缩略图（Image.PreviewGroup 大图预览）
  const renderImages = (m: MessageItem) =>
    m.image_ids && m.image_ids.length ? (
      <Image.PreviewGroup>
        <Space size={4} wrap style={{ marginBottom: 4 }}>
          {m.image_ids.map((id) => (
            <Image
              key={id}
              src={`${import.meta.env.BASE_URL}api/chat/uploads/${id}/img`.replace("//api", "/api")}
              width={64}
              height={64}
              style={{ objectFit: "cover", borderRadius: 4 }}
              fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
            />
          ))}
        </Space>
      </Image.PreviewGroup>
    ) : null;

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
          <Text type="secondary">新建或选择一个会话开始与教练对话（上下文自动注入你的画像与最近复盘；支持上传截图，教练通过 OCR 读图）</Text>
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
                  {renderImages(m)}
                  <div>{m.content}</div>
                </div>
              </List.Item>
            )}
          />
        )}
        {streaming !== null ? (
          <List.Item style={{ justifyContent: "flex-start" }}>
            <div style={{ maxWidth: "80%", background: "#262626", padding: "8px 12px", borderRadius: 8, whiteSpace: "pre-wrap" }}>
              <Text style={{ fontSize: 11, color: "#888" }}>教练</Text>
              <div>{streaming || "…"}</div>
            </div>
          </List.Item>
        ) : null}
        {send.isPending && streaming === null ? <Text type="secondary">教练思考中…</Text> : null}
        <div ref={bottomRef} />
        {pendingImages.length ? (
          <Space size={4} wrap style={{ marginTop: 8 }} data-testid="pending-images">
            {pendingImages.map((p) => (
              <span key={p.id} style={{ position: "relative", display: "inline-block" }}>
                <Image src={p.url} alt={p.filename} width={56} height={56} style={{ objectFit: "cover", borderRadius: 4 }} />
                <Button
                  size="small"
                  type="text"
                  danger
                  style={{ position: "absolute", top: -6, right: -6, height: 16, width: 16, minWidth: 16, padding: 0 }}
                  aria-label={`移除贴图${p.id}`}
                  onClick={() => setPendingImages((prev) => prev.filter((x) => x.id !== p.id))}
                >
                  ×
                </Button>
              </span>
            ))}
          </Space>
        ) : null}
        <Space.Compact style={{ width: "100%", marginTop: 12 }}>
          <Upload
            accept="image/jpeg,image/png,image/webp"
            showUploadList={false}
            beforeUpload={(f) => {
              upload.mutate([f]);
              return false;
            }}
            disabled={activeId == null}
          >
            <Button icon={<PlusOutlined />} disabled={activeId == null} aria-label="上传对话图片" />
          </Upload>
          <Input
            placeholder="问教练（如：这周道具优先练什么；可附截图）"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPressEnter={onSend}
            disabled={activeId == null}
          />
          <Button
            type="primary"
            loading={send.isPending}
            onClick={onSend}
            disabled={activeId == null}
          >
            发送
          </Button>
        </Space.Compact>
      </Card>
    </Space>
  );
}
