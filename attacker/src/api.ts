// Everything the attacker app knows comes from the backend's /attack* routes (no auth: judges drive it).
// Shapes mirror backend/app/models.py (AttackStep, AttackResult) and backend/app/transcript.py.

export const API = (import.meta.env.VITE_API_URL as string | undefined) ?? "http://localhost:8000";

export type StepId = "gain-access" | "start-miner" | "steal-weights" | "persistence" | "ddos";
export type StepStatus = "locked" | "ready" | "running" | "done";

export interface AttackStep { id: StepId; label: string; description: string; status: StepStatus }
export interface AttackResult { ok: boolean; step: string; message: string; output?: string | null; attack: AttackStep[] }

export type EntryKind = "cmd" | "code" | "http" | "output" | "note";
export interface Entry {
  id: string; ts: string; step: string; kind: EntryKind; text: string;
  method?: string; url?: string; status?: number;
  [k: string]: unknown;
}

export interface Recon {
  jupyter: { reachable?: boolean; [k: string]: unknown };
  identity: { serviceAccount: string; namespace: string; rules: unknown };
  gpu: { total?: number; model?: string; utilization?: number; memUsedGiB?: number; memTotalGiB?: number; tempC?: number };
  target: string;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, init);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const getSteps = () => call<AttackStep[]>("/attack");
export const getRecon = () => call<Recon>("/attack/recon");
export const runStep = (id: StepId) => call<AttackResult>(`/attack/${id}`, { method: "POST" });
export const resetAll = () => call<AttackResult>("/reset", { method: "POST" });

type StreamMsg =
  | { type: "history"; entries: Entry[]; step: string }
  | { type: "transcript"; entry: Entry }
  | { type: "cleared" };

/** Live transcript over SSE. Returns an unsubscribe function. */
export function streamTranscript(on: {
  history: (e: Entry[]) => void; entry: (e: Entry) => void; cleared: () => void; connected: (ok: boolean) => void;
}): () => void {
  const es = new EventSource(API + "/attack/stream");
  es.onopen = () => on.connected(true);
  es.onerror = () => on.connected(false);
  es.onmessage = (m) => {
    const msg = JSON.parse(m.data) as StreamMsg;
    if (msg.type === "history") on.history(msg.entries);
    else if (msg.type === "transcript") on.entry(msg.entry);
    else if (msg.type === "cleared") on.cleared();
  };
  return () => es.close();
}
