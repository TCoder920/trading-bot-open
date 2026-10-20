import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import Tooltip from "../components/Tooltip";
import RefreshBtn from "../components/RefreshBtn";
import { get } from "../api";

const CATEGORIES = ["", "config", "risk", "watchlist", "strategy", "order", "backtest", "bot", "alpaca", "general"];

export default function Logs() {
  const [logs, setLogs] = useState([]);
  const [category, setCategory] = useState("");
  const [symbol, setSymbol] = useState("");
  const [strategy, setStrategy] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setError(null);
    try {
      const params = new URLSearchParams();
      if (category) params.set("category", category);
      if (symbol) params.set("symbol", symbol);
      if (strategy) params.set("strategy", strategy);
      if (search) params.set("search", search);
      params.set("limit", "200");
      const d = await get(`/api/logs?${params}`);
      setLogs(d.logs || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [category, symbol, strategy, search]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <PageShell
      title="Logs"
      description="Audit trail of config changes, orders, risk checks, backtests, and errors."
      actions={<RefreshBtn onClick={load} />}
    >
      <div className="filters">
        <select className="form-select" value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All Categories</option>
          {CATEGORIES.filter(Boolean).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <input className="form-input" placeholder="Symbol" value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())} style={{ width: 100 }} />
        <input className="form-input" placeholder="Strategy" value={strategy} onChange={(e) => setStrategy(e.target.value)} style={{ width: 120 }} />
        <input className="form-input" placeholder="Search text..." value={search} onChange={(e) => setSearch(e.target.value)} style={{ width: 180 }} />
        <button className="btn btn-sm" onClick={load}>Search</button>
        <Tooltip text="Audit trail of all system events: config changes, orders, risk checks, backtests, and errors." />
      </div>

      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}

      {!loading && !error && logs.length === 0 && (
        <EmptyState message="No logs matching filters" />
      )}

      {!loading && !error && logs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Level</th>
                <th>Category</th>
                <th>Symbol</th>
                <th>Strategy</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {logs.map((l) => (
                <tr key={l.id}>
                  <td style={{ fontSize: "0.72rem", whiteSpace: "nowrap" }}>{l.timestamp?.slice(0, 19)}</td>
                  <td><span className={`status-badge ${l.level === "error" ? "off" : "on"}`}>{l.level}</span></td>
                  <td>{l.category}</td>
                  <td>{l.symbol || "—"}</td>
                  <td>{l.strategy || "—"}</td>
                  <td style={{ maxWidth: 400 }}>{l.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}
