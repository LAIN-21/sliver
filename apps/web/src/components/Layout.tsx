import { useEffect, useRef } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router";

import { useSession } from "../session";
import HealthBadge from "./HealthBadge";
import { ExchangeIcon, SliverMark } from "./ExchangeIcons";

const INSIGHTS = { to: "/sell/insights", label: "Insights", end: false };

const NAV = [
  { to: "/", label: "Marketplace", end: true },
  { to: "/sell", label: "Sell data", end: false },
  { to: "/activity", label: "Activity", end: false },
];

export default function Layout() {
  const { account, logout } = useSession();
  const { pathname, hash } = useLocation();
  const previousPath = useRef(pathname);
  const nav =
    account?.role === "seller"
      ? [...NAV.slice(0, 2), INSIGHTS, ...NAV.slice(2)]
      : NAV;
  // "Sell data" covers /sell/*, except the insights page, which has its own entry.
  const onInsights = pathname.startsWith(INSIGHTS.to);
  useEffect(() => {
    if (!hash) {
      // A query edit can clear an anchor. Only a page navigation resets the
      // viewport; marketplace filters deliberately keep the results in view.
      if (previousPath.current !== pathname)
        window.scrollTo({ top: 0, behavior: "instant" });
      previousPath.current = pathname;
      return;
    }
    previousPath.current = pathname;
    const frame = requestAnimationFrame(() =>
      document.getElementById(hash.slice(1))?.scrollIntoView(),
    );
    return () => cancelAnimationFrame(frame);
  }, [pathname, hash]);
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <header className="app-header">
        <div className="app-header-inner">
          <NavLink to="/" className="brand-lockup" aria-label="Sliver home">
            <SliverMark />
            <span>
              sliver<span className="brand-period">.</span>
            </span>
          </NavLink>
          <nav aria-label="Main" className="app-nav">
            {nav.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  `nav-link ${
                    isActive && !(item.to === "/sell" && onInsights)
                      ? "is-active"
                      : ""
                  }`
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          {account ? (
            <div className="account-nav">
              <span>
                {account.display_name}{" "}
                <span className="text-xs">({account.role})</span>
              </span>
              <button type="button" onClick={() => void logout()}>
                Sign out
              </button>
            </div>
          ) : (
            <Link className="header-action" to="/sell/login">
              Seller sign in <ExchangeIcon name="arrow" size={16} />
            </Link>
          )}
          <span className="network-indicator">
            <i />
            XRPL TESTNET
          </span>
        </div>
      </header>
      <main
        id="main-content"
        tabIndex={-1}
        className={`app-main ${pathname === "/" ? "marketplace-main" : "workspace-main"}`}
      >
        <Outlet />
      </main>
      <footer className="app-footer">
        <div className="app-footer-top">
          <Link to="/" className="brand-lockup" aria-label="Sliver home">
            <SliverMark />
            <span>sliver.</span>
          </Link>
          <p>
            Good answers start
            <br />
            with the right data.
          </p>
          <div>
            <Link to="/">Marketplace</Link>
            <Link to="/sell">Sell your data</Link>
            <Link to="/activity">Activity</Link>
          </div>
        </div>
        <div className="app-footer-bottom">
          <span>XRPL Testnet demonstration. No real funds.</span>
          <HealthBadge />
          <span>Data, by the slice.</span>
        </div>
      </footer>
    </div>
  );
}
