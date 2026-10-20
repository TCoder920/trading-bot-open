import { Routes, Route, NavLink } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import BotControl from "./pages/BotControl";
import Strategies from "./pages/Strategies";
import Orb from "./pages/Orb";
import Watchlist from "./pages/Watchlist";
import RiskSettings from "./pages/RiskSettings";
import Orders from "./pages/Orders";
import Trades from "./pages/Trades";
import Backtesting from "./pages/Backtesting";
import DataSources from "./pages/DataSources";
import Alpaca from "./pages/Alpaca";
import AssetClasses from "./pages/AssetClasses";
import Options from "./pages/Options";
import Crypto from "./pages/Crypto";
import ProductionReadiness from "./pages/ProductionReadiness";
import Logs from "./pages/Logs";
import Settings from "./pages/Settings";
import ErrorBoundary from "./components/ErrorBoundary";
import "./App.css";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/bot", label: "Bot Control" },
  { to: "/strategies", label: "Strategies" },
  { to: "/orb", label: "ORB Strategy" },
  { to: "/watchlist", label: "Watchlist" },
  { to: "/risk", label: "Risk Settings" },
  { to: "/orders", label: "Orders" },
  { to: "/trades", label: "Trades" },
  { to: "/backtesting", label: "Backtesting" },
  { to: "/alpaca", label: "Alpaca" },
  { to: "/assets", label: "Asset Classes" },
  { to: "/options", label: "Options" },
  { to: "/crypto", label: "Crypto" },
  { to: "/readiness", label: "Readiness" },
  { to: "/datasources", label: "Data Sources" },
  { to: "/logs", label: "Logs" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  return (
    <div className="app-layout">
      <nav className="sidebar">
        <div className="sidebar-title">Trading Bot</div>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end className="nav-link">
            {n.label}
          </NavLink>
        ))}
      </nav>
      <main className="main-content">
        <ErrorBoundary>
          <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/bot" element={<BotControl />} />
          <Route path="/strategies" element={<Strategies />} />
          <Route path="/orb" element={<Orb />} />
          <Route path="/watchlist" element={<Watchlist />} />
          <Route path="/risk" element={<RiskSettings />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/trades" element={<Trades />} />
          <Route path="/backtesting" element={<Backtesting />} />
          <Route path="/alpaca" element={<Alpaca />} />
          <Route path="/assets" element={<AssetClasses />} />
          <Route path="/options" element={<Options />} />
          <Route path="/crypto" element={<Crypto />} />
          <Route path="/readiness" element={<ProductionReadiness />} />
          <Route path="/datasources" element={<DataSources />} />
          <Route path="/logs" element={<Logs />} />
          <Route path="/settings" element={<Settings />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
