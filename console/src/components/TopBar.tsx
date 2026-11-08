import { useState } from "react";
import { useLive, useSession } from "../context";
import { incidentStatus, PHASES } from "../labels";
import type { IncidentPhase } from "../types";
import { Link } from "../router";
import { applyTheme, loadTheme, type ThemePref } from "../theme";

const CONN = {
  live: { label: "Live", tone: "clean" },
  connecting: { label: "Connecting", tone: "invest" },
  lost: { label: "Disconnected", tone: "exfil" },
} as const;

const NEXT_THEME: Record<ThemePref, ThemePref> = { system: "dark", dark: "light", light: "system" };
const THEME_LABEL: Record<ThemePref, string> = { system: "Theme: system", dark: "Theme: dark", light: "Theme: light" };
const THEME_ICON: Record<ThemePref, string> = { system: "◐", dark: "☾", light: "☀" };

/** NIST SP 800-61 phase track; shown in the status band. */
export function PhaseTrack({ phase }: { phase: IncidentPhase }) {
  const idx = PHASES.findIndex((p) => p.id === phase);
  return (
    <ol className="phases" aria-label="Incident phase">
      {PHASES.map((p, i) => (
        <li key={p.id} className={i < idx ? "done" : i === idx ? "now" : ""} aria-current={i === idx ? "step" : undefined}>
          {p.label}
        </li>
      ))}
    </ol>
  );
}

export function TopBar() {
  const { connection, snapshot } = useLive();
  const { user, signOut } = useSession();
  const [theme, setTheme] = useState<ThemePref>(loadTheme);
  const record = snapshot?.record ?? null;
  const c = CONN[connection];

  return (
    <header className="topbar">
      <div className="brand">
        <img src="/mascots/logo.png" alt="" />
        <strong>NMC <em>// zero day</em></strong>
        <span>
          {snapshot
            ? `Client: ${snapshot.firm} · Cluster ${snapshot.cluster.name}`
            : "Client incident response"}
        </span>
      </div>
      <nav className="nav" aria-label="Main">
        <Link href="/">Command center</Link>
        <Link href="/floor">Floor</Link>
        <Link href="/evals">Evals</Link>
        {user?.role === "admin" && <Link href="/users">Users</Link>}
      </nav>
      <div className="topbar-right">
        {record && (
          <span className={`chip t-${incidentStatus(record.status).tone}`}>{incidentStatus(record.status).label}</span>
        )}
        <span className={`conn t-${c.tone}`} role="status">{c.label}</span>
        <button
          className="btn btn-ghost btn-icon"
          title={THEME_LABEL[theme]}
          aria-label={THEME_LABEL[theme]}
          onClick={() => {
            const n = NEXT_THEME[theme];
            setTheme(n);
            applyTheme(n);
          }}
        >
          {THEME_ICON[theme]}
        </button>
        {user && (
          <span className="whoami">
            <strong>{user.name}</strong> {user.role}
          </span>
        )}
        <button className="btn" onClick={signOut}>Sign out</button>
      </div>
    </header>
  );
}
