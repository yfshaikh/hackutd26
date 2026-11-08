// The incident record as a full page: a case switcher (live + archived incidents from
// GET /incidents) above the case file. If the history route isn't there, only "Live" shows.

import { useCallback, useEffect, useState } from "react";
import { errorText, getIncident, listIncidents } from "../api";
import { Empty } from "../components/Empty";
import { IncidentRecord } from "../components/IncidentRecord";
import { ScopeBoard } from "../components/ScopeBoard";
import { useLive } from "../context";
import { dateTime } from "../format";
import type { IncidentHistoryDetail, IncidentHistoryItem } from "../types";

export function IncidentPage() {
  const { snapshot } = useLive();
  const live = snapshot?.record ?? null;

  const [history, setHistory] = useState<IncidentHistoryItem[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [archived, setArchived] = useState<IncidentHistoryDetail | null>(null);
  const [archiveErr, setArchiveErr] = useState<string | null>(null);

  // Reload when the live incident changes too: a resolved one gets banked.
  useEffect(() => {
    listIncidents().then(setHistory).catch(() => setHistory([]));
  }, [live?.id, live?.status]);

  const open = useCallback(async (id: string | null) => {
    setOpenId(id);
    setArchived(null);
    setArchiveErr(null);
    if (!id) return;
    try {
      setArchived(await getIncident(id));
    } catch (e) {
      setOpenId(null);
      setArchiveErr(errorText(e));
    }
  }, []);

  // The live incident is also in history once archived; don't list it twice.
  const past = history.filter((h) => h.id !== live?.id);

  return (
    <main className="page incident-page">
      <nav className="case-switch" aria-label="Incidents">
        <button type="button" aria-pressed={openId === null} onClick={() => open(null)}>
          <span className="case-switch-dot" aria-hidden /> Live incident
        </button>
        {past.map((h) => (
          <button key={h.id} type="button" aria-pressed={h.id === openId} onClick={() => open(h.id)}>
            {h.title}
            <span className="case-switch-when">{dateTime(h.resolved_at ?? h.detected_at ?? undefined)}</span>
          </button>
        ))}
      </nav>

      {archiveErr && <div className="notice t-exfil" role="alert">{archiveErr}</div>}

      {openId !== null ? (
        archived ? <IncidentRecord record={archived.record} readOnly /> : <Empty title="Loading the archived incident…" />
      ) : snapshot && !live ? (
        <section className="panel">
          <Empty title="No incident yet">
            <span>The record opens by itself when the defender detects an attack on the cluster.</span>
          </Empty>
        </section>
      ) : (
        <IncidentRecord aside={<ScopeBoard />} />
      )}
    </main>
  );
}
