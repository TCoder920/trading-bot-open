import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import RefreshBtn from "../components/RefreshBtn";
import { get, post } from "../api";

export default function ProductionReadiness() {
  const [data, setData] = useState(null);
  const [exposure, setExposure] = useState(null);
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [readiness, exposureData, runsData] = await Promise.all([
        get("/api/system/readiness"),
        get("/api/reconciliation/exposure"),
        get("/api/reconciliation/runs?limit=5"),
      ]);
      setData(readiness);
      setExposure(exposureData);
      setRuns(runsData.runs || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const backup = async () => {
    setMsg(null);
    setError(null);
    try {
      const result = await post("/api/system/backup");
      setMsg(`Backup created: ${result.backup?.path}`);
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const syncPositions = async () => {
    setMsg(null);
    setError(null);
    try {
      const result = await post("/api/reconciliation/positions");
      setMsg(`Positions sync: ${result.status}`);
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const reconcileOrders = async () => {
    setMsg(null);
    setError(null);
    try {
      const result = await post("/api/reconciliation/orders");
      setMsg(`Order reconciliation: ${result.status}`);
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <PageShell
      title="Production Readiness"
      description="Operational gates for paper and live trading."
      actions={<><button className="btn btn-sm" onClick={reconcileOrders}>Reconcile Orders</button><button className="btn btn-sm" onClick={syncPositions}>Sync Positions</button><button className="btn btn-sm" onClick={backup}>Create DB Backup</button><RefreshBtn onClick={load} /></>}
    >
      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}
      {msg && <div className="success-banner">{msg}</div>}

      {!loading && !error && data && (
        <>
          <div className="card-grid">
            <div className="card">
              <div className="card-label">Trading Mode</div>
              <div className="card-value">{data.trading_mode}</div>
            </div>
            <div className="card">
              <div className="card-label">Paper Ready</div>
              <div className="card-value">{data.ready_for_paper ? "Yes" : "No"}</div>
            </div>
            <div className="card">
              <div className="card-label">Live Ready</div>
              <div className="card-value">{data.ready_for_live ? "Yes" : "No"}</div>
            </div>
            <div className="card">
              <div className="card-label">Migrations</div>
              <div className="card-value">{data.schema_migrations?.length || 0}</div>
            </div>
            <div className="card">
              <div className="card-label">Capital Source</div>
              <div className="card-value">{exposure?.capital_source || "unknown"}</div>
            </div>
            <div className="card">
              <div className="card-label">Open Exposure</div>
              <div className="card-value">${Number(exposure?.total_exposure || 0).toFixed(2)}</div>
            </div>
            <div className="card">
              <div className="card-label">Remaining Capital</div>
              <div className="card-value">{exposure?.remaining_capital == null ? "Unavailable" : `$${Number(exposure.remaining_capital).toFixed(2)}`}</div>
            </div>
          </div>

          <div className="section">
            <div className="section-title">Capital And Exposure</div>
            <div className="info-banner">Assigned capital is optional. If it is not set to a positive amount, order validation uses Alpaca available capital when account data is available.</div>
            <div className="info-row"><span className="info-label">Assigned Capital Limit</span><span>{exposure?.assigned_capital_enabled ? "Active" : "Inactive"}</span></div>
            <div className="info-row"><span className="info-label">Assigned Capital</span><span>{exposure?.assigned_capital == null ? "Not set" : `$${Number(exposure.assigned_capital).toFixed(2)}`}</span></div>
            <div className="info-row"><span className="info-label">Alpaca Buying Power</span><span>{exposure?.account_buying_power == null ? "Unavailable" : `$${Number(exposure.account_buying_power).toFixed(2)}`}</span></div>
            <div className="info-row"><span className="info-label">Position Exposure</span><span>${Number(exposure?.position_exposure || 0).toFixed(2)}</span></div>
            <div className="info-row"><span className="info-label">Open Order Exposure</span><span>${Number(exposure?.open_order_exposure || 0).toFixed(2)}</span></div>
          </div>

          <div className="section">
            <div className="section-title">Checks</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Check</th><th>Status</th><th>Severity</th><th>Message</th></tr></thead>
                <tbody>
                  {data.checks.map((c) => (
                    <tr key={c.key}>
                      <td>{c.key}</td>
                      <td><span className={`status-badge ${c.ok ? "on" : c.severity === "warning" ? "warn" : "off"}`}>{c.ok ? "Pass" : "Action"}</span></td>
                      <td>{c.severity}</td>
                      <td>{c.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="section">
            <div className="section-title">Schema Migrations</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Version</th><th>Applied</th></tr></thead>
                <tbody>
                  {(data.schema_migrations || []).map((m) => (
                    <tr key={m.version}><td>{m.version}</td><td>{m.applied_at}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="section">
            <div className="section-title">Recent Reconciliation Runs</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Type</th><th>Status</th><th>Summary</th><th>Created</th></tr></thead>
                <tbody>
                  {runs.length === 0 ? (
                    <tr><td colSpan="4">No reconciliation runs</td></tr>
                  ) : runs.map((run) => (
                    <tr key={run.id}>
                      <td>{run.run_type}</td>
                      <td><span className={`status-badge ${run.status === "ok" ? "on" : "warn"}`}>{run.status}</span></td>
                      <td>{JSON.stringify(run.summary)}</td>
                      <td>{run.created_at}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </PageShell>
  );
}
