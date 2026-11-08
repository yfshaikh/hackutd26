import { lazy, Suspense, useEffect } from "react";
import { TopBar } from "./components/TopBar";
import { Empty } from "./components/Empty";
import { LiveProvider, SessionProvider, useSession } from "./context";
import { CommandCenter } from "./pages/CommandCenter";
import { Evals } from "./pages/Evals";
import { IncidentPage } from "./pages/IncidentPage";
import { Login } from "./pages/Login";
import { Runbooks } from "./pages/Runbooks";
import { Users } from "./pages/Users";
import { navigate, usePath } from "./router";

const FloorPage = lazy(() => import("./pages/FloorPage").then((m) => ({ default: m.FloorPage })));

/** The judges' attack panel moved to its own app (port 5180). This dashboard is defender-only. */
const ATTACKER_APP_URL = (import.meta.env.VITE_ATTACKER_URL as string | undefined) || "http://localhost:5180";

const TITLES: Record<string, string> = {
  "/": "Operator console",
  "/floor": "Floor",
  "/evals": "Evaluations",
  "/record": "Incident record",
  "/runbooks": "Runbooks",
  "/users": "Users & roles",
  "/attack": "Attacker workstation",
};

function AttackMoved() {
  useEffect(() => {
    const t = setTimeout(() => window.location.replace(ATTACKER_APP_URL), 1200);
    return () => clearTimeout(t);
  }, []);
  return (
    <Empty title="The attacker has its own workstation now">
      <span>Taking you to {ATTACKER_APP_URL}. This dashboard is for the defender.</span>
      <a className="btn btn-primary" href={ATTACKER_APP_URL}>Open the attacker workstation</a>
    </Empty>
  );
}

function Signed({ path }: { path: string }) {
  return (
    <LiveProvider>
      <div className="shell">
        <TopBar />
        {path === "/users" ? (
          <Users />
        ) : path === "/evals" ? (
          <Evals />
        ) : path === "/record" ? (
          <IncidentPage />
        ) : path === "/runbooks" ? (
          <Runbooks />
        ) : path === "/floor" ? (
          <Suspense fallback={<Empty title="Loading the floor…" />}>
            <FloorPage />
          </Suspense>
        ) : (
          <CommandCenter />
        )}
      </div>
    </LiveProvider>
  );
}

function Routes() {
  const path = usePath();
  const { status } = useSession();

  useEffect(() => {
    document.title = `${TITLES[path] ?? "Command center"}`;
    if (!(path in TITLES)) navigate("/");
  }, [path]);

  // The attacker now lives in its own app; /attack just points there (no sign-in needed).
  if (path === "/attack") return <AttackMoved />;
  if (status !== "signed-in") return <Login />;
  return <Signed path={path} />;
}

export function App() {
  return (
    <SessionProvider>
      <Routes />
    </SessionProvider>
  );
}
