// All data access for the console goes through this file.
// It talks to the real command-center backend: REST for actions, SSE for live events.
// The contract (endpoints, event types, JSON shapes) is documented in ../API.md.
//
// Auth uses an HttpOnly session cookie set by POST /auth/login, so every request
// sends credentials and no token ever appears in a URL or in JS-readable storage.

import type {
  Approval,
  Asset,
  AssetStatus,
  AttackResult,
  AttackStep,
  AttackStepId,
  ConnectionState,
  EvalsResults,
  EvalsRunStatus,
  IncidentRecord,
  IncidentRecordPatch,
  NewUser,
  Role,
  RoleInfo,
  ServerEvent,
  Session,
  Snapshot,
  TimelineEntry,
  User,
} from "./types";

export const API_URL: string = (
  (import.meta.env.VITE_API_URL as string | undefined) || "http://localhost:8000"
).replace(/\/+$/, "");

export class ApiError extends Error {
  /** "network": backend unreachable. "http": backend answered with an error status. */
  readonly kind: "network" | "http";
  readonly status?: number;
  constructor(kind: "network" | "http", message: string, status?: number) {
    super(message);
    this.kind = kind;
    this.status = status;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(API_URL + path, {
      ...init,
      credentials: "include",
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new ApiError("network", `Not connected to the command center at ${API_URL}`);
  }
  if (!res.ok) {
    let detail = res.statusText || "Request failed";
    try {
      const body = (await res.json()) as { detail?: unknown; message?: unknown };
      const d = body.detail ?? body.message;
      if (typeof d === "string") detail = d;
    } catch {
      /* body was not JSON; keep statusText */
    }
    throw new ApiError("http", `${res.status} ${detail}`, res.status);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

// ---- Session -------------------------------------------------------------

export const getSession = () => request<Session>("/auth/me");
export const login = (email: string, password: string) =>
  post<Session>("/auth/login", { email, password });
export const logout = () => post<void>("/auth/logout");

// ---- Dashboard -----------------------------------------------------------

export const getSnapshot = () => request<Snapshot>("/snapshot");

export const approve = (id: string) =>
  post<Approval>(`/approvals/${encodeURIComponent(id)}/approve`);
export const deny = (id: string) =>
  post<Approval>(`/approvals/${encodeURIComponent(id)}/deny`);

export const sendMessage = (text: string) => post<TimelineEntry>("/messages", { text });

// ---- WS-B: incident record / scope / roles / chat -------------------------

export const getRecord = () => request<IncidentRecord | null>("/incident/record");
export const patchRecord = (body: IncidentRecordPatch) => patch<IncidentRecord>("/incident/record", body);

export const getScope = () => request<Asset[]>("/incident/scope");
export const patchScope = (assetId: string, status: AssetStatus, note?: string) =>
  patch<Asset>(`/incident/scope/${encodeURIComponent(assetId)}`, { status, note });

export const getMessages = () => request<TimelineEntry[]>("/messages");
export const listRoles = () => request<RoleInfo[]>("/roles");
export const setUserRole = (userId: string, role: Role) =>
  patch<User>(`/users/${encodeURIComponent(userId)}/role`, { role });

// ---- Attack panel (judges) ----------------------------------------------

export const getAttackSteps = () => request<AttackStep[]>("/attack");
export const runAttack = (step: AttackStepId) =>
  post<AttackResult>(`/attack/${encodeURIComponent(step)}`);
export const resetCluster = () => post<AttackResult>("/reset");

// ---- Users (admin) -------------------------------------------------------

export const listUsers = () => request<User[]>("/users");
export const addUser = (user: NewUser) => post<User>("/users", user);

// ---- WS-C: eval results --------------------------------------------------

/** Eval results, or null when none have been produced yet (backend returns 404 or {}). */
/** Start an eval run in the background; `started` is false if one is already in flight. */
export const runEvals = () => post<{ started: boolean } & EvalsRunStatus>("/defender/evals/run");
/** Live progress of a UI-triggered eval run; poll until `running` is false. */
export const evalsStatus = () => request<EvalsRunStatus>("/defender/evals/status");

export async function getEvals(): Promise<EvalsResults | null> {
  try {
    const data = await request<EvalsResults | Record<string, never>>("/defender/evals");
    return "runs" in data ? (data as EvalsResults) : null;
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

// ---- Live events ---------------------------------------------------------

/**
 * Subscribe to the server's event stream (GET /events, Server-Sent Events).
 * The server sends a `snapshot` event first on every (re)connect, then deltas.
 * EventSource reconnects on its own; we surface the connection state.
 * Returns an unsubscribe function.
 */
export function subscribe(
  onEvent: (e: ServerEvent) => void,
  onConnection: (s: ConnectionState) => void,
): () => void {
  onConnection("connecting");
  const es = new EventSource(API_URL + "/events", { withCredentials: true });
  es.onopen = () => onConnection("live");
  es.onerror = () => onConnection("lost");
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as ServerEvent);
    } catch {
      console.warn("Ignored malformed event from /events");
    }
  };
  return () => es.close();
}

export function errorText(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Something went wrong";
}
