import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import Tooltip from "../components/Tooltip";
import { get } from "../api";

export default function DataSources() {
  const [sources, setSources] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setError(null);
    try {
      const d = await get("/api/datasources");
      setSources(d.datasources || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <PageShell title="Data Sources" description="Alpaca market data capabilities and credential state.">
      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}

      {!loading && !error && sources.length === 0 && (
        <EmptyState message="No data sources returned from API." />
      )}

      {!loading && !error && sources.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Source</th>
                <th>Type</th>
                <th>Supported</th>
                <th>Configured</th>
                <th>Fields</th>
                <th>Info</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.key}>
                  <td>{s.label}</td>
                  <td>{s.type}</td>
                  <td><span className={`status-badge ${s.supported ? "on" : "off"}`}>{s.supported ? "Yes" : "No"}</span></td>
                  <td><span className={`status-badge ${s.configured ? "on" : "warn"}`}>{s.configured ? "Yes" : "No"}</span></td>
                  <td>{s.fields?.length > 0 ? s.fields.map((f) => f.name).join(", ") : "None required"}</td>
                  <td><Tooltip text={s.tooltip} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {!loading && !error && sources[0]?.capabilities && (
        <div className="section">
          <div className="section-title">Capabilities</div>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Asset</th><th>Historical Bars</th><th>Live Bars</th><th>Quotes</th><th>Trades</th><th>Minute</th><th>Daily</th><th>Readiness</th></tr></thead>
              <tbody>
                {Object.entries(sources[0].capabilities).map(([asset, caps]) => (
                  <tr key={asset}>
                    <td>{asset}</td>
                    <td>{caps.historical_bars ? "Yes" : "No"}</td>
                    <td>{caps.live_bars ? "Yes" : "No"}</td>
                    <td>{caps.quotes ? "Yes" : "No"}</td>
                    <td>{caps.trades ? "Yes" : "No"}</td>
                    <td>{caps.minute ? "Yes" : "—"}</td>
                    <td>{caps.daily ? "Yes" : "—"}</td>
                    <td>{caps.orb_compatible ? "ORB compatible" : caps.readiness || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </PageShell>
  );
}
