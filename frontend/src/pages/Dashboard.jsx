import Tooltip from "../components/Tooltip";
import RefreshBtn from "../components/RefreshBtn";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import usePolling from "../hooks/usePolling";
import { get } from "../api";

const TIPS = {
  bot_state: "Current operational state of the bot process.",
  trading_mode: "simulation is local only; paper and live use Alpaca gates.",
  live_trading_enabled: "Master switch. Must be true for real order placement.",
  default_asset_class: "Default asset class the bot is configured to trade.",
  active_strategy: "Strategy that will generate signals.",
  daily_pnl: "Realized profit/loss for today's trades.",
  trades_today: "Number of trades executed today.",
  max_daily_loss: "Maximum allowed cumulative loss per day before blocking.",
  open_positions: "Number of currently held positions.",
  alpaca_credentials_configured: "Whether Alpaca credentials are present in environment variables.",
};

const CARDS = [
  { key: "bot_state", label: "Bot Status" },
  { key: "active_broker", label: "Active Broker" },
  { key: "active_data_provider", label: "Data Provider" },
  { key: "trading_mode", label: "Trading Mode" },
  { key: "default_asset_class", label: "Default Asset Class" },
  { key: "active_strategy", label: "Active Strategy" },
  { key: "daily_pnl", label: "Daily P/L", fmt: (v) => `$${(v || 0).toFixed(2)}` },
  { key: "trades_today", label: "Trades Today" },
  { key: "max_daily_loss", label: "Max Daily Loss", fmt: (v) => `$${v || 0}` },
  { key: "open_positions", label: "Open Positions" },
  { key: "alpaca_credentials_configured", label: "Alpaca Credentials", fmt: (v) => (v ? "Configured" : "Missing") },
  { key: "live_trading_enabled", label: "Live Trading", fmt: (v) => (v ? "Enabled" : "Disabled") },
];

export default function Dashboard() {
  const { data, error, refresh } = usePolling(() => get("/api/bot/status"), 5000);
  const { data: orb } = usePolling(() => get("/api/orb/status"), 8000);

  const val = (c) => {
    if (!data) return "—";
    const raw = data[c.key];
    if (c.fmt) return c.fmt(raw);
    return raw ?? "None";
  };

  return (
    <PageShell
      title="Dashboard"
      description="Bot status, execution mode, and daily risk summary."
      actions={<RefreshBtn onClick={refresh} />}
    >
      {error && <ErrorState message={error} onRetry={refresh} />}
      {!data && !error && <LoadingState />}
      {data && (
        <div className="card-grid">
          {CARDS.map((c) => (
            <div className="card" key={c.key}>
              <div className="card-label">
                {c.label} <Tooltip text={TIPS[c.key]} />
              </div>
              <div className="card-value">{String(val(c))}</div>
            </div>
          ))}
        </div>
      )}

      {orb && (data?.active_strategy === "stocks_in_play_orb_v1" || orb.candidate_count > 0 || orb.proposal_count > 0) && (
        <div className="section">
          <div className="section-title">Stocks In Play ORB v1</div>
          <div className="card-grid">
            <div className="card">
              <div className="card-label">Candidates <Tooltip text="In-play symbols ranked by relative volume." /></div>
              <div className="card-value">{orb.candidate_count}</div>
            </div>
            <div className="card">
              <div className="card-label">Pending Proposals</div>
              <div className="card-value">{orb.proposal_count}</div>
            </div>
            <div className="card">
              <div className="card-label">Rejected Signals</div>
              <div className="card-value">{orb.rejected_count}</div>
            </div>
            <div className="card">
              <div className="card-label">Session</div>
              <div className="card-value" style={{ fontSize: "0.8rem" }}>
                {orb.session?.entry_window || "—"}
              </div>
            </div>
          </div>
        </div>
      )}

      {data?.asset_classes && (
        <div className="section">
          <div className="section-title">Asset Classes</div>
          <div className="card-grid">
            {data.asset_classes.map((a) => (
              <div className="card" key={a.asset_class}>
                <div className="card-label">{a.asset_class}</div>
                <div className="card-value" style={{ fontSize: "0.85rem" }}>
                  {a.enabled ? "Enabled" : "Disabled"} / {a.live_enabled ? "Live" : "Live Off"}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </PageShell>
  );
}
