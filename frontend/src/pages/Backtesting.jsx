import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import Tooltip from "../components/Tooltip";
import RefreshBtn from "../components/RefreshBtn";
import { get, post } from "../api";

const ORB_TEMPLATE = "stocks_in_play_orb_v1";

const ORB_PARAM_FIELDS = [
  { key: "risk_per_trade_pct", label: "Risk per trade %", tip: "Percent of equity risked per trade (0.25 = 0.25%)." },
  { key: "top_candidates", label: "Top candidates", tip: "Keep the top N symbols ranked by RVOL." },
  { key: "rvol_min", label: "RVOL min", tip: "Minimum first-5-min relative volume to be in play." },
  { key: "min_daily_atr_14", label: "ATR(14) min", tip: "Minimum daily ATR(14) to qualify." },
  { key: "spread_cap_abs", label: "Spread cap $", tip: "Max bid/ask spread in dollars." },
  { key: "spread_cap_bps", label: "Spread cap bps", tip: "Max spread in basis points of price." },
  { key: "enable_spy_regime_filter", label: "SPY regime filter", tip: "1 = require SPY risk-on, 0 = off." },
  { key: "entry_window_start", label: "Entry start (ET)", tip: "Earliest breakout entry time." },
  { key: "entry_window_end", label: "Entry end (ET)", tip: "Latest breakout entry time." },
  { key: "flatten_time", label: "Flatten time (ET)", tip: "Force-flatten time." },
];

const ORB_DEFAULTS = {
  risk_per_trade_pct: 0.25,
  top_candidates: 10,
  rvol_min: 2.0,
  min_daily_atr_14: 0.5,
  spread_cap_abs: 0.05,
  spread_cap_bps: 10,
  enable_spy_regime_filter: 1,
  entry_window_start: "09:35",
  entry_window_end: "10:30",
  flatten_time: "15:45",
};

function MetricRow({ label, value }) {
  return (
    <tr>
      <td style={{ color: "var(--text-muted)" }}>{label}</td>
      <td>{value === null || value === undefined ? "—" : String(value)}</td>
    </tr>
  );
}

export default function Backtesting() {
  const [backtests, setBacktests] = useState([]);
  const [strategies, setStrategies] = useState([]);
  const [expanded, setExpanded] = useState(null);
  const [form, setForm] = useState({
    strategy_name: "",
    symbols: "",
    start_date: "2024-01-01",
    end_date: "2024-12-31",
    starting_cash: 100000,
    data_source: "alpaca",
  });
  const [orbParams, setOrbParams] = useState({ ...ORB_DEFAULTS });
  const [error, setError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [b, s] = await Promise.all([get("/api/backtests"), get("/api/strategies")]);
      setBacktests(b.backtests || []);
      setStrategies(s.strategies || []);
    } catch (e) {
      setLoadError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedStrategy = strategies.find((s) => s.name === form.strategy_name);
  const isOrb =
    form.strategy_name === ORB_TEMPLATE || selectedStrategy?.template === ORB_TEMPLATE;

  const run = async () => {
    setError(null);
    try {
      const payload = {
        ...form,
        symbols: form.symbols.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean),
      };
      if (isOrb) {
        payload.template = ORB_TEMPLATE;
        payload.params = { ...orbParams };
      }
      await post("/api/backtests", payload);
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <PageShell
      title="Backtesting"
      description="Run Lumibot backtests against Alpaca data where credentials are configured."
      actions={<RefreshBtn onClick={load} />}
    >
      <div className="panel">
        <div className="section-title">Run Backtest</div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Strategy <Tooltip text="Select a configured strategy to backtest." /></label>
            <select className="form-select" value={form.strategy_name} onChange={(e) => setForm((f) => ({ ...f, strategy_name: e.target.value }))}>
              <option value="">Select...</option>
              {strategies.map((s) => <option key={s.name} value={s.name}>{s.name}</option>)}
              <option value={ORB_TEMPLATE}>Stocks In Play ORB v1</option>
              <option value="buy_and_hold">Simple Buy & Hold</option>
            </select>
          </div>
          <div className="form-group">
            <label className="form-label">Symbols (comma-separated)</label>
            <input className="form-input" value={form.symbols} onChange={(e) => setForm((f) => ({ ...f, symbols: e.target.value }))} placeholder="AAPL, MSFT" />
          </div>
          <div className="form-group">
            <label className="form-label">Start Date</label>
            <input className="form-input" type="date" value={form.start_date} onChange={(e) => setForm((f) => ({ ...f, start_date: e.target.value }))} />
          </div>
          <div className="form-group">
            <label className="form-label">End Date</label>
            <input className="form-input" type="date" value={form.end_date} onChange={(e) => setForm((f) => ({ ...f, end_date: e.target.value }))} />
          </div>
          <div className="form-group">
            <label className="form-label">Starting Cash</label>
            <input className="form-input" type="number" value={form.starting_cash} onChange={(e) => setForm((f) => ({ ...f, starting_cash: Number(e.target.value) }))} />
          </div>
          <div className="form-group">
            <label className="form-label">Data Source <Tooltip text="Alpaca provides minute and daily data through Lumibot when credentials are configured." /></label>
            <select className="form-select" value={form.data_source} onChange={(e) => setForm((f) => ({ ...f, data_source: e.target.value }))}>
              <option value="alpaca">Alpaca</option>
            </select>
          </div>
        </div>

        {isOrb && (
          <>
            <div className="section-title" style={{ marginTop: "1rem" }}>ORB Parameters</div>
            <div className="form-row">
              {ORB_PARAM_FIELDS.map((p) => (
                <div className="form-group" key={p.key}>
                  <label className="form-label">{p.label} <Tooltip text={p.tip} /></label>
                  <input
                    className="form-input"
                    value={orbParams[p.key]}
                    onChange={(e) => {
                      const num = Number(e.target.value);
                      setOrbParams((o) => ({
                        ...o,
                        [p.key]: isNaN(num) || e.target.value === "" ? e.target.value : num,
                      }));
                    }}
                  />
                </div>
              ))}
            </div>
            <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              Note: the 5-minute opening range requires minute bars. Missing Alpaca credentials return
              a safe warning instead of fabricated data.
            </div>
          </>
        )}

        {error && <div className="error-banner">{error}</div>}
        <div className="form-actions">
          <button className="btn" onClick={run}>Run Backtest</button>
        </div>
      </div>

      {loading && <LoadingState />}
      {loadError && !loading && <ErrorState message={loadError} onRetry={load} />}

      {!loading && !loadError && (
        <div className="section">
          <div className="section-title">Results</div>
          {backtests.length === 0 ? (
            <EmptyState message="No backtests run yet" />
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Strategy</th>
                    <th>Symbols</th>
                    <th>Range</th>
                    <th>Cash</th>
                    <th>Source</th>
                    <th>Status</th>
                    <th>Details</th>
                  </tr>
                </thead>
                <tbody>
                  {backtests.map((b) => (
                    <Row key={b.id} b={b} expanded={expanded === b.id} onToggle={() => setExpanded(expanded === b.id ? null : b.id)} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </PageShell>
  );
}

function Row({ b, expanded, onToggle }) {
  const metrics = b.result?.metrics;
  const warnings = b.result?.data_quality_warnings || [];
  return (
    <>
      <tr>
        <td>{b.id}</td>
        <td>{b.strategy_name}</td>
        <td>{b.symbols?.join(", ")}</td>
        <td style={{ fontSize: "0.75rem" }}>{b.start_date} → {b.end_date}</td>
        <td>${b.starting_cash}</td>
        <td>{b.data_source}</td>
        <td><span className={`status-badge ${b.status === "completed" ? "on" : b.status === "error" ? "off" : "warn"}`}>{b.status}</span></td>
        <td>
          {(metrics || warnings.length || b.error) ? (
            <button className="btn btn-sm" onClick={onToggle}>{expanded ? "Hide" : "View"}</button>
          ) : "—"}
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={8}>
            {b.error && <div className="error-banner">{b.error}</div>}
            {metrics && (
              <div className="table-wrap" style={{ maxWidth: 480 }}>
                <table>
                  <tbody>
                    <MetricRow label="Starting cash" value={metrics.starting_cash} />
                    <MetricRow label="Ending equity" value={metrics.ending_equity} />
                    <MetricRow label="Total return %" value={metrics.total_return_pct} />
                    <MetricRow label="Total trades" value={metrics.total_trades} />
                    <MetricRow label="Win rate %" value={metrics.win_rate_pct} />
                    <MetricRow label="Average R" value={metrics.average_R} />
                    <MetricRow label="Expectancy" value={metrics.expectancy} />
                    <MetricRow label="Best trade" value={metrics.best_trade} />
                    <MetricRow label="Worst trade" value={metrics.worst_trade} />
                    <MetricRow label="Rejected signals" value={metrics.rejected_signals} />
                    <MetricRow label="Avg RVOL" value={metrics.average_rvol} />
                    <MetricRow label="Avg spread" value={metrics.average_spread} />
                  </tbody>
                </table>
              </div>
            )}
            {warnings.length > 0 && (
              <ul style={{ fontSize: "0.75rem", color: "var(--text-muted)", marginTop: "0.5rem" }}>
                {warnings.map((w, i) => <li key={i}>{w}</li>)}
              </ul>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
