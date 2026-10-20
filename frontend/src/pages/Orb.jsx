import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import Tooltip from "../components/Tooltip";
import RefreshBtn from "../components/RefreshBtn";
import { get, post } from "../api";

const fmt = (v, d = 2) =>
  v === null || v === undefined || v === "" ? "—" : typeof v === "number" ? v.toFixed(d) : String(v);

export default function Orb() {
  const [status, setStatus] = useState(null);
  const [proposals, setProposals] = useState([]);
  const [diagnostics, setDiagnostics] = useState(null);
  const [candidates, setCandidates] = useState({ candidates: [], states: {} });
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const [s, p, d, c] = await Promise.all([
        get("/api/orb/status"),
        get("/api/orb/proposals"),
        get("/api/orb/diagnostics"),
        get("/api/orb/candidates"),
      ]);
      setStatus(s);
      setProposals(p.proposals || []);
      setDiagnostics(d);
      setCandidates(c);
    } catch (e) {
      setLoadError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load]);

  const act = async (fn) => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const promote = (id) => act(() => post(`/api/orb/proposals/${id}/promote`));
  const reset = () => act(() => post("/api/orb/reset"));
  const flatten = () => act(() => post("/api/orb/flatten"));

  const ts = status?.trace_stats || {};

  return (
    <PageShell
      title="Stocks In Play ORB v1"
      description="Long-only opening-range-breakout detail: candidates, proposals, diagnostics, and runtime state. Proposals flow into the Orders workflow on promotion."
      actions={
        <div className="btn-row">
          <RefreshBtn onClick={load} />
          <button className="btn btn-sm" onClick={reset}>Reset Daily State</button>
          <button className="btn btn-sm" onClick={flatten}>Emergency Flatten</button>
        </div>
      }
    >
      {loading && <LoadingState />}
      {loadError && !loading && <ErrorState message={loadError} onRetry={load} />}
      {error && <div className="error-banner">{error}</div>}

      {!loading && !loadError && status && (
        <>
          <div className="card-grid">
            <div className="card">
              <div className="card-label">Candidates <Tooltip text="Symbols ranked in play by relative volume." /></div>
              <div className="card-value">{status.candidate_count}</div>
            </div>
            <div className="card">
              <div className="card-label">Pending Proposals</div>
              <div className="card-value">{status.proposal_count}</div>
            </div>
            <div className="card">
              <div className="card-label">Rejected Signals</div>
              <div className="card-value">{status.rejected_count}</div>
            </div>
            <div className="card">
              <div className="card-label">Daily P/L</div>
              <div className="card-value">{fmt(ts.daily_pnl)}</div>
            </div>
            <div className="card">
              <div className="card-label">Kill Switch</div>
              <div className="card-value">{ts.kill_switch_active ? "ACTIVE" : "—"}</div>
            </div>
            <div className="card">
              <div className="card-label">Opening Range</div>
              <div className="card-value" style={{ fontSize: "0.85rem" }}>{status.session?.opening_range}</div>
            </div>
            <div className="card">
              <div className="card-label">Entry Window</div>
              <div className="card-value" style={{ fontSize: "0.85rem" }}>{status.session?.entry_window}</div>
            </div>
            <div className="card">
              <div className="card-label">Flatten Time</div>
              <div className="card-value" style={{ fontSize: "0.85rem" }}>{status.session?.flatten_time}</div>
            </div>
          </div>

          <div className="section">
            <div className="section-title">Top Candidates</div>
            {(candidates.candidates || []).length === 0 ? (
              <EmptyState message="No candidates yet. Run a simulation cycle (POST /api/orb/generate) to evaluate in-play symbols." />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Rank</th><th>Symbol</th><th>OR High</th><th>OR Low</th>
                      <th>Captured</th><th>Proposal</th><th>Lockout</th>
                    </tr>
                  </thead>
                  <tbody>
                    {candidates.candidates.map((sym) => {
                      const st = candidates.states?.[sym] || {};
                      const or = st.opening_range || {};
                      return (
                        <tr key={sym}>
                          <td>{st.candidate_rank ?? "—"}</td>
                          <td>{sym}</td>
                          <td>{fmt(or.high)}</td>
                          <td>{fmt(or.low)}</td>
                          <td><span className={`status-badge ${st.opening_range_captured ? "on" : "off"}`}>{st.opening_range_captured ? "Yes" : "No"}</span></td>
                          <td>{st.proposal_status || "—"}</td>
                          <td><span className={`status-badge ${st.lockout_for_day ? "off" : "on"}`}>{st.lockout_for_day ? "Locked" : "Open"}</span></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="section">
            <div className="section-title">Proposals <Tooltip text="Promote a pending proposal to create an order in the Alpaca workflow." /></div>
            {proposals.length === 0 ? (
              <EmptyState message="No ORB proposals yet." />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th><th>Symbol</th><th>Status</th><th>Entry</th><th>Stop</th><th>Target</th>
                      <th>Qty</th><th>R</th><th>RVOL</th><th>Spread</th><th>VWAP</th><th>Regime</th>
                      <th>Setup / Reason</th><th>Mode</th><th>Order</th><th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {proposals.map((p) => (
                      <tr key={p.id}>
                        <td>{p.id}</td>
                        <td>{p.symbol}</td>
                        <td><span className={`status-badge ${p.status === "approved" ? "on" : p.status === "rejected" || p.status === "invalidated" ? "off" : "warn"}`}>{p.status}</span></td>
                        <td>{fmt(p.proposed_entry)}</td>
                        <td>{fmt(p.stop_price)}</td>
                        <td>{fmt(p.target_price)}</td>
                        <td>{fmt(p.quantity, 0)}</td>
                        <td>{fmt(p.expected_r, 1)}</td>
                        <td>{fmt(p.rvol, 1)}</td>
                        <td>{fmt(p.spread, 3)}{p.spread_check_status === "degraded" ? " ⚠" : ""}</td>
                        <td>{fmt(p.vwap)}</td>
                        <td>{p.regime_state || "—"}</td>
                        <td style={{ fontSize: "0.72rem", maxWidth: 200 }}>
                          {p.status === "rejected" || p.status === "invalidated"
                            ? (p.rejection_reason || p.invalidation_reason || "—")
                            : p.setup_name}
                        </td>
                        <td>{p.is_live ? "live" : "sim"}</td>
                        <td>{p.order_id || "—"}</td>
                        <td>
                          {p.status === "pending" && !p.order_id && (
                            <button className="btn btn-sm" onClick={() => promote(p.id)}>Promote → Order</button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {diagnostics && (
            <div className="section">
              <div className="section-title">Signal Diagnostics</div>
              <div className="card-grid">
                <div className="card"><div className="card-label">Total Proposals</div><div className="card-value">{diagnostics.total_proposals}</div></div>
                <div className="card"><div className="card-label">Pending</div><div className="card-value">{diagnostics.pending}</div></div>
                <div className="card"><div className="card-label">Rejected</div><div className="card-value">{diagnostics.rejected}</div></div>
                <div className="card"><div className="card-label">Avg RVOL</div><div className="card-value">{fmt(diagnostics.avg_rvol, 2)}</div></div>
                <div className="card"><div className="card-label">Avg Spread</div><div className="card-value">{fmt(diagnostics.avg_spread, 3)}</div></div>
              </div>
              {Object.keys(diagnostics.rejection_reasons || {}).length > 0 && (
                <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
                  <table>
                    <thead><tr><th>Rejection Reason</th><th>Count</th></tr></thead>
                    <tbody>
                      {Object.entries(diagnostics.rejection_reasons).map(([r, n]) => (
                        <tr key={r}><td style={{ fontSize: "0.78rem" }}>{r}</td><td>{n}</td></tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </PageShell>
  );
}
