// The signed-in seller or reviewer, shared by the seller pages and the header.

import { createContext, type ReactNode, useCallback, useContext, useEffect, useState } from "react";

import { getAccount, signIn, signOut } from "./api";
import type { Account } from "./types";

type Session = {
  // undefined while the first /auth/me request is in flight.
  account: Account | null | undefined;
  login: (email: string, password: string) => Promise<Account>;
  logout: () => Promise<void>;
};

const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<Account | null | undefined>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    getAccount(controller.signal)
      .then(setAccount)
      .catch((error: unknown) => {
        if (!(error instanceof DOMException && error.name === "AbortError")) setAccount(null);
      });
    return () => controller.abort();
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const signedIn = await signIn(email, password);
    setAccount(signedIn);
    return signedIn;
  }, []);

  const logout = useCallback(async () => {
    await signOut().catch(() => undefined);
    setAccount(null);
  }, []);

  return <SessionContext value={{ account, login, logout }}>{children}</SessionContext>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession must be used inside SessionProvider");
  return session;
}
