import type { ReactNode } from "react";
import { API_URL } from "../api";
import { Link } from "../router";
import type { ConnectionState } from "../types";

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty" role="status">
      <strong>{title}</strong>
      {children}
    </div>
  );
}

/** Shown in any panel that has no snapshot yet. Never shows placeholder data. */
export function NoData({ connection, what }: { connection: ConnectionState; what: string }) {
  if (connection === "connecting")
    return <Empty title={`Connecting to the command center…`}>{what} appears once it answers.</Empty>;
  return (
    <Empty title="Not connected to the command center">
      <span>
        Tried <code>{API_URL}</code>. {what} appears when it is back. Retrying automatically.
      </span>
    </Empty>
  );
}

export function NoIncident() {
  return (
    <Empty title="No incidents yet">
      <span>
        Launch an attack from the <Link href="/attack">attack panel</Link> to start one.
      </span>
    </Empty>
  );
}
