import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import Tooltip from "../components/Tooltip";
import useConfigDraftValidation, { draftsEqual } from "../hooks/useConfigDraftValidation";
import { API_BASE_URL, get, patch, post } from "../api";

const TIPS = {
  trading_mode: "simulation is local only; paper uses Alpaca paper readiness; live requires all live gates.",
  live_trading_enabled: "Master switch for live broker submission. Disabled by default.",
  default_asset_class: "Default asset class for broker-connected workflows.",
  default_data_source: "Alpaca is the only active market data provider on this branch.",
  require_order_review: "Require review before broker submission.",
  assigned_capital: "Optional strategy capital cap. Leave blank to use Alpaca available capital.",
  use_assigned_capital_limit: "When enabled with a positive assigned capital amount, risk checks cap bot exposure to that amount.",
  max_daily_loss: "Daily realised loss cap used by risk checks.",
  max_open_positions: "Maximum simultaneously open positions allowed by risk checks.",
  mock_paper_submission: "When enabled, paper orders are mocked locally (no order reaches Alpaca). Intended only for AI development agents. Leave disabled for real Alpaca paper trading. Simulation mode is always mocked; live is gated separately. The ALPACA_MOCK_PAPER_SUBMISSION env var overrides this.",
};

const DEFAULTS = {
  trading_mode: "simulation",
  live_trading_enabled: false,
  default_asset_class: "stocks",
  require_order_review: true,
  default_data_source: "alpaca",
  "alpaca.enabled": true,
  "alpaca.data_enabled": true,
  "alpaca.execution_enabled": true,
  "alpaca.paper": true,
  "alpaca.mock_paper_submission": false,
  "paper_trading.assigned_capital": null,
  "paper_trading.use_assigned_capital_limit": false,
  "risk_limits.max_daily_loss": 200,
  "risk_limits.max_open_positions": 5,
  "stocks.enabled": true,
  "stocks.paper_enabled": true,
  "stocks.live_enabled": false,
  "stocks.sizing_mode": "notional",
  "stocks.max_order_notional": null,
  "options.enabled": true,
  "options.paper_enabled": true,
  "options.live_enabled": false,
  "options.explicit_enablement": true,
  "options.account_approved": false,
  "crypto.enabled": true,
  "crypto.paper_enabled": false,
  "crypto.live_enabled": false,
  "crypto.explicit_enablement": false,
};

function draftFromConfig(cfg) {
  const alpaca = cfg.alpaca || {};
  const paperTrading = cfg.paper_trading || {};
  const riskLimits = cfg.risk_limits || {};
  const stocks = cfg.stocks || {};
  const options = cfg.options || {};
  const crypto = cfg.crypto || {};
  return {
    trading_mode: cfg.trading_mode ?? DEFAULTS.trading_mode,
    live_trading_enabled: cfg.live_trading_enabled ?? DEFAULTS.live_trading_enabled,
    default_asset_class: cfg.default_asset_class ?? DEFAULTS.default_asset_class,
    require_order_review: cfg.require_order_review ?? DEFAULTS.require_order_review,
    default_data_source: cfg.default_data_source ?? DEFAULTS.default_data_source,
    "alpaca.enabled": alpaca.enabled ?? DEFAULTS["alpaca.enabled"],
    "alpaca.data_enabled": alpaca.data_enabled ?? DEFAULTS["alpaca.data_enabled"],
    "alpaca.execution_enabled": alpaca.execution_enabled ?? DEFAULTS["alpaca.execution_enabled"],
    "alpaca.paper": alpaca.paper ?? DEFAULTS["alpaca.paper"],
    "alpaca.mock_paper_submission": alpaca.mock_paper_submission ?? DEFAULTS["alpaca.mock_paper_submission"],
    "paper_trading.assigned_capital": paperTrading.assigned_capital ?? DEFAULTS["paper_trading.assigned_capital"],
    "paper_trading.use_assigned_capital_limit": paperTrading.use_assigned_capital_limit ?? DEFAULTS["paper_trading.use_assigned_capital_limit"],
    "risk_limits.max_daily_loss": riskLimits.max_daily_loss ?? DEFAULTS["risk_limits.max_daily_loss"],
    "risk_limits.max_open_positions": riskLimits.max_open_positions ?? DEFAULTS["risk_limits.max_open_positions"],
    "stocks.enabled": stocks.enabled ?? DEFAULTS["stocks.enabled"],
    "stocks.paper_enabled": stocks.paper_enabled ?? DEFAULTS["stocks.paper_enabled"],
    "stocks.live_enabled": stocks.live_enabled ?? DEFAULTS["stocks.live_enabled"],
    "stocks.sizing_mode": stocks.sizing_mode ?? DEFAULTS["stocks.sizing_mode"],
    "stocks.max_order_notional": stocks.max_order_notional ?? DEFAULTS["stocks.max_order_notional"],
    "options.enabled": options.enabled ?? DEFAULTS["options.enabled"],
    "options.paper_enabled": options.paper_enabled ?? DEFAULTS["options.paper_enabled"],
    "options.live_enabled": options.live_enabled ?? DEFAULTS["options.live_enabled"],
    "options.explicit_enablement": options.explicit_enablement ?? DEFAULTS["options.explicit_enablement"],
    "options.account_approved": options.account_approved ?? DEFAULTS["options.account_approved"],
    "crypto.enabled": crypto.enabled ?? DEFAULTS["crypto.enabled"],
    "crypto.paper_enabled": crypto.paper_enabled ?? DEFAULTS["crypto.paper_enabled"],
    "crypto.live_enabled": crypto.live_enabled ?? DEFAULTS["crypto.live_enabled"],
    "crypto.explicit_enablement": crypto.explicit_enablement ?? DEFAULTS["crypto.explicit_enablement"],
  };
}

function BoolSelect({ value, onChange }) {
  return (
    <select className="form-select" style={{ width: 120 }} value={value ? "true" : "false"} onChange={(e) => onChange(e.target.value === "true")}>
      <option value="false">Disabled</option>
      <option value="true">Enabled</option>
    </select>
  );
}

function NumberInput({ value, onChange, min = 0, step = "0.01", width = 140 }) {
  return (
    <input
      className="form-input"
      style={{ width }}
      type="number"
      min={min}
      step={step}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
    />
  );
}

export default function Settings() {
  const [draft, setDraft] = useState(() => draftFromConfig(DEFAULTS));
  const [savedDraft, setSavedDraft] = useState(() => draftFromConfig(DEFAULTS));
  const [credentials, setCredentials] = useState(null);
  const [account, setAccount] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [msg, setMsg] = useState(null);
  const [saving, setSaving] = useState(false);

  const dirty = !draftsEqual(draft, savedDraft);
  const { validation, liveErrors } = useConfigDraftValidation(draft, !loading && !error);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfg, creds, acct] = await Promise.all([get("/api/config"), get("/api/alpaca/credentials"), get("/api/alpaca/account")]);
      const next = draftFromConfig(cfg);
      setDraft(next);
      setSavedDraft(next);
      setCredentials(creds);
      setAccount(acct);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const setField = (key, value) => {
    setMsg(null);
    setDraft((d) => ({ ...d, [key]: value }));
  };

  const save = async () => {
    setSaving(true);
    setMsg(null);
    setError(null);
    try {
      await patch("/api/config/batch", { updates: draft });
      setSavedDraft(draft);
      setMsg("Settings saved.");
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  };

  const reload = async () => {
    setMsg(null);
    setError(null);
    try {
      await post("/api/config/reload");
      setMsg("Configuration reloaded from disk.");
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const showLiveWarnings = draft.live_trading_enabled && liveErrors.length > 0;

  return (
    <PageShell
      title="Settings"
      description="Alpaca broker, data provider, trading mode, live gates, and asset-class controls."
      actions={
        <>
          <button className="btn btn-sm" onClick={reload}>Reload Config</button>
          <button className="btn" onClick={save} disabled={saving || loading || !dirty}>
            {saving ? "Saving..." : dirty ? "Save Settings *" : "Save Settings"}
          </button>
        </>
      }
    >
      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}
      {msg && <div className="success-banner">{msg}</div>}
      {dirty && !loading && <div className="info-banner">Unsaved changes.</div>}

      {!loading && !error && (
        <>
          {showLiveWarnings && <div className="error-banner">Live trading blocked: {liveErrors.join("; ")}</div>}
          {validation?.errors?.length > 0 && !showLiveWarnings && <div className="info-banner">{validation.errors.join("; ")}</div>}

          <div className="section">
            <div className="section-title">API</div>
            <div className="info-row"><span className="info-label">Backend URL</span><span style={{ fontSize: "0.82rem" }}>{API_BASE_URL}</span></div>
          </div>

          <div className="section">
            <div className="section-title">Broker Settings</div>
            <div className="info-row"><span className="info-label">Active Broker</span><span>Alpaca</span></div>
            <div className="info-row"><span className="info-label">Active Data Provider</span><span>Alpaca</span></div>
            <div className="info-row">
              <span className="info-label">Trading Mode <Tooltip text={TIPS.trading_mode} /></span>
              <select className="form-select" style={{ width: 160 }} value={draft.trading_mode} onChange={(e) => setField("trading_mode", e.target.value)}>
                <option value="simulation">Simulation</option>
                <option value="paper">Paper</option>
                <option value="live">Live</option>
              </select>
            </div>
            <div className="info-row"><span className="info-label">Live Trading <Tooltip text={TIPS.live_trading_enabled} /></span><BoolSelect value={draft.live_trading_enabled} onChange={(v) => setField("live_trading_enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Require Order Review <Tooltip text={TIPS.require_order_review} /></span><BoolSelect value={draft.require_order_review} onChange={(v) => setField("require_order_review", v)} /></div>
            <div className="info-row">
              <span className="info-label">Default Asset Class <Tooltip text={TIPS.default_asset_class} /></span>
              <select className="form-select" style={{ width: 140 }} value={draft.default_asset_class} onChange={(e) => setField("default_asset_class", e.target.value)}>
                <option value="stocks">Stocks</option>
                <option value="options">Options</option>
                <option value="crypto">Crypto</option>
              </select>
            </div>
            <div className="info-row"><span className="info-label">Default Data Source <Tooltip text={TIPS.default_data_source} /></span><span>Alpaca</span></div>
          </div>

          <div className="section">
            <div className="section-title">Alpaca</div>
            <div className="info-row"><span className="info-label">Enabled</span><BoolSelect value={draft["alpaca.enabled"]} onChange={(v) => setField("alpaca.enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Data Enabled</span><BoolSelect value={draft["alpaca.data_enabled"]} onChange={(v) => setField("alpaca.data_enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Execution Enabled</span><BoolSelect value={draft["alpaca.execution_enabled"]} onChange={(v) => setField("alpaca.execution_enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Paper Flag</span><BoolSelect value={draft["alpaca.paper"]} onChange={(v) => setField("alpaca.paper", v)} /></div>
            <div className="info-row"><span className="info-label">Mock Paper Submission <Tooltip text={TIPS.mock_paper_submission} /></span><BoolSelect value={draft["alpaca.mock_paper_submission"]} onChange={(v) => setField("alpaca.mock_paper_submission", v)} /></div>
            {draft.trading_mode === "paper" && !draft["alpaca.mock_paper_submission"] && (
              <div className="info-banner">Paper orders will be submitted to Alpaca for real (paper account). Enable Mock Paper Submission only for AI development.</div>
            )}
            <div className="info-row"><span className="info-label">Credential Status</span><span>{credentials?.configured ? "Configured" : "Not configured"}</span></div>
            <div className="info-row"><span className="info-label">Credential Env Vars</span><span style={{ fontSize: "0.78rem" }}>ALPACA_API_KEY / ALPACA_API_SECRET / ALPACA_OAUTH_TOKEN</span></div>
            <div className="info-row"><span className="info-label">Alpaca Buying Power</span><span>{account?.account?.buying_power ? `$${account.account.buying_power}` : "Unavailable"}</span></div>
            <div className="info-row"><span className="info-label">Alpaca Equity</span><span>{account?.account?.equity ? `$${account.account.equity}` : "Unavailable"}</span></div>
          </div>

          <div className="section">
            <div className="section-title">Bot Assigned Capital</div>
            <div className="info-banner">Bot assigned strategy capital is optional and separate from Alpaca account equity and buying power. Leave it blank to use Alpaca available capital.</div>
            <div className="info-row">
              <span className="info-label">Assigned Bot Capital <Tooltip text={TIPS.assigned_capital} /></span>
              <NumberInput value={draft["paper_trading.assigned_capital"]} onChange={(v) => setField("paper_trading.assigned_capital", v)} min={1} />
            </div>
            <div className="info-row">
              <span className="info-label">Use Assigned Capital Limit <Tooltip text={TIPS.use_assigned_capital_limit} /></span>
              <BoolSelect value={draft["paper_trading.use_assigned_capital_limit"]} onChange={(v) => setField("paper_trading.use_assigned_capital_limit", v)} />
            </div>
            <div className="info-row">
              <span className="info-label">Stock Sizing Mode</span>
              <span>{draft["stocks.sizing_mode"]}</span>
            </div>
            <div className="info-row">
              <span className="info-label">Max Stock Order Notional</span>
              <NumberInput value={draft["stocks.max_order_notional"]} onChange={(v) => setField("stocks.max_order_notional", v)} min={1} />
            </div>
            <div className="info-row">
              <span className="info-label">Max Daily Loss <Tooltip text={TIPS.max_daily_loss} /></span>
              <NumberInput value={draft["risk_limits.max_daily_loss"]} onChange={(v) => setField("risk_limits.max_daily_loss", v)} min={0} />
            </div>
            <div className="info-row">
              <span className="info-label">Max Open Positions <Tooltip text={TIPS.max_open_positions} /></span>
              <NumberInput value={draft["risk_limits.max_open_positions"]} onChange={(v) => setField("risk_limits.max_open_positions", v)} min={0} step="1" />
            </div>
          </div>

          <div className="section">
            <div className="section-title">Stocks</div>
            <div className="info-row"><span className="info-label">Enabled</span><BoolSelect value={draft["stocks.enabled"]} onChange={(v) => setField("stocks.enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Paper Enabled</span><BoolSelect value={draft["stocks.paper_enabled"]} onChange={(v) => setField("stocks.paper_enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Live Enabled</span><BoolSelect value={draft["stocks.live_enabled"]} onChange={(v) => setField("stocks.live_enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Sizing Mode</span><span>{draft["stocks.sizing_mode"]}</span></div>
          </div>

          <div className="section">
            <div className="section-title">Options</div>
            <div className="info-row"><span className="info-label">Enabled</span><BoolSelect value={draft["options.enabled"]} onChange={(v) => setField("options.enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Explicit Enablement</span><BoolSelect value={draft["options.explicit_enablement"]} onChange={(v) => setField("options.explicit_enablement", v)} /></div>
            <div className="info-row"><span className="info-label">Account Approved</span><BoolSelect value={draft["options.account_approved"]} onChange={(v) => setField("options.account_approved", v)} /></div>
            <div className="info-row"><span className="info-label">Paper Enabled</span><BoolSelect value={draft["options.paper_enabled"]} onChange={(v) => setField("options.paper_enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Live Enabled</span><BoolSelect value={draft["options.live_enabled"]} onChange={(v) => setField("options.live_enabled", v)} /></div>
          </div>

          <div className="section">
            <div className="section-title">Crypto</div>
            <div className="info-row"><span className="info-label">Enabled</span><BoolSelect value={draft["crypto.enabled"]} onChange={(v) => setField("crypto.enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Explicit Enablement</span><BoolSelect value={draft["crypto.explicit_enablement"]} onChange={(v) => setField("crypto.explicit_enablement", v)} /></div>
            <div className="info-row"><span className="info-label">Paper Enabled</span><BoolSelect value={draft["crypto.paper_enabled"]} onChange={(v) => setField("crypto.paper_enabled", v)} /></div>
            <div className="info-row"><span className="info-label">Live Enabled</span><BoolSelect value={draft["crypto.live_enabled"]} onChange={(v) => setField("crypto.live_enabled", v)} /></div>
          </div>
        </>
      )}
    </PageShell>
  );
}
