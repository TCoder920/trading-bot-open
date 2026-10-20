import Tooltip from "../components/Tooltip";
import RefreshBtn from "../components/RefreshBtn";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import usePolling from "../hooks/usePolling";
import { get, post } from "../api";

const STATES = {
  stopped: "Bot is not running.",
  running_simulation: "Bot is running in local simulation mode.",
  running_paper: "Bot is running autonomously on Alpaca PAPER.",
  running_live: "Bot is running autonomously on Alpaca LIVE.",
  paused: "Bot is paused and not processing signals.",
  backtesting: "A backtest is in progress.",
  error: "Bot encountered an error.",
};

export default function BotControl() {
  const { data, error, refresh } = usePolling(() => get("/api/bot/status"), 3000);

  const action = async (path) => {
    try {
      await post(`/api/bot/${path}`);
      refresh();
    } catch (e) {
      // refresh will show latest state; polling hook captures errors on next fetch
    }
  };

  const state = data?.bot_state || "stopped";
  const running = state.startsWith("running");

  return (
    <PageShell
      title="Bot Control"
      description="Start, pause, stop the autonomous loop, monitor the kill switch and trading session, and reset the daily ledger."
      actions={<RefreshBtn onClick={refresh} />}
    >
      {error && <ErrorState message={error} onRetry={refresh} />}
      {!data && !error && <LoadingState />}

      {data && (
        <>
          <div className="section">
            <div className="info-row">
              <span className="info-label">Status <Tooltip text="Current bot process state." /></span>
              <span className={`status-badge ${state === "stopped" ? "off" : "on"}`}>{state}</span>
            </div>
            <div className="info-row">
              <span className="info-label">Description</span>
              <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>{STATES[state] || state}</span>
            </div>
          </div>

          <div className="section">
            <div className="section-title">Actions</div>
            <div className="btn-row">
              <button className="btn" onClick={() => action("start")} disabled={running}>Start</button>
              <button className="btn" onClick={() => action("pause")} disabled={!running}>Pause</button>
              <button className="btn" onClick={() => action("resume")} disabled={state !== "paused"}>Resume</button>
              <button className="btn" onClick={() => action("stop")} disabled={state === "stopped"}>Stop</button>
              <button className="btn" onClick={() => action("tick")}>Run One Tick</button>
              <button className="btn" onClick={() => action("ledger/reset")}>Reset Daily Ledger</button>
            </div>
          </div>

          <div className="section">
            <div className="section-title">Autonomous Loop</div>
            <div className="info-row">
              <span className="info-label">Kill Switch <Tooltip text="Halts all new order submissions when the daily-loss limit or another safety condition is breached." /></span>
              <span className={`status-badge ${data.kill_switch_active ? "warn" : "on"}`}>
                {data.kill_switch_active ? "ACTIVE" : "Clear"}
              </span>
            </div>
            {data.kill_switch_active && data.kill_switch_reasons?.length > 0 && (
              <div className="info-row">
                <span className="info-label">Kill Switch Reasons</span>
                <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                  {data.kill_switch_reasons.join(", ")}
                </span>
              </div>
            )}
            <div className="info-row">
              <span className="info-label">Scheduler</span>
              <span className={`status-badge ${data.scheduler?.state === "running" ? "on" : "off"}`}>
                {data.scheduler?.state || "stopped"}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Current Session</span>
              <span>{data.session || "—"}</span>
            </div>
            <div className="info-row">
              <span className="info-label">Extended Hours</span>
              <span className={`status-badge ${data.allow_extended_hours ? "warn" : "off"}`}>
                {data.allow_extended_hours ? "Allowed" : "RTH only"}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Last Tick</span>
              <span style={{ color: "var(--text-muted)", fontSize: "0.85rem" }}>
                {data.scheduler?.last_tick_at || "—"} ({data.scheduler?.tick_count ?? 0} ticks)
              </span>
            </div>
          </div>

          <div className="section">
            <div className="section-title">Safety Status</div>
            <div className="info-row">
              <span className="info-label">Live Trading</span>
              <span className={`status-badge ${data.live_trading_enabled ? "warn" : "off"}`}>
                {data.live_trading_enabled ? "ENABLED" : "Disabled"}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Execution Mode</span>
              <span>{data.trading_mode || "—"}</span>
            </div>
            <div className="info-row">
              <span className="info-label">Alpaca Broker</span>
              <span className={`status-badge ${data.alpaca_enabled ? "on" : "off"}`}>
                {data.alpaca_enabled ? "Enabled" : "Disabled"}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Alpaca Credentials</span>
              <span className={`status-badge ${data.alpaca_credentials_configured ? "on" : "warn"}`}>
                {data.alpaca_credentials_configured ? "Configured" : "Missing"}
              </span>
            </div>
            <div className="info-row">
              <span className="info-label">Paper Mode</span>
              <span>{data.paper ? "Yes" : "No"}</span>
            </div>
          </div>
        </>
      )}
    </PageShell>
  );
}
