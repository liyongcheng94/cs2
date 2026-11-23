// 与后端契约对应的类型定义

export interface MatchSummary {
  id: number;
  match_id: string;
  map_name: string;
  score1: number;
  score2: number;
  win: boolean;
  draw?: boolean;
  map_en?: string;
  player_id?: string;
  mode: string;
  played_at: string | null;
  demo_status: string;
}

export interface FourDimAnalysisShape {
  match_id: string;
  deaths?: { events?: Record<string, unknown>[]; disadvantaged_rate?: number | null };
  economy?: { buy_decisions?: Record<string, unknown>[]; first_kill_conversion?: number | null };
  utility?: {
    throws?: Record<string, unknown>[];
    blind_median_s?: number | null;
    waste_rate?: number | null;
    enemy_blind_s?: number | null;
    team_blind_s?: number | null;
    usage?: { grenade_type: string; bought: number; thrown: number; waste_rate: number | null }[];
    spots?: { kind: string; x: number; y: number; start_tick?: number | null; end_tick?: number | null; side?: string | null }[];
  };
  duels?: { by_weapon_distance?: { distance: string; weapon: string; kills?: number; deaths?: number; win_rate?: number | null }[]; first_strike_win_rate?: number | null; mirror_win_rate?: number | null };
  highlights?: {
    round_no: number | null; start_tick?: number | null; end_tick?: number | null;
    kills: number; headshots: number; score?: number | null; label?: string | null;
    round_won?: boolean | null; clutch?: boolean | null;
  }[];
  meta?: { parser?: string; cost_s?: number | null; peak_mem_mb?: number | null };
}

export interface MatchDetail {
  match: MatchSummary;
  stat: Record<string, unknown> | null;
  analysis: FourDimAnalysisShape | null;
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
