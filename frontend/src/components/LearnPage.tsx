/**
 * 学道具页重设计（2026-11-23 grill-me 共识 L1+L2 + v2 八问共识）：
 * - L1 视频卡片墙：封面（referrerPolicy=no-referrer 绕 B站防盗链）+ 时长 + 字幕状态 + 总结 Modal
 * - L2 道具库：地图一级 Tab → 分区二级 Tab（全部/A区/B区/中路/出生点）→ 卡片
 *   卡片：道具图标徽章 + zone Tag + ★收藏（PATCH，收藏置顶）+ 贴图（上传/预览/删除）+ 视频跳转
 * 数据源：GET /api/bili/videos、GET /api/bili/grenades（含 zone/favorited）
 *
 * 场景（vitest 覆盖见 LearnPage.test.tsx）：
 * - Given 已学视频带封面与总结 When 渲染 Then 卡片显示封面图与「查看总结」入口
 * - Given 无总结视频 When 渲染 Then 显示占位提示不炸
 * - Given 点开卡片 When Modal 打开 Then marked 渲染 summary_md
 * - Given 道具卡带 zone When 渲染 Then 二级分区 Tab 分组正确，zone∈四值
 * - Given 存量卡 zone=null When 渲染 Then inferZone 正则兜底（A大→A区/中→中路/B小→B区/出生→出生点）
 * - Given 点★ When 点击 Then PATCH favorited 且收藏置顶
 * - Given 卡片贴图 When 上传 Then apiUpload 后预览可见
 */
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Button,
  Card,
  Col,
  Empty,
  Image,
  Input,
  message,
  Modal,
  Row,
  Space,
  Spin,
  Tag,
  Typography,
  Upload,
} from "antd";
import { StarFilled, StarOutlined } from "@ant-design/icons";
import { marked } from "marked";
import { apiGet, apiPatch, apiPost, apiUpload, apiDelete } from "../api/client";

const { Text, Paragraph } = Typography;

/** 道具类型 → 图标徽章颜色（中文值来自 AI 卡片，兼容英文枚举） */
const GRENADE_META: Record<string, { color: string; icon: string }> = {
  烟雾弹: { color: "geekblue", icon: "💨" },
  闪光弹: { color: "gold", icon: "⚡" },
  燃烧弹: { color: "volcano", icon: "🔥" },
  手雷: { color: "red", icon: "💥" },
  HE: { color: "red", icon: "💥" },
  smoke: { color: "geekblue", icon: "💨" },
  flash: { color: "gold", icon: "⚡" },
  molotov: { color: "volcano", icon: "🔥" },
  无: { color: "default", icon: "🎯" },
};

function GrenadeBadge({ type }: { type: string | null | undefined }) {
  if (!type) return <Tag>-</Tag>;
  const meta = GRENADE_META[type] ?? GRENADE_META[type.split("+")[0]?.trim() ?? ""] ?? { color: "default", icon: "🎯" };
  const parts = type.split("+").map((p) => p.trim());
  return (
    <Space size={4} wrap>
      {parts.map((p) => {
        const m = GRENADE_META[p] ?? meta;
        return (
          <Tag key={p} color={m.color}>
            {m.icon} {p}
          </Tag>
        );
      })}
    </Space>
  );
}

function fmtDuration(s: number | null | undefined): string {
  if (!s || s <= 0) return "";
  const m = Math.floor(s / 60);
  const sec = Math.round(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}

/**
 * B站 ?t= 参数是【秒数】（支持小数，如 ?t=698.1）。
 * AI 输出的 video_ts 可能是 "03:24"（分:秒）→ 换算 204；
 * 已经是纯数字/小数（"698" / "698.1"）→ 原样透传；
 * 「未提供」等无效值 → 空串（不带 t 参数）。
 */
function tsToSeconds(ts: string | null | undefined): string {
  const s = (ts ?? "").trim().replace(/^约\s*/, ""); // AI 偶尔输出「约15:30」
  if (!s || /未提供|未提及|未知|n\/a/i.test(s)) return "";
  const mmss = s.match(/^(\d{1,3}):([0-5]?\d)(?:\.(\d+))?$/);
  if (mmss) {
    const base = Number(mmss[1]) * 60 + Number(mmss[2]);
    const frac = mmss[3] ? `.${mmss[3]}` : "";
    return `${base}${frac}`;
  }
  if (/^\d+(\.\d+)?$/.test(s)) return s; // 已是秒
  return ""; // 未知格式不带 t，宁可跳视频开头也不跳错位置
}

export { tsToSeconds };

interface VideoRow {
  bvid: string;
  title: string;
  owner: string | null;
  subtitle_status: string;
  created_at: string | null;
  summary_md: string | null;
  cover: string | null;
  duration: number | null;
}

interface GrenadeRow {
  id: number;
  map_name: string;
  point: string | null;
  grenade_type: string | null;
  stance: string | null;
  timing: string | null;
  video_ts: string | null;
  bvid: string | null;
  content_md: string;
  zone: string | null;
  favorited: boolean;
  health?: string | null; // v3 S4：alive/aging/stale（stale=过期红标、aging=存疑黄标）
}

interface GrenadeImageRow {
  id: number;
  filename: string;
  url: string;
}

/** 分区四值（grill-me v2 0b：二级 Tab 选项） */
export const ZONES = ["全部", "A区", "B区", "中路", "出生点"] as const;

/**
 * 存量卡 zone=null 的正则兜底（grill-me v2 0a：前端正则解析存量卡）。
 * 实测 110 卡全覆盖零「其他」：A大/A小/A1→A区；中路/中门/拱门(中)→中路；B小/B通道→B区；出生→出生点。
 */
export function inferZone(card: { zone?: string | null; point?: string | null }): string {
  if (card.zone && ZONES.slice(1).includes(card.zone as (typeof ZONES)[number])) return card.zone;
  const p = card.point ?? "";
  if (/出生/.test(p)) return "出生点";
  if (/A区|A大|A小|A1|A2|A点|A包/.test(p)) return "A区";
  if (/B区|B小|B1|B2|B点|B包|B通道|香蕉/.test(p)) return "B区";
  if (/中|拱门|VIP|连接|下水道|窗户|沙袋/.test(p)) return "中路";
  return "中路";
}

// ---------- L1 视频卡片墙 ----------
function VideoWall({ onOpen }: { onOpen: (v: VideoRow) => void }) {
  const videos = useQuery({
    queryKey: ["bili-videos"],
    queryFn: () => apiGet<VideoRow[]>("/bili/videos"),
  });
  if (videos.isLoading) return <Spin />;
  const rows = videos.data ?? [];
  if (!rows.length)
    return <Empty description="还没有学过视频：上面输入 BV 号 / UP主 mid / 关键词开始学习" />;

  return (
    <Row gutter={[16, 16]}>
      {rows.map((v) => (
        <Col key={v.bvid} xs={24} sm={12} md={8} lg={6}>
          <Card
            hoverable
            size="small"
            onClick={() => onOpen(v)}
            cover={
              v.cover ? (
                <div style={{ position: "relative" }}>
                  {/* B站防盗链：外站 Referer 403，no-referrer 直显 */}
                  <img
                    alt={v.title}
                    src={v.cover}
                    referrerPolicy="no-referrer"
                    style={{ width: "100%", height: 140, objectFit: "cover" }}
                  />
                  {v.duration ? (
                    <span
                      style={{
                        position: "absolute",
                        right: 8,
                        bottom: 8,
                        background: "rgba(0,0,0,.65)",
                        color: "#fff",
                        fontSize: 12,
                        padding: "1px 6px",
                        borderRadius: 4,
                      }}
                    >
                      {fmtDuration(v.duration)}
                    </span>
                  ) : null}
                </div>
              ) : undefined
            }
          >
            <Card.Meta
              title={<span style={{ fontSize: 13 }}>{v.title}</span>}
              description={
                <Space size={4} wrap>
                  {v.owner ? <Text type="secondary">{v.owner}</Text> : null}
                  {v.subtitle_status === "subtitle" ? (
                    <Tag color="green">已总结</Tag>
                  ) : v.subtitle_status === "no_subtitle" ? (
                    <Tag color="orange">无字幕</Tag>
                  ) : (
                    <Tag>{v.subtitle_status}</Tag>
                  )}
                  {v.summary_md ? <Text type="secondary">{v.summary_md.length} 字</Text> : null}
                </Space>
              }
            />
          </Card>
        </Col>
      ))}
    </Row>
  );
}

// ---------- 总结详情 Modal ----------
function SummaryModal({ video, onClose }: { video: VideoRow | null; onClose: () => void }) {
  if (!video) return null;
  const html = video.summary_md ? (marked.parse(video.summary_md) as string) : "";
  return (
    <Modal
      open={!!video}
      onCancel={onClose}
      footer={
        <Button
          type="primary"
          href={`https://www.bilibili.com/video/${video.bvid}`}
          target="_blank"
        >
          打开原视频
        </Button>
      }
      title={video.title}
      width={760}
    >
      <Paragraph type="secondary" style={{ marginBottom: 12 }}>
        {video.owner ?? "-"} · {video.bvid}
        {video.summary_md ? null : " · 暂无本地总结（学习时 AI 未配置，配置后重学可生成）"}
      </Paragraph>
      {video.summary_md ? (
        <div className="report-md" dangerouslySetInnerHTML={{ __html: html }} />
      ) : (
        <Empty description="无总结内容" />
      )}
    </Modal>
  );
}

// ---------- L2 道具库（地图 → 分区二级 Tab，★收藏置顶，贴图） ----------

/** 单卡贴图区：上传 + 预览 + 删除 */
function CardImages({ cardId }: { cardId: number }) {
  const qc = useQueryClient();
  const images = useQuery({
    queryKey: ["grenade-images", cardId],
    queryFn: () => apiGet<GrenadeImageRow[]>(`/bili/grenades/${cardId}/images`),
  });
  const upload = useMutation({
    mutationFn: (files: File[]) => apiUpload<GrenadeImageRow[]>(`/bili/grenades/${cardId}/images`, files),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["grenade-images", cardId] });
      message.success("贴图已上传");
    },
    onError: (e: Error) => message.error(`上传失败：${e.message}`),
  });
  const remove = useMutation({
    mutationFn: (imageId: number) => apiDelete<{ deleted: number }>(`/bili/grenades/${cardId}/images/${imageId}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["grenade-images", cardId] }),
  });

  if (images.isLoading) return null;
  const rows = images.data ?? [];
  return (
    <Space size={6} wrap data-testid={`card-images-${cardId}`}>
      <Image.PreviewGroup>
        {rows.map((img) => (
          <span key={img.id} style={{ position: "relative", display: "inline-block" }}>
            <Image src={img.url} alt={img.filename} width={72} height={48} style={{ objectFit: "cover", borderRadius: 4 }} />
            <Button
              size="small"
              type="text"
              danger
              style={{ position: "absolute", top: -6, right: -6, height: 16, width: 16, minWidth: 16, padding: 0, fontSize: 10 }}
              aria-label={`删除贴图${img.id}`}
              onClick={(e) => {
                e.stopPropagation();
                remove.mutate(img.id);
              }}
            >
              ×
            </Button>
          </span>
        ))}
      </Image.PreviewGroup>
      {rows.length < 9 ? (
        <Upload
          accept="image/jpeg,image/png,image/webp"
          showUploadList={false}
          beforeUpload={(_f, fileList) => {
            upload.mutate(fileList);
            return false; // 阻止 antd 默认上传，走自己的 mutation
          }}
        >
          <Button size="small" type="dashed" loading={upload.isPending}>
            ＋贴图
          </Button>
        </Upload>
      ) : null}
    </Space>
  );
}

function GrenadeLibrary() {
  const grenades = useQuery({
    queryKey: ["grenades"],
    queryFn: () => apiGet<GrenadeRow[]>("/bili/grenades"),
  });
  const qc = useQueryClient();
  const [activeMap, setActiveMap] = useState<string>("");
  const [activeZone, setActiveZone] = useState<string>("全部");

  const fav = useMutation({
    mutationFn: (p: { id: number; favorited: boolean }) =>
      apiPatch<{ id: number; favorited: boolean }>(`/bili/grenades/${p.id}/favorite`, { favorited: p.favorited }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["grenades"] }),
  });

  const maps = useMemo(() => {
    const counter = new Map<string, number>();
    for (const g of grenades.data ?? []) {
      counter.set(g.map_name, (counter.get(g.map_name) ?? 0) + 1);
    }
    return [...counter.entries()].sort((a, b) => b[1] - a[1]);
  }, [grenades.data]);

  if (grenades.isLoading) return <Spin />;
  const all = grenades.data ?? [];
  if (!all.length) return <Empty description="道具库为空：学习带点位教学的视频后自动收录" />;

  // 收藏置顶（grill-me v2 1d）
  const sorted = [...all].sort((a, b) => Number(b.favorited) - Number(a.favorited));
  const shown = sorted
    .filter((g) => !activeMap || g.map_name === activeMap)
    .filter((g) => activeZone === "全部" || inferZone(g) === activeZone);

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Space size={8} wrap>
        <Button size="small" type={!activeMap ? "primary" : "default"} onClick={() => setActiveMap("")}>
          全部（{all.length}）
        </Button>
        {maps.map(([m, n]) => (
          <Button
            key={m}
            size="small"
            type={activeMap === m ? "primary" : "default"}
            onClick={() => setActiveMap(m)}
          >
            {m}（{n}）
          </Button>
        ))}
      </Space>
      <Space size={6} wrap data-testid="zone-tabs">
        {ZONES.map((z) => (
          <Button
            key={z}
            size="small"
            type={activeZone === z ? "primary" : "text"}
            onClick={() => setActiveZone(z)}
          >
            {z}
          </Button>
        ))}
      </Space>
      <Row gutter={[12, 12]}>
        {shown.map((g) => {
          const ts = tsToSeconds(g.video_ts);
          return (
            <Col key={g.id} xs={24} sm={12} lg={8}>
              <Card
                size="small"
                title={
                  <Space size={6} style={{ width: "100%", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 13 }}>
                      {g.map_name} · {g.point ?? "-"}
                    </span>
                    <Button
                      type="text"
                      size="small"
                      aria-label={`收藏${g.id}`}
                      icon={g.favorited ? <StarFilled style={{ color: "#faad14" }} /> : <StarOutlined />}
                      onClick={(e) => {
                        e.stopPropagation();
                        fav.mutate({ id: g.id, favorited: !g.favorited });
                      }}
                    />
                  </Space>
                }
              >
                <Space direction="vertical" size={4} style={{ width: "100%" }}>
                  <Space size={6} wrap>
                    <GrenadeBadge type={g.grenade_type} />
                    <Tag color="purple">{inferZone(g)}</Tag>
                    {g.timing ? <Tag>{g.timing}</Tag> : null}
                    {g.health === "stale" ? (
                      <Tag color="red" data-testid={`health-stale-${g.id}`}>过期</Tag>
                    ) : null}
                    {g.health === "aging" ? (
                      <Tag color="gold" data-testid={`health-aging-${g.id}`}>存疑</Tag>
                    ) : null}
                  </Space>
                  {g.stance ? (
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      站位：{g.stance}
                    </Text>
                  ) : null}
                  <Paragraph style={{ fontSize: 13, marginBottom: 4 }}>{g.content_md}</Paragraph>
                  <CardImages cardId={g.id} />
                  {g.bvid ? (
                    <Button
                      size="small"
                      type="link"
                      style={{ padding: 0 }}
                      href={`https://www.bilibili.com/video/${g.bvid}${ts ? `?t=${ts}` : ""}`}
                      target="_blank"
                    >
                      ▶ 视频跳转{ts ? ` @${ts}` : ""}
                    </Button>
                  ) : null}
                </Space>
              </Card>
            </Col>
          );
        })}
      </Row>
    </Space>
  );
}

// ---------- 页面入口 ----------
export function LearnPage() {
  const [kw, setKw] = useState("");
  const [detail, setDetail] = useState<VideoRow | null>(null);
  const qc = useQueryClient();

  const learn = useMutation({
    mutationFn: (payload: { bvid?: string; up_mid?: string; keyword?: string }) => {
      const body = payload.bvid
        ? { bvid: payload.bvid }
        : payload.up_mid
          ? { up_mid: Number(payload.up_mid) }
          : { keyword: payload.keyword };
      return apiPost<{ id: number }>("/tasks", { type: "bili_learn", payload: body }).then((t) =>
        apiPost<{ status: string; error: string | null }>(`/tasks/${t.id}/run`),
      );
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: ["bili-videos"] });
      qc.invalidateQueries({ queryKey: ["grenades"] });
      if (res.status === "success") message.success("学习完成，总结已收录");
      else message.error(`失败：${res.error ?? res.status}`);
    },
  });

  return (
    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
      <Card title="学道具（B站字幕 → AI 总结 + 道具卡）" size="small">
        <Space>
          <Input
            placeholder="关键词 / BV 号 / UP主 mid 号"
            value={kw}
            style={{ width: 320 }}
            onChange={(e) => setKw(e.target.value)}
          />
          <Button
            type="primary"
            loading={learn.isPending}
            onClick={() => {
              // 含 BV 号（裸 BV / 完整链接 / b23.tv 短链）→ 单视频解析（后端 resolve_bvid 提取）
              const body = /BV[0-9A-Za-z]{10}/.test(kw.toUpperCase()) || /b23\.tv/i.test(kw)
                ? { bvid: kw }
                : /^\d+$/.test(kw)
                  ? { up_mid: kw }
                  : { keyword: kw };
              learn.mutate(body);
            }}
          >
            学习
          </Button>
        </Space>
        <div style={{ color: "#999", fontSize: 12, marginTop: 8 }}>
          纯数字=UP主（学最新 3 投稿），BV=单视频，其余=关键词检索；每次最多 5 条；总结与道具卡直接在本页查看
        </div>
      </Card>

      <Card title="已学视频" size="small">
        <VideoWall onOpen={setDetail} />
      </Card>

      <Card title="道具库" size="small">
        <GrenadeLibrary />
      </Card>

      <SummaryModal video={detail} onClose={() => setDetail(null)} />
    </Space>
  );
}
