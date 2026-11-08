/**
 * Two-sided framing: the law firm is the client running the AI jobs; NMC is the
 * operator protecting them. The console itself runs off the attacked box.
 */
export function Framing() {
  return (
    <details className="framing">
      <summary>Who's who: client, operator, and why this console survives a breach</summary>
      <div className="framing-grid">
        <div className="frame-card client">
          <span className="frame-tag">Client</span>
          <strong>Halloran &amp; Vance LLP</strong>
          <span>
            Runs the AI workloads on the GPU cluster: model serving, fine-tuning and research
            notebooks. Their client data and model IP are what the attacker is after.
          </span>
        </div>
        <div className="frame-card operator">
          <span className="frame-tag">Operator</span>
          <strong>NMC · SOC</strong>
          <span>
            Monitors the cluster and protects the client's jobs. The defender agent proposes ranked
            fixes; the client's responders approve them.
          </span>
        </div>
        <div className="frame-card resilience">
          <span className="frame-tag">Compromise-resilient</span>
          <strong>Runs off the attacked box</strong>
          <span>
            The console, incident record and approval path live outside the cluster. A fully
            compromised cluster cannot erase the record or bypass a human decision.
          </span>
        </div>
      </div>
    </details>
  );
}
