import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, getSession, logout as apiLogout } from "./api";
import { useLiveState, type LiveState } from "./store";
import type { User } from "./types";

const LiveCtx = createContext<LiveState | null>(null);

/** One SSE connection for the whole app. Mounted only after sign-in. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const live = useLiveState();
  return <LiveCtx.Provider value={live}>{children}</LiveCtx.Provider>;
}

export function useLive(): LiveState {
  const v = useContext(LiveCtx);
  if (!v) throw new Error("useLive outside LiveProvider");
  return v;
}

export interface SessionState {
  /** "checking" while GET /auth/me is in flight. */
  status: "checking" | "signed-in" | "signed-out" | "offline";
  user: User | null;
  setUser: (u: User) => void;
  signOut: () => void;
  retry: () => void;
}

const SessionCtx = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionState["status"]>("checking");
  const [user, setUserState] = useState<User | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let alive = true;
    getSession()
      .then((s) => {
        if (!alive) return;
        setUserState(s.user);
        setStatus("signed-in");
      })
      .catch((e) => {
        if (!alive) return;
        setStatus(e instanceof ApiError && e.kind === "network" ? "offline" : "signed-out");
      });
    return () => {
      alive = false;
    };
  }, [attempt]);

  const setUser = useCallback((u: User) => {
    setUserState(u);
    setStatus("signed-in");
  }, []);
  const signOut = useCallback(() => {
    apiLogout().catch(() => undefined);
    setUserState(null);
    setStatus("signed-out");
  }, []);
  const retry = useCallback(() => {
    setStatus("checking");
    setAttempt((n) => n + 1);
  }, []);

  return (
    <SessionCtx.Provider value={{ status, user, setUser, signOut, retry }}>{children}</SessionCtx.Provider>
  );
}

export function useSession(): SessionState {
  const v = useContext(SessionCtx);
  if (!v) throw new Error("useSession outside SessionProvider");
  return v;
}
