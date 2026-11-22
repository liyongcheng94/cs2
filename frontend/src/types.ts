// 与后端契约对应的类型定义

export interface MatchSummary {
  id: number;
  match_id: string;
  map_name: string;
  score1: number;
  score2: number;
  win: boolean;
  mode: string;
  played_at: string | null;
  demo_status: string;
}

export interface MatchDetail {
  match: MatchSummary;
  stat: Record<string, unknown> | null;
  analysis: Record<string, unknown> | null;
  report: { title: string; pushed: boolean } | null;
}

export interface TaskItem {
  id: number;
  type: string;
  payload: Record<string, unknown>;
  status: "pending" | "running" | "success" | "failed" | "NEED_AUTH" | string;
  priority: number;
  progress: number;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string | null;
}

export interface Profile {
  key: string;
  data: {
    mouse?: string;
    dpi?: number;
    sens?: number;
    edpi?: number;
    main_map?: string;
    grades?: Record<string, string>;
    pistol_we?: number;
    t_rating?: number;
    ct_rating?: number;
    hs_rate?: number;
    source?: string;
  };
  updated_at: string;
}

export interface MockFlowResult {
  ok: boolean;
  pushed: boolean;
  mv_uuid?: string;
  topic?: string;
  match_id: string;
  reason?: string;
}
