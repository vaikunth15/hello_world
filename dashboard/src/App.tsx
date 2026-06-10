import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  AuditEvent,
  Pnl,
  PositionRow,
  SlippageStats,
  SystemStateInfo,
} from "./api";

const STATE_COLORS: Record<string, string> = {
  RUNNING: "#1a7f37",
  SOFT_HALT: "#b58105",
  HARD_HALT: "#c93c37",
  FLATTENING: "#c93c37",
  FLAT_LOCKED: "#6e40c9",
};

const POLL_MS = 5000;

function StateBanner({ state }: { state: SystemStateInfo | null }) {
  if (!state) return <div className="banner" style={{ background: "#555" }}>connecting…</div>;
  return (
    <div className="banner" style={{ background: STATE_COLORS[state.system_state] ?? "#555" }}>
      <strong>{state.system_state}</strong>
      <span>
        {state.instrument} · {state.mode.toUpperCase()} · size ×{state.size_multiplier}
      </span>
    </div>
  );
}

function EquityCurve({ points }: { points: number[] }) {
  if (points.length < 2) return <p className="muted">collecting equity samples…</p>;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const path = points
    .map((v, i) => `${i === 0 ? "M" : "L"}${(i / (points.length - 1)) * 600},${40 - ((v - min) / span) * 36}`)
    .join(" ");
  return (
    <svg viewBox="0 0 600 44" width="100%" height="60" role="img" aria-label="equity curve">
      <path d={path} fill="none" stroke="#1a7f37" strokeWidth="1.5" />
    </svg>
  );
}

function DrawdownLadder({ pnl }: { pnl: Pnl | null }) {
  if (!pnl) return null;
  const dailyLossPct = pnl.day_start_equity
    ? Math.max(0, (100 * -pnl.daily_pnl) / pnl.day_start_equity)
    : 0;
  const rungs = [
    { label: "Daily loss → SOFT_HALT", at: 2, value: dailyLossPct },
    { label: "Drawdown → size ×0.5", at: 10, value: pnl.drawdown_pct },
    { label: "Drawdown → HARD_HALT + flatten", at: 15, value: pnl.drawdown_pct },
  ];
  return (
    <table>
      <tbody>
        {rungs.map((r) => (
          <tr key={r.label} className={r.value >= r.at ? "breached" : ""}>
            <td>{r.label}</td>
            <td>
              {r.value.toFixed(2)}% / {r.at}%
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Positions({ rows }: { rows: PositionRow[] }) {
  if (rows.length === 0) return <p className="muted">flat</p>;
  return (
    <table>
      <thead>
        <tr><th>symbol</th><th>qty</th><th>avg</th><th>stop</th><th>broker stop id</th></tr>
      </thead>
      <tbody>
        {rows.map((p) => (
          <tr key={p.instrument.symbol}>
            <td>{p.instrument.symbol}</td>
            <td>{p.qty}</td>
            <td>{p.avg_price.toFixed(1)}</td>
            <td>{p.stop_price.toFixed(1)}</td>
            <td>{p.broker_stop_order_id ?? <span className="breached">MISSING</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ConfirmButton({
  label,
  color,
  onConfirm,
}: {
  label: string;
  color: string;
  onConfirm: () => Promise<void>;
}) {
  const [arming, setArming] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!arming) {
    return (
      <button style={{ background: color }} onClick={() => setArming(true)}>
        {label}
      </button>
    );
  }
  return (
    <span className="confirm">
      <span>Really {label}?</span>
      <button
        style={{ background: color }}
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
            setArming(false);
          }
        }}
      >
        confirm
      </button>
      <button onClick={() => setArming(false)}>cancel</button>
    </span>
  );
}

export default function App() {
  const [state, setState] = useState<SystemStateInfo | null>(null);
  const [pnl, setPnl] = useState<Pnl | null>(null);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [slippage, setSlippage] = useState<SlippageStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const equityHistory = useRef<number[]>([]);

  const refresh = useCallback(async () => {
    try {
      const [s, p, pos, a, sl] = await Promise.all([
        api.state(), api.pnl(), api.positions(), api.audit(), api.slippage(),
      ]);
      setState(s);
      setPnl(p);
      setPositions(pos);
      setAudit(a.slice(-50).reverse());
      setSlippage(sl);
      equityHistory.current = [...equityHistory.current, p.equity].slice(-500);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <main>
      <StateBanner state={state} />
      {error && <p className="breached">{error}</p>}

      <section>
        <h2>Equity</h2>
        <EquityCurve points={equityHistory.current} />
        {pnl && (
          <p>
            ${pnl.equity.toLocaleString()} · day {pnl.daily_pnl >= 0 ? "+" : ""}
            {pnl.daily_pnl.toFixed(0)} · DD {pnl.drawdown_pct.toFixed(2)}%
          </p>
        )}
      </section>

      <section>
        <h2>Drawdown ladder</h2>
        <DrawdownLadder pnl={pnl} />
      </section>

      <section>
        <h2>Open positions</h2>
        <Positions rows={positions} />
      </section>

      <section>
        <h2>Slippage</h2>
        {slippage && (
          <p>
            rolling avg ${slippage.rolling_avg_cost.toFixed(2)} over {slippage.window} trades
            (modeled ${slippage.modeled_cost.toFixed(2)}, halt at $
            {slippage.breach_threshold.toFixed(2)})
          </p>
        )}
      </section>

      <section>
        {/* The only two write actions that exist. No resume, no risk toggle. */}
        <h2>Controls</h2>
        <ConfirmButton label="HALT" color="#b58105"
          onConfirm={async () => { await api.halt("dashboard halt"); await refresh(); }} />
        <ConfirmButton label="FLATTEN" color="#c93c37"
          onConfirm={async () => { await api.flatten("dashboard flatten"); await refresh(); }} />
      </section>

      <section>
        <h2>Audit (last 50)</h2>
        <table>
          <tbody>
            {audit.map((e, i) => (
              <tr key={i}>
                <td className="muted">{e.timestamp}</td>
                <td>{e.kind}</td>
                <td><code>{JSON.stringify(e.payload)}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </main>
  );
}
