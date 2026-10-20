import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import RefreshBtn from "../components/RefreshBtn";
import { get, patch } from "../api";

const SETTINGS = [
  { key: "crypto.enabled", label: "Enabled" },
  { key: "crypto.paper_enabled", label: "Paper trading" },
  { key: "crypto.live_enabled", label: "Live trading" },
  { key: "crypto.explicit_enablement", label: "Explicit enablement" },
];

function isCrypto(assetClass) {
  return String(assetClass || "").toLowerCase().includes("crypto");
}

export default function Crypto() {
  const [positions, setPositions] = useState([]);
  const [orders, setOrders] = useState([]);
  const [cfg, setCfg] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const [posResp, ordResp, config] = await Promise.all([
        get("/api/alpaca/positions").catch(() => ({ positions: [] })),
        get("/api/orders?limit=200").catch(() => ({ orders: [] })),
        get("/api/config"),
      ]);
      setPositions((posResp.positions || []).filter((p) => isCrypto(p.asset_class)));
      setOrders((ordResp.orders || []).filter((o) => o.asset_class === "crypto"));
      setCfg(config);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  async function toggle(key, value) {
    setSaving(key);
    try {
      await patch("/api/config", { key, value });
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(null);
    }
  }

  const cCfg = cfg?.crypto || {};
  const allowed = cCfg.allowed_symbols || [];

  return (
    <PageShell
      title="Crypto"
      description="Reference view: crypto positions, order history, and quick settings. The bot trades crypto only via strategies (24/7) — there is no manual trading here (use Alpaca directly for manual trades)."
      actions={<RefreshBtn onClick={load} />}
    >
      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}

      {!loading && !error && (
        <>
          <div className="section">
            <div className="section-title">Quick Settings</div>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Setting</th><th>State</th><th></th></tr></thead>
                <tbody>
                  {SETTINGS.map((s) => {
                    const key = s.key.split(".")[1];
                    const on = Boolean(cCfg[key]);
                    return (
                      <tr key={s.key}>
                        <td>{s.label}</td>
                        <td><span className={`status-badge ${on ? "on" : "off"}`}>{on ? "On" : "Off"}</span></td>
                        <td>
                          <button className="btn btn-sm" disabled={saving === s.key} onClick={() => toggle(s.key, !on)}>
                            {saving === s.key ? "…" : on ? "Disable" : "Enable"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="muted" style={{ fontSize: "0.75rem" }}>
              Allowed symbols: {allowed.length ? allowed.join(", ") : "—"}. Live crypto requires the crypto gates plus the global live gate.
            </p>
          </div>

          <div className="section">
            <div className="section-title">Active Crypto Positions</div>
            {positions.length === 0 ? (
              <EmptyState message="No crypto positions (from Alpaca)." />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Pair</th><th>Qty</th><th>Avg Cost</th><th>Mkt Value</th><th>Unrealized P/L</th></tr></thead>
                  <tbody>
                    {positions.map((p, i) => (
                      <tr key={i}>
                        <td>{p.symbol}</td>
                        <td>{p.qty ?? p.quantity}</td>
                        <td>{p.avg_entry_price ?? p.avg_cost ?? "—"}</td>
                        <td>{p.market_value ?? "—"}</td>
                        <td>{p.unrealized_pl ?? p.unrealised_pnl ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="section">
            <div className="section-title">Crypto Order History</div>
            {orders.length === 0 ? (
              <EmptyState message="No crypto orders recorded yet." />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Time</th><th>Pair</th><th>Side</th><th>Qty/Notional</th><th>Type</th><th>Status</th><th>Strategy</th></tr></thead>
                  <tbody>
                    {orders.map((o) => (
                      <tr key={o.id}>
                        <td style={{ fontSize: "0.75rem" }}>{(o.created_at || o.timestamp || "").slice(0, 19)}</td>
                        <td>{o.symbol}</td>
                        <td>{o.side}</td>
                        <td>{o.quantity ?? o.notional ?? "—"}</td>
                        <td>{o.order_type}</td>
                        <td><span className="status-badge">{o.execution_status}</span></td>
                        <td>{o.strategy || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </PageShell>
  );
}
