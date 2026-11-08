// Spec 02: the NIST SP 800-61 incident record is a full page, not a cramped side tab.
//
// The live record arrives over SSE with the snapshot. Past incidents come from the
// separate history read path (Spec 03, GET /incidents); if that path isn't there yet
// the page quietly shows only the current incident.

import { useCallback, useEffect, useState } from "react";
import { errorText, getIncident, listIncidents } from "../api";
import { Empty } from "../components/Empty";
import { IncidentRecord } from "../components/IncidentRecord";
import { ScopeBoard } from "../components/ScopeBoard";
import { SeverityChip } from "../components/Status";
import { useLive } from "../context";
import { clock, dateTime } from "../format";
import { incidentStatus } from "../labels";
import type { IncidentHistoryDetail, IncidentHistoryItem, RecordAction } from "../types";

/** The record's actionsTaken list, promoted out of the field grid: ts · by · text. */
function ActionsTaken({ actions }: { actions: RecordAction[] }) {
  return (
    <section className="panel actions-panel" aria-labelledby="actions-h">
      <div className="panel-head">
        <h2 id="actions-h">Actions taken</h2>
        <span className="aside">
          {actions.length === 0
            ? "nothing recorded yet"
            : `${actions.length} ${actions.length === 1 ? "action" : "actions"}`}
        </span>
      </div>
      {actions.length === 0 ? (
        <Empty title="No actions yet">Agents and responders add to this as they act.</Empty>
      ) : (
        <ol className="action-list">
          {actions.map((a, i) => (
            <li className="action-item" key={`${a.ts}-${i}`}>
              <time className="action-ts mono" dateTime={a.ts}>{clock(a.ts)}</time>
              <span className="action-by">{a.by}</span>
              <span className="action-text">{a.text}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

/** Past incidents, newest first. Renders nothing when there is no history backend. */
function History({
  rows,
  openId,
  onOpen,
}: {
  rows: IncidentHistoryItem[];
  openId: string | null;
  onOpen: (id: string) => void;
}) {
  if (rows.length === 0) return null;
  return (
    <section className="panel history-panel" aria-labelledby="history-h">
      <div className="panel-head">
        <h2 id="history-h">Past incidents</h2>
        <span className="aside">{rows.length} archived</span>
      </div>
      <div className="history-list">
        {rows.map((h) => (
          <button
            key={h.id}
            type="button"
            className={`history-item${h.id === openId ? " is-open" : ""}`}
            aria-pressed={h.id === openId}
            onClick={() => onOpen(h.id)}
          >
            <span className="history-title">{h.title}</span>
            <span className="history-meta">
              <span className={`chip t-${incidentStatus(h.status).tone}`}>{incidentStatus(h.status).label}</span>
              <SeverityChip severity={h.severity} />
              <span className="mono">{dateTime(h.resolved_at ?? h.detected_at ?? undefined)}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function IncidentPage() {
  const { snapshot } = useLive();
  const live = snapshot?.record ?? null;

  const [history, setHistory] = useState<IncidentHistoryItem[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [archived, setArchived] = useState<IncidentHistoryDetail | null>(null);
  const [loadingArchive, setLoadingArchive] = useState(false);
  const [archiveErr, setArchiveErr] = useState<string | null>(null);

  // Graceful degradation: no /incidents route (or no DB yet) just means an empty list.
  const loadHistory = useCallback(() => {
    listIncidents()
      .then(setHistory)
      .catch(() => setHistory([]));
  }, []);

  // Reload when the live incident changes too: a resolved one gets banked.
  useEffect(() => {
    loadHistory();
  }, [loadHistory, live?.id, live?.status]);

  const open = useCallback(async (id: string) => {
    setOpenId(id);
    setArchived(null);
    setArchiveErr(null);
    setLoadingArchive(true);
    try {
      setArchived(await getIncident(id));
    } catch (e) {
      setArchived(null);
      setOpenId(null);
      setArchiveErr(errorText(e));
    } finally {
      setLoadingArchive(false);
    }
  }, []);

  const backToLive = () => {
    setOpenId(null);
    setArchived(null);
    setArchiveErr(null);
  };

  const viewingArchive = archived !== null;
  const shown = archived?.record ?? live;
  const closedAt = archived ? archived.resolved_at ?? archived.record.closedAt ?? archived.record.updatedAt : null;

  return (
    <main className="page incident-page">
      <div className="incident-head">
        <div>
          <h1>Incident</h1>
          <p className="lede">
            The NIST SP 800-61 record for this incident: what happened, what we did, and
            what is left. Kept in the operator console, off the attacked cluster.
          </p>
        </div>
      </div>

      <History rows={history} openId={openId} onOpen={open} />

      {archiveErr && <div className="notice t-exfil" role="alert">{archiveErr}</div>}

      {viewingArchive && archived && (
        <div className="archived-banner" role="status">
          <span>
            <strong>Viewing an archived incident.</strong> {archived.title}
            {closedAt ? ` · closed ${dateTime(closedAt)}` : ""}
          </span>
          <button className="btn" onClick={backToLive}>Back to live incident</button>
        </div>
      )}

      {loadingArchive ? (
        <Empty title="Loading the archived incident…" />
      ) : !shown ? (
        !snapshot ? (
          <IncidentRecord />
        ) : (
          <section className="panel">
            <Empty title="No incident yet">
              <span>The record opens by itself when the defender detects an attack on the cluster.</span>
            </Empty>
          </section>
        )
      ) : (
        <div className={`incident-grid${viewingArchive ? " is-archive" : ""}`}>
          <div className="incident-main">
            <ActionsTaken actions={shown.actionsTaken} />
            <IncidentRecord record={archived?.record} readOnly={viewingArchive} showActions={false} />
          </div>
          {!viewingArchive && (
            <aside className="incident-side">
              <ScopeBoard />
            </aside>
          )}
        </div>
      )}
    </main>
  );
}
