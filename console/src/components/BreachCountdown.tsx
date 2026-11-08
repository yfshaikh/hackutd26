import { dateTime, remaining } from "../format";
import { useNow } from "../hooks";
import type { NotificationDeadline } from "../types";

function toneFor(d: NotificationDeadline, overdue: boolean, msLeft: number): string {
  if (d.status === "met") return "clean";
  if (d.status === "overdue" || overdue) return "exfil";
  if (d.status === "due" || msLeft <= 24 * 3_600_000) return "high";
  return "contained";
}

/**
 * Live breach-notification clocks. One card per deadline; ticks every second.
 * Falls back to the legacy single `notificationDueAt` when no deadline list is set.
 */
export function BreachCountdown({
  deadlines,
  fallbackDueAt,
}: {
  deadlines: NotificationDeadline[];
  fallbackDueAt?: string;
}) {
  const now = useNow(1000);
  const list: NotificationDeadline[] =
    deadlines.length > 0
      ? deadlines
      : fallbackDueAt
        ? [{ label: "Client notification", dueAt: fallbackDueAt, status: "upcoming" }]
        : [];

  if (list.length === 0) {
    return (
      <p className="deadline-empty">
        No breach-notification deadline set. Add one in the record editor when client data leaves.
      </p>
    );
  }

  return (
    <div className="deadline-grid">
      {list.map((d, i) => {
        const r = remaining(d.dueAt, now);
        const tone = toneFor(d, r.overdue, r.ms);
        return (
          <div key={`${d.label}-${i}`} className={`deadline-card t-${tone}`}>
            <div className="deadline-top">
              <span className="deadline-label">{d.label}</span>
              {d.jurisdiction && <span className="tag mono">{d.jurisdiction}</span>}
            </div>
            <strong className="deadline-big">{d.status === "met" ? "Met" : r.text}</strong>
            <span className="deadline-when">
              Due {dateTime(d.dueAt)}
              {d.status === "met" ? " · notification sent" : ""}
            </span>
          </div>
        );
      })}
    </div>
  );
}
