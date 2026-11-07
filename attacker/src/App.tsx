import { lazy, Suspense, useState } from "react";
import Terminal from "./Terminal";

const Scene = lazy(() => import("./Scene"));
const reduced = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

// closed: the desk scene · opening: lid + camera animation · open: the terminal overlay
export default function App() {
  const [stage, setStage] = useState<"closed" | "opening" | "open">(reduced ? "open" : "closed");
  return (
    <div className="app">
      {stage !== "open" && (
        <Suspense fallback={<div className="loading">Loading the desk…</div>}>
          <Scene opening={stage === "opening"} onOpen={() => setStage("opening")} onOpened={() => setStage("open")} />
        </Suspense>
      )}
      {stage === "closed" && (
        <p className="hint">An attacker's laptop. Open it to start.</p>
      )}
      {stage === "open" && (
        <div className="screen-in">
          <Terminal onClose={() => setStage(reduced ? "open" : "closed")} />
        </div>
      )}
    </div>
  );
}
