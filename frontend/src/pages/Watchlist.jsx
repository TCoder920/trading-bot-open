import { useCallback, useEffect, useState } from "react";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import Tooltip from "../components/Tooltip";
import { get, post, del } from "../api";

export default function Watchlist() {
  const [symbols, setSymbols] = useState([]);
  const [newSym, setNewSym] = useState("");
  const [error, setError] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoadError(null);
    try {
      const d = await get("/api/watchlist?asset_class=stocks");
      setSymbols(d.symbols || []);
    } catch (e) {
      setLoadError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const add = async () => {
    if (!newSym.trim()) return;
    setError(null);
    try {
      await post("/api/watchlist", { symbol: newSym.trim().toUpperCase(), asset_class: "stocks" });
      setNewSym("");
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const remove = async (sym) => {
    setError(null);
    try {
      await del("/api/watchlist", { symbol: sym, asset_class: "stocks" });
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  return (
    <PageShell
      title="Watchlist"
      description="Approved symbols for trading. Orders for symbols not on this list are rejected by the risk engine."
    >
      <div className="panel" style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <Tooltip text="Approved symbols for trading. Orders for symbols not on this list will be rejected by the risk engine." />
        <input
          className="form-input"
          style={{ width: 140 }}
          placeholder="SYMBOL"
          value={newSym}
          onChange={(e) => setNewSym(e.target.value.toUpperCase())}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
        <button className="btn" onClick={add}>Add</button>
        {error && <span className="error-banner">{error}</span>}
      </div>

      {loading && <LoadingState />}
      {loadError && !loading && <ErrorState message={loadError} onRetry={load} />}

      {!loading && !loadError && symbols.length === 0 && (
        <EmptyState message="Watchlist is empty. Add symbols to allow order proposals." />
      )}

      {!loading && !loadError && symbols.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Symbol</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {symbols.map((s) => (
                <tr key={s}>
                  <td>{s}</td>
                  <td><button className="btn btn-sm" onClick={() => remove(s)}>Remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageShell>
  );
}
