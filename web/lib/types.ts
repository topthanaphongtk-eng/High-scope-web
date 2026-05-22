export type Mode = "mode1" | "mode2";

export interface CaptureFile {
  slot: string;
  fused_path: string;
  fused_name: string;
  size_bytes: number | null;
  sha256: string | null;
  image_rel?: string | null;
}

export interface Capture {
  capture_id: string;
  confirmed_at: string;
  lot_id: string;
  bonding_number: string | null;
  lot_location: string | null;
  mpc: string | null;
  package: string | null;
  qs: string | null;
  operator_badge: string;
  hostname: string | null;
  app_version: string | null;
  mode: string;
  raw_lot_info: Record<string, unknown> | string | null;
  files: CaptureFile[];
}

export interface LotSummary {
  lot_id: string;
  last_confirmed_at: string;
  capture_count: number;
}

export interface CaptureFilter {
  since?: Date | null;
  until?: Date | null;
  bonding_number?: string | null;
  lot_location?: string | null;
  lot_id?: string | null;
  mode?: Mode | null;
  limit?: number;
  offset?: number;
}

export interface BucketCounts {
  today: number;
  week: number;
  month: number;
  total: number;
}
