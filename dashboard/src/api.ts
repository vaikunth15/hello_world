// Read-only monitoring plus exactly two write actions: HALT and FLATTEN.
// There is intentionally no API call here that touches risk limits — the
// dashboard cannot loosen anything (spec §0.2, §8).

export interface SystemStateInfo {
  system_state: "RUNNING" | "SOFT_HALT" | "HARD_HALT" | "FLATTENING" | "FLAT_LOCKED";
  mode: string;
  size_multiplier: number;
  instrument: string;
}

export interface Pnl {
  equity: number;
  day_start_equity: number;
  daily_pnl: number;
  high_water_mark: number;
  drawdown_pct: number;
  size_multiplier: number;
  margin_used: number;
}

export interface PositionRow {
  instrument: { symbol: string };
  qty: number;
  avg_price: number;
  stop_price: number;
  broker_stop_order_id: string | null;
}

export interface AuditEvent {
  timestamp: string;
  kind: string;
  payload: Record<string, unknown>;
}

export interface SlippageStats {
  window: number;
  rolling_avg_cost: number;
  modeled_cost: number;
  breach_threshold: number;
}

const READ_KEY = import.meta.env.VITE_READONLY_KEY ?? "";
const CONTROL_KEY = import.meta.env.VITE_CONTROL_KEY ?? "";

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`/api${path}`, { headers: { "X-API-Key": READ_KEY } });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    headers: { "X-API-Key": CONTROL_KEY, "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

export const api = {
  state: () => get<SystemStateInfo>("/state"),
  pnl: () => get<Pnl>("/pnl"),
  positions: () => get<PositionRow[]>("/positions"),
  audit: () => get<AuditEvent[]>("/audit"),
  slippage: () => get<SlippageStats>("/slippage"),
  halt: (reason: string) => post<{ system_state: string }>("/halt", { reason }),
  flatten: (reason: string) => post<{ system_state: string }>("/flatten", { reason }),
};
