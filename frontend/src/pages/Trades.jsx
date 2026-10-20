import RefreshBtn from "../components/RefreshBtn";
import PageShell from "../components/PageShell";
import LoadingState from "../components/LoadingState";
import ErrorState from "../components/ErrorState";
import EmptyState from "../components/EmptyState";
import usePolling from "../hooks/usePolling";
import { get } from "../api";

export default function Trades() {
  const { data: tradesData, error: tradesError, refresh: refreshTrades } = usePolling(() => get("/api/trades"), 10000);
  const { data: posData, error: posError, refresh: refreshPos } = usePolling(() => get("/api/positions"), 10000);

  const trades = tradesData?.trades || [];
  const positions = posData?.positions || [];
  const error = tradesError || posError;
  const loading = !tradesData && !posData && !error;

  const refresh = () => {
    refreshTrades();
    refreshPos();
  };

  return (
    <PageShell
      title="Trades & Positions"
      description="Recorded trades and open positions from simulation or Alpaca execution."
      actions={<RefreshBtn onClick={refresh} />}
    >
      {error && <ErrorState message={error} onRetry={refresh} />}
      {loading && <LoadingState />}

      {!loading && (
        <>
          <div className="section">
            <div className="section-title">Open Positions</div>
            {positions.length === 0 ? (
              <EmptyState message="No positions" />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Symbol</th><th>Qty</th><th>Avg Cost</th><th>Mkt Value</th><th>P/L</th><th>Source</th></tr>
                  </thead>
                  <tbody>
                    {positions.map((p, i) => (
                      <tr key={i}>
                        <td>{p.symbol}</td>
                        <td>{p.quantity}</td>
                        <td>{p.avg_cost ?? "—"}</td>
                        <td>{p.market_value ?? "—"}</td>
                        <td>{p.unrealised_pnl ?? "—"}</td>
                        <td>{p.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="section">
            <div className="section-title">Trade History</div>
            {trades.length === 0 ? (
              <EmptyState message="No trades recorded yet" />
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Time</th><th>Symbol</th><th>Side</th><th>Qty</th><th>Price</th><th>$</th><th>Strategy</th><th>P/L</th></tr>
                  </thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr key={t.id}>
                        <td style={{ fontSize: "0.75rem" }}>{t.timestamp?.slice(0, 19)}</td>
                        <td>{t.symbol}</td>
                        <td>{t.side}</td>
                        <td>{t.quantity}</td>
                        <td>{t.price}</td>
                        <td>{t.dollar_amount}</td>
                        <td>{t.strategy || "—"}</td>
                        <td>{t.pnl ?? "—"}</td>
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
