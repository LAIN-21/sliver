import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router";

import { useSession } from "../session";
import type { Account } from "../types";
import SellerAgreementGate from "./SellerAgreementGate";

export default function RequireAccount({ children }: { children: (account: Account) => ReactNode }) {
  const { account } = useSession();
  const location = useLocation();
  if (account === undefined) return <p className="text-muted">Loading…</p>;
  if (account === null) {
    return <Navigate to={`/sell/login?next=${encodeURIComponent(location.pathname)}`} replace />;
  }
  if (account.role === "seller") {
    return (
      <SellerAgreementGate key={`${account.id}:${location.pathname}`}>
        {children(account)}
      </SellerAgreementGate>
    );
  }
  return <>{children(account)}</>;
}
