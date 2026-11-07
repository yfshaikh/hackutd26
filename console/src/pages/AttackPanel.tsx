// /attack: the judges' panel. Big buttons, no shell. Every button calls the real backend
// and shows exactly what it answered, or a clear error when it is down.

import { useCallback, useEffect, useState } from "react";
import { API_URL, ApiError, errorText, getAttackSteps, resetCluster, runAttack } from "../api";
import { Link } from "../router";
import type { AttackResult, AttackStep, AttackStepId } from "../types";

/** Button copy only. Status always comes from the backend. */
const STEPS: { id: AttackStepId; label: string; description: string }[] = [
  { id: "gain-access", label: "Gain access", description: "Log in to the exposed research notebook with a leaked token." },
  { id: "start-miner", label: "Start miner", description: "Run a disguised GPU miner inside the notebook pod." },
  { id: "steal-weights", label: "Steal weights", description: "Copy the firm's fine-tuned model weights off the cluster." },
  { id: "persistence", label: "Hide a way back in", description: "Plant a CronJob that reopens access every few minutes." },
];

type Outcome = { ok: true; result: AttackResult } | { ok: false; label: string; error: string; offline: boolean };

export function AttackPanel() {
  const [steps, setSteps] = useState<AttackStep[] | null>(null);
  const [offline, setOffline] = useState<string | null>(null);
  const [running, setRunning] = useState<AttackStepId | "reset" | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  const refresh = useCallback(() => {
    getAttackSteps()
      .then((s) => {
        setSteps(s);
        setOffline(null);
      })
      .catch((e) => setOffline(errorText(e)));
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  const fire = async (id: AttackStepId | "reset", label: string) => {
    setRunning(id);
    setOutcome(null);
    try {
      const result = id === "reset" ? await resetCluster() : await runAttack(id);
      setSteps(result.attack);
      setOutcome({ ok: true, result });
      setOffline(null);
    } catch (e) {
      const net = e instanceof ApiError && e.kind === "network";
      if (net) setOffline(errorText(e));
      setOutcome({ ok: false, label, error: errorText(e), offline: net });
    } finally {
      setRunning(null);
    }
  };

  const statusOf = (id: AttackStepId) => steps?.find((s) => s.id === id)?.status;

  return (
    <div className="attack-page">
      <main className="page stack">
        <div className="attack-head">
          <div>
            <h1>Attack panel</h1>
            <p className="lede">
              You are the attacker. Press the buttons in order and watch the defenders respond on the{" "}
              <Link href="/">command center</Link>. Each button runs a real step against our own cluster.
            </p>
          </div>
        </div>

        {offline && (
          <div className="notice t-exfil" role="alert">
            Not connected to the command center
            <p>
              Tried <code>{API_URL}</code>. Buttons will report an error until it is back.
            </p>
          </div>
        )}

        <ol className="steps">
          {STEPS.map((s) => {
            const st = statusOf(s.id);
            return (
              <li key={s.id} className={`step ${st ?? ""}`}>
                <button
                  disabled={running !== null || st === "locked" || st === "running" || st === "done"}
                  onClick={() => fire(s.id, s.label)}
                >
                  <span className="title">{s.label}</span>
                  <span className="desc">{s.description}</span>
                  {running === s.id && <span className="state">Running…</span>}
                  {running !== s.id && st === "running" && <span className="state">Running…</span>}
                  {st === "done" && <span className="state">Done</span>}
                  {st === "locked" && <span className="state" style={{ color: "var(--muted)" }}>Run the step before this first</span>}
                </button>
              </li>
            );
          })}
        </ol>

        <div className="reset-row">
          <button className="btn btn-lg" disabled={running !== null} onClick={() => fire("reset", "Reset")}>
            {running === "reset" ? "Resetting…" : "Reset the cluster"}
          </button>
          <span style={{ color: "var(--muted)" }}>Puts everything back for the next judge. Takes about 30 seconds.</span>
        </div>

        {outcome && (
          <section className="panel" aria-live="polite">
            <div className="panel-head">
              <h2>{outcome.ok ? (outcome.result.ok ? "Backend response" : "The backend refused this step") : `${outcome.label} failed`}</h2>
            </div>
            <div className="panel-body stack" style={{ gap: 10 }}>
              {outcome.ok ? (
                <>
                  <div className={`notice ${outcome.result.ok ? "t-clean" : "t-invest"}`}>{outcome.result.message}</div>
                  {outcome.result.output && <pre className="output">{outcome.result.output}</pre>}
                </>
              ) : (
                <div className="notice t-exfil">
                  {outcome.offline ? "Not connected to the command center" : "The backend returned an error"}
                  <p>{outcome.error}</p>
                </div>
              )}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
