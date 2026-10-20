import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import RefreshBtn from "../components/RefreshBtn";
import { get } from "../api";

export default function AssetClasses() {
  const [classes, setClasses] = useState([]);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setError(null);
    try {
      const d = await get("/api/assets/classes");
      setClasses(d.asset_classes || []);
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
    <PageShell title="Asset Classes" description="Stocks drive the autonomous loop today. All asset classes are traded only by strategies (no manual trading in the bot); options and crypto have the full strategy-facing execution rails plus managed TP/SL. The Options and Crypto pages are reference + quick-settings views. Live trading is disabled by default per class." actions={<RefreshBtn onClick={load} />}>
      {loading && <LoadingState />}
      {error && !loading && <ErrorState message={error} onRetry={load} />}
      {!loading && !error && (
        <div className="table-wrap">
          <table>
            <thead><tr><th>Asset Class</th><th>Enabled</th><th>Paper</th><th>Live</th><th>Explicit</th><th>Approval</th><th>Ready</th><th>Errors</th></tr></thead>
            <tbody>
              {classes.map((c) => (
                <tr key={c.asset_class}>
                  <td>{c.asset_class}</td>
                  <td>{c.enabled ? "Yes" : "No"}</td>
                  <td>{c.paper_enabled ? "Yes" : "No"}</td>
                  <td>{c.live_enabled ? "Yes" : "No"}</td>
                  <td>{c.explicit_enablement ? "Yes" : "No"}</td>
                  <td>{c.asset_class === "options" ? (c.account_approved ? "Approved" : c.approval_status || "Pending") : "—"}</td>
                  <td><span className={`status-badge ${c.ready ? "on" : "warn"}`}>{c.ready ? "Ready" : "Blocked"}</span></td>
                  <td style={{ fontSize: "0.75rem" }}>{(c.errors || []).join("; ") || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}
