import { NavLink, Outlet } from "react-router";

import { useSession } from "../session";
import HealthBadge from "./HealthBadge";

const NAV = [
  { to: "/", label: "Marketplace", end: true },
  { to: "/sell", label: "Sell data", end: false },
  { to: "/activity", label: "Activity", end: false },
];

export default function Layout() {
  const { account, logout } = useSession();
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-3 px-4 py-4 sm:px-6">
          <NavLink to="/" className="flex items-baseline gap-2" aria-label="Sliver home">
            <span className="text-xl font-semibold tracking-tight">Sliver</span>
            <span className="hidden text-sm text-muted sm:inline">data agents can buy by the slice</span>
          </NavLink>
          <nav aria-label="Main" className="flex gap-1">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `rounded-md px-3 py-2 text-sm font-medium ${
                    isActive ? "bg-brand-soft text-brand" : "text-muted hover:bg-surface hover:text-ink"
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          {account ? (
            <div className="ml-auto flex items-center gap-3 text-sm">
              <span className="text-muted">
                {account.display_name} <span className="text-xs">({account.role})</span>
              </span>
              <button type="button" onClick={() => void logout()} className="font-medium text-brand hover:underline">
                Sign out
              </button>
            </div>
          ) : null}
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-10 sm:px-6">
        <Outlet />
      </main>
      <footer className="border-t border-line bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3 px-4 py-4 text-sm text-muted sm:px-6">
          <span>Local demo on XRPL Testnet. No real funds.</span>
          <HealthBadge />
        </div>
      </footer>
    </div>
  );
}
