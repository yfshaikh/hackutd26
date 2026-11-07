// Live dashboard state: one SSE subscription, reduced into a Snapshot.
// Nothing here invents data. Until the server sends a snapshot, state is null.

import { useCallback, useEffect, useMemo, useReducer } from "react";
import { subscribe } from "./api";
import type { ConnectionState, ServerEvent, Snapshot, TimelineEntry } from "./types";

export interface LiveState {
  connection: ConnectionState;
  snapshot: Snapshot | null;
  /** The most recent attack event, used to flash where it hit. */
  lastAttack: TimelineEntry | null;
  /** Apply a server response locally (e.g. the Approval returned by POST approve). */
  apply: (e: ServerEvent) => void;
}

type Action = { kind: "event"; event: ServerEvent } | { kind: "connection"; state: ConnectionState };

function upsert<T>(list: T[], item: T, key: (t: T) => string): T[] {
  const k = key(item);
  const i = list.findIndex((x) => key(x) === k);
  if (i === -1) return [...list, item];
  const next = list.slice();
  next[i] = item;
  return next;
}

export function applyEvent(snap: Snapshot | null, e: ServerEvent): Snapshot | null {
  if (e.type === "snapshot") return e.snapshot;
  if (!snap) return snap; // deltas before a snapshot are meaningless
  switch (e.type) {
    case "timeline":
      return { ...snap, timeline: upsert(snap.timeline, e.entry, (t) => t.id) };
    case "asset":
      return { ...snap, assets: upsert(snap.assets, e.asset, (a) => a.id) };
    case "approval":
      return { ...snap, approvals: upsert(snap.approvals, e.approval, (a) => a.id) };
    case "record":
      return { ...snap, record: e.record };
    case "cluster":
      return { ...snap, cluster: e.cluster };
    case "attack":
      return { ...snap, attack: e.attack };
  }
}

type Core = Omit<LiveState, "apply">;

function reducer(s: Core, a: Action): Core {
  if (a.kind === "connection") return { ...s, connection: a.state };
  const lastAttack =
    a.event.type === "timeline" && a.event.entry.kind === "attack" ? a.event.entry : s.lastAttack;
  return { ...s, snapshot: applyEvent(s.snapshot, a.event), lastAttack };
}

export function useLiveState(): LiveState {
  const [state, dispatch] = useReducer(reducer, {
    connection: "connecting",
    snapshot: null,
    lastAttack: null,
  });
  useEffect(
    () =>
      subscribe(
        (event) => dispatch({ kind: "event", event }),
        (s) => dispatch({ kind: "connection", state: s }),
      ),
    [],
  );
  const apply = useCallback((event: ServerEvent) => dispatch({ kind: "event", event }), []);
  return useMemo(() => ({ ...state, apply }), [state, apply]);
}
