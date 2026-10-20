import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import Tooltip from "../components/Tooltip";
import { get, patch } from "../api";

const TIPS = {
  max_dollars_per_trade: "Maximum dollar value allowed per single trade.",
  max_loss_per_trade: "Maximum loss allowed before a single trade is force-closed.",
  max_daily_loss: "Cumulative loss cap for the day. Trading halts when reached.",
  max_trades_per_day: "Maximum number of trades allowed per day.",
  max_open_positions: "Maximum number of simultaneously held positions.",
  assigned_capital: "Strategy capital the bot is allowed to use when assigned-capital mode is enabled.",
  use_assigned_capital_limit: "Use assigned capital instead of full Alpaca buying power for risk checks.",
  max_stock_order_notional: "Maximum dollar notional allowed for one stock order.",
};

const FIELDS = [
  { key: "assigned_capital", label: "Assigned Bot Capital", type: "number" },
  { key: "use_assigned_capital_limit", label: "Use Assigned Capital Limit", type: "boolean" },
  { key: "stock_sizing_mode", label: "Stock Sizing Mode", type: "readonly" },
  { key: "max_stock_order_notional", label: "Max Stock Order Notional", type: "number" },
  { key: "max_dollars_per_trade", label: "Max $ Per Trade", type: "number" },
  { key: "max_loss_per_trade", label: "Max Loss Per Trade", type: "number" },
  { key: "max_daily_loss", label: "Max Daily Loss", type: "number" },
  { key: "max_trades_per_day", label: "Max Trades/Day", type: "number" },
  { key: "max_open_positions", label: "Max Open Positions", type: "number" },
];

export default function RiskSettings() {
  const [draft, setDraft] = useState({});
  const [dirty, setDirty] = useState(false);
  const [msg, setMsg] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setError(null);
    try {
      const d = await get("/api/risk/settings");
      setDraft(d);
      setDirty(false);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const change = (key, val) => {
    setDraft((d) => ({ ...d, [key]: val }));
    setDirty(true);
  };

  const save = async () => {
    setMsg(null);
    setError(null);
    try {
      await patch("/api/risk/settings", draft);
      setMsg("Saved");
      setDirty(false);
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <PageShell title="Risk Settings" description="Pre-execution limits enforced on every order proposal and placement.">
      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}
      {msg && <div className="success-banner">{msg}</div>}

      {!loading && !error && (
        <div className="panel">
          {FIELDS.map((f) => (
            <div className="form-group" key={f.key}>
              <label className="form-label">
                {f.label} <Tooltip text={TIPS[f.key]} />
              </label>
              {f.type === "boolean" ? (
                <select className="form-select" value={draft[f.key] ? "true" : "false"} onChange={(e) => change(f.key, e.target.value === "true")}>
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              ) : f.type === "readonly" ? (
                <input className="form-input" value={draft[f.key] ?? ""} disabled />
              ) : (
                <input
                  className="form-input"
                  type="number"
                  value={draft[f.key] ?? ""}
                  onChange={(e) => change(f.key, e.target.value === "" ? null : Number(e.target.value))}
                />
              )}
            </div>
          ))}
          <div className="form-actions">
            <button className="btn" onClick={save} disabled={!dirty}>Save</button>
            <button className="btn" onClick={load} disabled={!dirty}>Reset</button>
          </div>
        </div>
      )}
    </PageShell>
  );
}
