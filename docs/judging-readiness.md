# Judging Readiness & "Wow" Plan — NVIDIA + Winstead

Scope/plan only (no code here). Grades the project against both rubrics **plus the judges'
own Discord clarifications**, then lays out concrete, scoped improvements. Another agent is
concurrently building evals-in-UI, two-way agent comms, and the floor restyle — this is
sequenced around that.

Legend: ✅ strong · 🟡 met, strengthenable · ⚠️ real gap.

---

## STATUS — built overnight (uncommitted, verified)

- **P0 ✅ built + verified live.** External-API tools added to the agent workflow (`backend/app/enrich.py`):
  `lookup_cve` (NVD) and `mining_impact` (CoinGecko), with offline fallbacks. In a live run the
  Investigator called `lookup_cve` and pulled **CVE-2023-48022 (CVSS 9.8)** into the incident. This
  closes the only real NVIDIA gap.
- **P1 ✅ built + verified.** Winstead repositioned as the **out-of-band war room**: login copy, an
  "⬡ Out-of-band" top-bar chip (tooltip: "attacker can see email/phones/files — but not this
  channel"), and the Chat tab is now **War room** ("email & phones are down — coordinate here").
- **P2 ✅ built + verified.** A headline **scoreboard** (`Scoreboard.tsx`, polling `/defender/metrics`):
  time-to-contain with **"N× faster than ~15m manual"**, autonomous vs approved actions, **GPU compute
  protected in $**, and human decision time. Backend `metrics()` now returns `$`, a manual baseline,
  and the speed-up multiplier.
- **P3 — intentionally left for the brainstorm.** The visible numbered Advisor plan + the deeper
  coordination features (stakeholder roster / presence / @mentions / "assign owner") are the
  "make-it-special" layer — better designed together than built blind overnight. See §3.

Everything above is **uncommitted** (for review) and typechecks; the backend is running the new code.

---

## 0. What the judges actually told us (read this first)

**Winstead (paraphrased from Discord):**
- *"Level of control unknown, but assume they can see normal comms. Ransomware has locked a
  substantial amount of data, even phones are down, email is sporadic."*
- *"Running inside vs outside compromised systems — we'll allow you to take a creative approach,
  it's up to you."*
- *"For comms, the assumption is **nobody has information**. There needs to be a way for
  stakeholders to communicate and coordinate over the issue."*

**The reframe this forces (our biggest "wow" lever):** the dashboard is **not** an incident-
reporting form. It is **the one trustworthy, out-of-band war room** during a breach — the
attacker can read email/Slack/phones, ransomware locked the files, and *nobody has information*.
Our product is where stakeholders (legal, IT, execs) **coordinate** when every normal channel is
compromised, and the **agent is the thing that actually produces the missing information**. We
already built the pieces; we need to **name this** and make the UI say it.

**NVIDIA (paraphrased):** *"Does multi-step require multiple agents, or can one agent decide the
workflow? → Both would be acceptable."* So our Triage→Investigator→Advisor team already
**exceeds** the bar. The only real gap is **external APIs**.

---

## 1. NVIDIA — "Use Nemotron Beyond a Chatbot"

| Criterion | Verdict | Evidence / plan |
|---|---|---|
| Beyond a chatbot | ✅ | Agents take real, policy-gated cluster actions (quarantine/delete/revoke). Model proposes, `classify()` decides. |
| Multi-step workflows | ✅ (exceeds) | `Triage → Investigator → Advisor` multi-agent pipeline, each a multi-tool loop; Advisor plans a ranked remediation. Judges said one agent would do — we have three. |
| Tool integration (external APIs) | ⚠️ **gap** | Agents call the **k8s API** (9 tools) — real tool use — but **nothing third-party**. This is the one thing to add. |
| Real-world applicability | ✅ | GPU cryptojacking + weights exfil is a real attack class; least-priv SA split is a real NMC² pattern. |

### Improvements
- **P0 — Add genuine external-API tools to the agent workflow** (the gap). Read-only lookup tools
  the Investigator calls mid-forensics:
  - **CVE / NVD lookup** on the exploited vector (exposed Jupyter / Ray → ShadowRay) — cite a real
    **CVE + CVSS** in the incident record.
  - **Threat-intel / IP-reputation** on the exfil destination — "is this host known-bad?"
  - Optional **GPU price** lookup → turns `gpuHoursSaved` into **$ saved**.
  Design: new read-only tools in `_tool_schemas` + `_RAW` (no approval — lookups); results flow into
  the record + timeline; keys in `.env.example` (never `.env`); **fail gracefully to a cached stub**
  so the demo works offline. ~half a day. **Highest NVIDIA value.**
- **P1 — Make the plan visible.** Advisor emits a **numbered remediation plan** before executing
  (step 1…N with rank / risk / approval-needed), rendered as a checklist that fills in as it runs.
  Turns the implicit pipeline into a visible "agent that plans and executes." (Overlaps the in-flight
  two-way-agent work.)

### Metrics we already track (the "measurable outcome")
`timeToContainSeconds`, `containmentActions` (autonomous vs approved), `meanTimeToApproveSeconds`,
`gpuHoursSaved`, `detectionCadenceSeconds`, plus the evals suite (9 metrics / 8 scenarios).
**Gap:** not surfaced as one headline number, no **manual baseline** to beat, no **$**/token figure.
→ **P2 below.**

---

## 2. Winstead — "Cyber Incident Response Dashboard"

**Bottom line: we meet all 5 required components and all 3 judging criteria. The win is to
reposition around the out-of-band war-room insight and add a few coordination "wow" features.**

| # | Component | Verdict | Evidence + where to push |
|---|---|---|---|
| 01 | Secure & Isolated | ✅ | Runs **off the compromised box**; least-priv SA split; in-memory token minting; per-agent tool scope in code; scrypt auth. **Push:** say it out loud in the UI ("secure channel, off the compromised network"). |
| 02 | Access Control | ✅ | Admin adds users; 5 server-enforced roles. **Push:** frame as "who's in the war room + what they may do." |
| 03 | Incident Documentation | ✅ | NIST 800-61 record, **auto-built by the agents**, real-time, PDF export. **Push:** the agent *writes the brief nobody else has*. |
| 04 | Scope Definitions | ✅ | Per-asset status from **real exfil evidence**; breach-deadline countdowns. |
| 05 | Real-Time Communications | 🟡 | Live timeline + role-gated chat. **This is now the headline, not a side tab** — see below. |

| Judging criterion | Verdict | Push |
|---|---|---|
| Security (attacker owns everything) | ✅ strong | Already our best axis; make the off-box/out-of-band story explicit. |
| Ease of Use (stressed, no tutorials) | 🟡 | Ranked "do #1 first," auto-record. **Push:** one obvious "what do I do now" affordance. |
| Creativity | ✅ strong | Live attacker-vs-defender, 3 agents, evals. |

### The Winstead "wow" plan (reposition + coordinate)
1. **Name the thesis in the product.** Login + header say: *"Out-of-band command center — isolated
   from the compromised network. Email, phones, and file shares are assumed hostile."* This directly
   answers the judges' scenario and the Security criterion.
2. **Promote comms from a tab to the spine.** The judges said comms = *stakeholders coordinating
   when nobody has information.* Make the war room feel like one:
   - **Stakeholder roster + presence** (who's online: legal, IT, exec) and **@mentions**.
   - **Action-linked messages** ("re: revoke_service_account — hold, legal reviewing").
   - **Assign an owner** to a decision/asset; a visible **who's-doing-what** board.
3. **The agent is the information source.** Since "nobody has information," surface the agent's
   findings as a plain-English **situation brief** the humans read first (not just a tool log).
4. **Ease-of-use under stress.** One primary "**Next action**" call-to-action; bigger approve/deny;
   less chrome (you already trimmed tabs).
5. **Resilience flex.** Show the dashboard keeps working with the cluster fully owned (it does —
   it's off-box). A small "channel secure ✓ / cluster: compromised" status.

---

## 3. Prioritized plan (what to build, in order)

| Pri | Item | Track | Effort | Why |
|---|---|---|---|---|
| **P0** | External-API tools (CVE + threat-intel + GPU price) in the agent workflow | NVIDIA | ~0.5 day | Closes the only real rubric gap; strongest "intelligent external APIs" story. |
| **P1** | Reposition Winstead as the **out-of-band war room** (login/header copy, comms promoted, agent "situation brief") | Winstead | ~0.5–1 day | Directly answers the judges' own scenario; biggest "wow" per hour. |
| **P2** | Headline **measurable outcome** tile: manual-baseline vs agent, `gpuHoursSaved`→$, per-incident cost/token | both | ~0.5 day | Quantifies the pitch; reuses P0's price API. |
| **P3** | Visible numbered **Advisor plan** + coordination extras (roster/presence/@mentions/owner) | both | ~0.5–1 day | Polishes multi-step + comms. |

**Recommended order:** P0 → P1 → P2 → P3. P0 and P1 are the two that move the needle with judges;
P2/P3 are force-multipliers. None of these conflict with the in-flight evals-in-UI / two-way-agent /
floor work.

## 4. Value-prop template, filled in
> When ransomware locks a law firm's data and the attacker can read their email and phones, the
> responders **have no trustworthy way to see what happened or coordinate a response**. Our
> out-of-band command center runs off the compromised network and puts a **Nemotron agent team**
> to work: it investigates the breach (enriched with live CVE + threat-intel lookups), writes the
> incident brief nobody else has, and proposes a ranked, policy-gated remediation a human approves —
> **cutting time-to-contain from minutes of manual work to ~seconds**, saving GPU-hours (and $) of
> mining, with every action logged to a NIST-standard record the whole war room can see.
