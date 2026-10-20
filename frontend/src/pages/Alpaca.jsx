import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import RefreshBtn from "../components/RefreshBtn";
import { get, post } from "../api";

export default function Alpaca() {
  const [status, setStatus] = useState(null);
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [dataStatus, setDataStatus] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [testResult, setTestResult] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [s, a, p, o, d] = await Promise.all([
        get("/api/alpaca/status"),
        get("/api/alpaca/account"),
        get("/api/alpaca/positions"),
        get("/api/alpaca/orders"),
        get("/api/alpaca/data/status"),
      ]);
      setStatus(s);
      setAccount(a);
      setPositions(p.positions || []);
      setOrders(o.orders || []);
      setDataStatus(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const testConnection = async () => {
    setError(null);
    try {
      setTestResult(await post("/api/alpaca/test-connection"));
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <PageShell
      title="Alpaca"
      description="Broker, paper trading, account, positions, orders, and market data status."
      actions={<RefreshBtn onClick={load} />}
    >
      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && status && (
        <>
          <div className="card-grid">
            <div className="card"><div className="card-label">Broker</div><div className="card-value">{status.broker}</div></div>
            <div className="card"><div className="card-label">Trading Mode</div><div className="card-value">{status.trading_mode}</div></div>
            <div className="card"><div className="card-label">Credentials</div><div className="card-value">{status.credentials?.configured ? "Configured" : "Not Configured"}</div></div>
            <div className="card"><div className="card-label">Paper</div><div className="card-value">{status.paper ? "Yes" : "No"}</div></div>
            <div className="card"><div className="card-label">Live Trading</div><div className="card-value">{status.live_trading_enabled ? "Enabled" : "Disabled"}</div></div>
            <div className="card"><div className="card-label">Data Feed</div><div className="card-value">{dataStatus?.data_feed || "—"}</div></div>
          </div>

          <div className="section">
            <div className="section-title">Connection</div>
            <button className="btn btn-sm" onClick={testConnection}>Test Connection</button>
            {testResult && <div className={testResult.ok ? "success-banner" : "info-banner"}>{testResult.status}</div>}
            {status.errors?.length > 0 && <div className="error-banner">{status.errors.join("; ")}</div>}
          </div>

          <div className="section">
            <div className="section-title">Account Status</div>
            {!account?.account ? <EmptyState message={account?.status || "No account data"} /> : (
              <div className="table-wrap"><table><tbody>
                {Object.entries(account.account).slice(0, 12).map(([k, v]) => <tr key={k}><th>{k}</th><td>{String(v)}</td></tr>)}
              </tbody></table></div>
            )}
          </div>

          <div className="section">
            <div className="section-title">Positions</div>
            {positions.length === 0 ? <EmptyState message="No positions returned" /> : (
              <div className="table-wrap"><table><thead><tr><th>Symbol</th><th>Qty</th><th>Market Value</th><th>P/L</th></tr></thead><tbody>
                {positions.map((p, i) => <tr key={i}><td>{p.symbol}</td><td>{p.qty || p.quantity}</td><td>{p.market_value || "—"}</td><td>{p.unrealized_pl || "—"}</td></tr>)}
              </tbody></table></div>
            )}
          </div>

          <div className="section">
            <div className="section-title">Broker Orders</div>
            {orders.length === 0 ? <EmptyState message="No broker orders returned" /> : (
              <div className="table-wrap"><table><thead><tr><th>ID</th><th>Symbol</th><th>Side</th><th>Status</th><th>Qty</th></tr></thead><tbody>
                {orders.map((o, i) => <tr key={o.id || i}><td>{o.id || "—"}</td><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}</td><td>{o.qty}</td></tr>)}
              </tbody></table></div>
            )}
          </div>
        </>
      )}
    </PageShell>
  );
}

