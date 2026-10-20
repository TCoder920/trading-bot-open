import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import Tooltip from "../components/Tooltip";
import RefreshBtn from "../components/RefreshBtn";
import { get, post } from "../api";

const SECTIONS = [
  {
    key: "proposed",
    title: "Proposed / Risk Approved",
    match: (o) =>
      o.risk_approved &&
      ["proposed", "risk_approved"].includes(o.execution_status),
  },
  {
    key: "submission",
    title: "Pending Broker Submission",
    match: (o) => o.execution_status === "pending_broker_submission",
  },
  {
    key: "submitted",
    title: "Submitted / Filled",
    match: (o) => ["paper_submitted", "paper_filled", "live_submitted", "live_filled", "accepted", "partially_filled"].includes(o.execution_status),
  },
  {
    key: "terminal",
    title: "Rejected / Failed / Canceled",
    match: (o) => ["rejected", "failed", "canceled", "blocked", "risk_rejected"].includes(o.execution_status),
  },
];

const statusColor = (s) => {
  if (["paper_filled", "live_filled", "accepted"].includes(s)) return "on";
  if (["risk_rejected", "rejected", "blocked", "failed", "canceled"].includes(s)) return "off";
  return "warn";
};

const formatSize = (o) => {
  if ((o.asset_class || "stocks") === "stocks" && o.sizing_mode === "notional") {
    return `$${Number(o.notional || 0).toFixed(2)} notional`;
  }
  if (o.asset_class === "options") return `${o.quantity || "—"} contracts`;
  if (o.notional) return `$${Number(o.notional).toFixed(2)}`;
  return o.quantity || o.dollar_amount || "—";
};

function OrderTable({ orders, onAction }) {
  if (!orders.length) return null;

  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Time</th>
            <th>Symbol</th>
            <th>Asset</th>
            <th>Strategy <Tooltip text="Origin strategy. ORB proposals show 'stocks_in_play_orb_v1'." /></th>
            <th>Side</th>
            <th>Qty / Notional</th>
            <th>Type</th>
            <th>Broker ID</th>
            <th>Paper</th>
            <th>Risk <Tooltip text="Risk engine result for this proposal." /></th>
            <th>Review</th>
            <th>Status</th>
            <th>Error</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>{o.id}</td>
              <td style={{ fontSize: "0.75rem" }}>{o.timestamp?.slice(0, 19) || "—"}</td>
              <td>{o.symbol}</td>
              <td>{o.asset_class || "stocks"}</td>
              <td style={{ fontSize: "0.72rem" }}>{o.strategy || "—"}</td>
              <td>{o.side}</td>
              <td>{formatSize(o)}</td>
              <td>{o.order_type}</td>
              <td style={{ fontSize: "0.72rem" }}>{o.broker_order_id || "—"}</td>
              <td>{o.paper ? "Yes" : "No"}</td>
              <td>
                <span className={`status-badge ${o.risk_approved ? "on" : "off"}`}>
                  {o.risk_approved ? "Approved" : o.risk_reason?.slice(0, 40) || "Rejected"}
                </span>
              </td>
              <td>{o.review_status}</td>
              <td>
                <span className={`status-badge ${statusColor(o.execution_status)}`}>
                  {o.execution_status}
                </span>
              </td>
              <td style={{ fontSize: "0.75rem", maxWidth: 120 }}>{o.error || o.notes || "—"}</td>
              <td>
                <div className="btn-row">
                  {o.risk_approved && o.execution_status === "risk_approved" && (
                    <>
                      <button className="btn btn-sm" onClick={() => onAction(o.id, "review")}>Review</button>
                      <button className="btn btn-sm" onClick={() => onAction(o.id, "advance")}>Queue for Broker</button>
                    </>
                  )}
                  {o.risk_approved && o.execution_status === "pending_broker_submission" && (
                    <>
                      <button className="btn btn-sm" onClick={() => onAction(o.id, "place")}>Submit</button>
                      <button className="btn btn-sm" onClick={() => onAction(o.id, "execute")}>Mark Filled</button>
                      <button className="btn btn-sm" onClick={() => onAction(o.id, "fail", "Broker submission failed")}>Mark Failed</button>
                    </>
                  )}
                  {!["paper_filled", "live_filled", "rejected", "failed", "canceled", "blocked", "risk_rejected"].includes(o.execution_status) && (
                    <>
                      <button className="btn btn-sm" onClick={() => onAction(o.id, "reject")}>Reject</button>
                      <button className="btn btn-sm" onClick={() => onAction(o.id, "cancel")}>Cancel</button>
                    </>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Orders() {
  const [orders, setOrders] = useState([]);
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [formError, setFormError] = useState(null);
  const [preview, setPreview] = useState(null);
  const [form, setForm] = useState({
    symbol: "",
    asset_class: "stocks",
    stock_sizing_mode: "notional",
    side: "buy",
    notional: "",
    dollar_amount: "",
    quantity: "",
    order_type: "market",
  });

  const load = useCallback(async () => {
    setError(null);
    try {
      const [d, cfg] = await Promise.all([get("/api/orders"), get("/api/config")]);
      setOrders(d.orders || []);
      setConfig(cfg);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const buildPayload = () => {
    const payload = {
      symbol: form.symbol,
      asset_class: form.asset_class,
      side: form.side,
      order_type: form.order_type,
    };
    if (form.asset_class === "stocks") {
      payload.sizing_mode = form.stock_sizing_mode;
      if (form.stock_sizing_mode === "notional") {
        payload.notional = Number(form.notional) || 0;
        payload.time_in_force = "day";
      } else {
        payload.quantity = form.quantity ? Number(form.quantity) : 0;
        payload.dollar_amount = form.dollar_amount ? Number(form.dollar_amount) : undefined;
      }
    } else if (form.asset_class === "options") {
      payload.quantity = form.quantity ? Number(form.quantity) : 0;
    } else {
      payload.notional = form.notional ? Number(form.notional) : undefined;
      payload.quantity = form.quantity ? Number(form.quantity) : undefined;
    }
    return payload;
  };

  const previewOrder = async () => {
    setFormError(null);
    setPreview(null);
    try {
      setPreview(await post("/api/orders/preview", buildPayload()));
    } catch (e) {
      setFormError(e.message);
    }
  };

  const propose = async () => {
    setFormError(null);
    try {
      await post("/api/orders/propose", buildPayload());
      setPreview(null);
      setForm((f) => ({ ...f, symbol: "", notional: "", dollar_amount: "", quantity: "", order_type: "market" }));
      await load();
    } catch (e) {
      setFormError(e.message);
    }
  };

  const action = async (id, act, failReason) => {
    setError(null);
    try {
      if (act === "fail") {
        await post(`/api/orders/${id}/fail`, { reason: failReason || "Failed" });
      } else if (act === "execute") {
        await post(`/api/orders/${id}/execute`, { notes: "Marked executed via UI (simulation or agent result)" });
      } else if (act === "reject") {
        await post(`/api/orders/${id}/reject`, { reason: "Rejected via UI" });
      } else {
        await post(`/api/orders/${id}/${act}`);
      }
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <PageShell
      title="Orders"
      description="Propose orders, run risk checks, and advance the Alpaca broker workflow. Simulation testing works without live trading."
      actions={<RefreshBtn onClick={load} />}
    >
      <div className="panel">
        <div className="section-title">Propose Order</div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Symbol</label>
            <input
              className="form-input"
              value={form.symbol}
              onChange={(e) => setForm((f) => ({ ...f, symbol: e.target.value.toUpperCase() }))}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Asset Class</label>
            <select className="form-select" value={form.asset_class} onChange={(e) => setForm((f) => ({ ...f, asset_class: e.target.value }))}>
              <option value="stocks">Stocks</option>
              <option value="options">Options</option>
              <option value="crypto">Crypto</option>
            </select>
          </div>
          {form.asset_class === "stocks" && (
            <div className="form-group">
              <label className="form-label">Stock Order Method <Tooltip text="Use dollar notional for fractional execution or whole-share quantity for standard stock orders." /></label>
              <select className="form-select" value={form.stock_sizing_mode} onChange={(e) => setForm((f) => ({ ...f, stock_sizing_mode: e.target.value }))}>
                <option value="notional">Dollar notional</option>
                <option value="whole_share">Whole shares</option>
              </select>
            </div>
          )}
          <div className="form-group">
            <label className="form-label">Side</label>
            <select className="form-select" value={form.side} onChange={(e) => setForm((f) => ({ ...f, side: e.target.value }))}>
              <option value="buy">Buy</option>
              <option value="sell">Sell</option>
            </select>
          </div>
          {form.asset_class === "stocks" && form.stock_sizing_mode === "notional" && (
            <div className="form-group">
              <label className="form-label">Stock Dollar Notional <Tooltip text="Submitted to Alpaca as notional. Alpaca calculates the resulting fractional shares." /></label>
              <input
                className="form-input"
                type="number"
                min={config?.stocks?.min_order_notional || 1}
                max={config?.stocks?.max_order_notional || undefined}
                step="0.01"
                value={form.notional}
                onChange={(e) => setForm((f) => ({ ...f, notional: e.target.value }))}
              />
            </div>
          )}
          {form.asset_class === "stocks" && form.stock_sizing_mode === "whole_share" && (
            <>
              <div className="form-group">
                <label className="form-label">Whole Share Quantity <Tooltip text="Submitted to Alpaca as quantity. Fractional share quantity is not supported here." /></label>
                <input
                  className="form-input"
                  type="number"
                  min="1"
                  step="1"
                  value={form.quantity}
                  onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Estimated Dollar Value <Tooltip text="Used by risk checks only. It is not sent to Alpaca as notional for whole-share orders." /></label>
                <input
                  className="form-input"
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.dollar_amount}
                  onChange={(e) => setForm((f) => ({ ...f, dollar_amount: e.target.value }))}
                />
              </div>
            </>
          )}
          {form.asset_class === "options" && (
            <div className="form-group">
              <label className="form-label">Contract Quantity <Tooltip text="Options orders use whole contracts only. Notional sizing is not allowed." /></label>
              <input
                className="form-input"
                type="number"
                min="1"
                step="1"
                value={form.quantity}
                onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))}
              />
            </div>
          )}
          {form.asset_class === "crypto" && (
            <>
              <div className="form-group">
                <label className="form-label">Crypto Notional</label>
                <input
                  className="form-input"
                  type="number"
                  step="0.01"
                  value={form.notional}
                  onChange={(e) => setForm((f) => ({ ...f, notional: e.target.value }))}
                />
              </div>
              <div className="form-group">
                <label className="form-label">Crypto Quantity</label>
                <input
                  className="form-input"
                  type="number"
                  value={form.quantity}
                  onChange={(e) => setForm((f) => ({ ...f, quantity: e.target.value }))}
                />
              </div>
            </>
          )}
          <div className="form-group">
            <label className="form-label">Order Type</label>
            <select className="form-select" value={form.order_type} onChange={(e) => setForm((f) => ({ ...f, order_type: e.target.value }))}>
              <option value="market">Market</option>
              <option value="limit">Limit</option>
            </select>
          </div>
        </div>
        {formError && <div className="error-banner">{formError}</div>}
        {preview && (
          <div className="info-banner">
            <strong>Preview:</strong> risk {preview.risk_approved ? "approved" : "rejected"} ({preview.risk_reason}).
            <div style={{ marginTop: "0.5rem", fontSize: "0.78rem" }}>
              Normalized: {JSON.stringify(preview.normalized)}
            </div>
            {preview.broker_payload && (
              <div style={{ marginTop: "0.5rem", fontSize: "0.78rem" }}>
                Broker payload: {JSON.stringify(preview.broker_payload)}
              </div>
            )}
          </div>
        )}
        <div className="form-actions">
          <button className="btn" onClick={previewOrder}>Preview</button>
          <button className="btn" onClick={propose}>Submit Proposal</button>
        </div>
      </div>

      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}

      {!loading && !error && orders.length === 0 && (
        <EmptyState message="No orders yet. Submit a proposal above to start the workflow." />
      )}

      {!loading && !error && orders.length > 0 && SECTIONS.map((section) => {
        const sectionOrders = orders.filter(section.match);
        return (
          <div key={section.key} className="order-section">
            <div className="section-title">{section.title}</div>
            {sectionOrders.length === 0 ? (
              <EmptyState message={`No orders in ${section.title.toLowerCase()}.`} />
            ) : (
              <OrderTable orders={sectionOrders} onAction={action} />
            )}
          </div>
        );
      })}
    </PageShell>
  );
}
