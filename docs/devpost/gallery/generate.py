"""Generates the Devpost gallery SVGs in one shared HackUTD Zero Day style."""
import sys
from html import escape
from pathlib import Path

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1500, 1000
BG, PANEL, LINE, TEXT, MUTED = "#07060d", "#110d1f", "#2b2348", "#f4f2ff", "#a69fc4"
C = {
    "purple": "#9b6bff", "teal": "#4fe3a8", "coral": "#ff5c7c", "amber": "#ffc857",
    "blue": "#8fa8ff", "gray": "#8a84a8", "pink": "#f08bff",
}
FONT = "Inter, 'Helvetica Neue', Arial, sans-serif"
MONO = "'IBM Plex Mono', Menlo, monospace"


class Svg:
    def __init__(self, title, subtitle):
        self.parts = []
        self.add(f'<rect width="{W}" height="{H}" fill="{BG}"/>')
        self.add(f'<rect width="{W}" height="{H}" fill="url(#glow)"/>')
        self.text(60, 82, title.upper(), 44, TEXT, weight=800, italic=True, spacing=1.5)
        self.text(60, 124, subtitle, 21, MUTED)
        self.text(W - 60, H - 30, "HACKUTD 2026 · ZERO DAY COMMAND CENTER", 15, "#5c5680",
                  anchor="end", weight=700, spacing=2)

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, size, fill, weight=400, anchor="start", italic=False, spacing=0, mono=False):
        st = ' font-style="italic"' if italic else ""
        ls = f' letter-spacing="{spacing}"' if spacing else ""
        self.add(f'<text x="{x}" y="{y}" font-family="{MONO if mono else FONT}" font-size="{size}" '
                 f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{st}{ls}>{escape(s)}</text>')

    def box(self, x, y, w, h, title, lines=(), color="purple", dashed=False, mono_lines=False, title_size=24):
        c = C[color]
        dash = ' stroke-dasharray="8 6"' if dashed else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{c}" fill-opacity="0.10" '
                 f'stroke="{c}" stroke-width="2"{dash}/>')
        n = len(lines)
        block = title_size + n * 26
        ty = y + (h - block) / 2 + title_size * 0.85
        self.text(x + w / 2, ty, title, title_size, TEXT, weight=700, anchor="middle")
        for i, ln in enumerate(lines):
            self.text(x + w / 2, ty + 32 + i * 26, ln, 18, MUTED, anchor="middle", mono=mono_lines)

    def container(self, x, y, w, h, label, color="gray", sub=None):
        c = C[color]
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="22" fill="{PANEL}" fill-opacity="0.6" '
                 f'stroke="{c}" stroke-width="2" stroke-dasharray="10 8"/>')
        self.text(x + 24, y + 38, label.upper(), 20, c, weight=800, spacing=1.5)
        if sub:
            self.text(x + w - 24, y + 38, sub, 17, MUTED, anchor="end")

    def arrow(self, pts, color=LINE, label=None, lx=None, ly=None, both=False, dashed=False, width=2.5):
        d = "M" + " L".join(f"{x} {y}" for x, y in pts)
        col = C.get(color, color)
        mk = "a-" + col.strip("#")
        dash = ' stroke-dasharray="9 7"' if dashed else ""
        start = f' marker-start="url(#{mk})"' if both else ""
        self.add(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="{width}"{dash} '
                 f'marker-end="url(#{mk})"{start}/>')
        if label:
            self.pill(lx, ly, label, col)

    def pill(self, x, y, s, col, size=16):
        w = len(s) * size * 0.56 + 24
        self.add(f'<rect x="{x - w / 2}" y="{y - size}" width="{w}" height="{size * 1.7}" rx="{size * 0.85}" '
                 f'fill="{BG}" stroke="{col}" stroke-width="1.5"/>')
        self.text(x, y + size * 0.3, s, size, col, weight=700, anchor="middle")

    def save(self, name):
        markers = "".join(
            f'<marker id="a-{c.strip("#")}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M1 1L9 5L1 9z" fill="{c}"/></marker>'
            for c in [LINE, *C.values()])
        defs = (f'<defs>{markers}<radialGradient id="glow" cx="50%" cy="0%" r="70%">'
                f'<stop offset="0" stop-color="#7828ff" stop-opacity="0.22"/>'
                f'<stop offset="1" stop-color="#7828ff" stop-opacity="0"/></radialGradient></defs>')
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
               + defs + "".join(self.parts) + "</svg>")
        (OUT / f"{name}.svg").write_text(svg)


# 1 ── System overview ────────────────────────────────────────────────────────
s = Svg("System overview", "The command center runs off the attacked box; the GPU cluster is the data center under attack.")
s.container(60, 170, 560, 520, "My laptop (off-box)", "purple")
s.box(100, 230, 220, 140, "Attacker app", ["3D hacker laptop", "judges click attacks"], "coral")
s.box(100, 400, 220, 140, "Operator console", ["dashboard, approvals,", "war room, records"], "purple")
s.box(360, 230, 220, 420, "Backend", ["FastAPI + live SSE", "attack chain", "rule-based Detector", "3 Nemotron agents",
                                       "policy gate", "approvals + record", "SQLite history"], "blue")
s.arrow([(320, 300), (356, 300)], "coral")
s.arrow([(320, 470), (356, 470)], "purple", both=True)
s.container(880, 170, 560, 520, "Brev GPU VM", "teal", "AWS g4dn.xlarge · Tesla T4")
s.box(920, 230, 480, 90, "k3s Kubernetes API :6443", [], "teal")
s.box(920, 345, 230, 150, "lawfirm", ["model-server · training", "notebook · weights"], "teal")
s.box(1170, 345, 230, 150, "platform", ["gpu-telemetry", "notebook-edge · agent IDs"], "purple")
s.box(920, 515, 230, 150, "drop-site", ["drop (stolen files)", "sink (DDoS victim)"], "coral")
s.box(1170, 515, 230, 150, "kube-system", ["GPU plugin:", "1 T4 → 8 slots"], "gray")
s.arrow([(580, 275), (916, 275)], "teal", both=True, label="Tailscale tunnel", lx=750, ly=252)
s.text(750, 312, "WireGuard · private", 16, MUTED, anchor="middle")
s.add(f'<path d="M470 650 L470 760" stroke="{C["blue"]}" stroke-width="2.5" fill="none"/>')
s.add(f'<path d="M270 760 L1230 760" stroke="{C["blue"]}" stroke-width="2.5" fill="none"/>')
for x in (270, 750, 1230):
    s.arrow([(x, 760), (x, 806)], "blue")
s.box(60, 810, 420, 110, "NVIDIA Nemotron 3", ["Ultra + Nano, tool calling"], "purple")
s.box(540, 810, 420, 110, "NVD + CoinGecko", ["CVE lookup · mining cost"], "blue")
s.box(1020, 810, 420, 110, "Cartesia voice", ["phones on-call for approvals"], "amber")
s.save("01-system-overview")

# 2 ── Inside the Brev VM ─────────────────────────────────────────────────────
s = Svg("Inside the Brev VM", "One rented AWS GPU VM running single-node k3s: the law firm, the operator, the attacker's servers.")
s.container(60, 160, 1380, 785, "Brev VM: hackutd-gpu", "teal", "Ubuntu · NVIDIA driver · Tailscale 100.106.83.89")
# left: GPU time-slicing + layer stack
s.add(f'<rect x="100" y="215" width="420" height="235" rx="14" fill="{C["purple"]}" fill-opacity="0.10" '
      f'stroke="{C["purple"]}" stroke-width="2"/>')
s.text(310, 254, "GPU time-slicing", 24, TEXT, weight=700, anchor="middle")
s.text(310, 282, "one Tesla T4 advertised as 8 slots", 18, MUTED, anchor="middle")
slots = [("model", "teal"), ("train", "teal"), ("smi", "purple"), ("miner", "coral")] + [("", "gray")] * 4
for i, (lab, col) in enumerate(slots):
    x = 122 + i * 48
    s.add(f'<rect x="{x}" y="310" width="40" height="56" rx="6" fill="{C[col]}" '
          f'fill-opacity="{0.55 if lab else 0.08}" stroke="{C[col]}" stroke-width="1.5"/>')
    if lab:
        s.text(x + 20, 388, lab, 13, MUTED, anchor="middle")
s.text(310, 428, "pods take turns · no isolation", 18, C["amber"], anchor="middle", weight=700)
layers = [("k3s (single-node Kubernetes)", "teal"), ("Tailscale (private network)", "teal"),
          ("NVIDIA container toolkit", "gray"), ("Ubuntu + NVIDIA driver", "gray"),
          ("4 vCPU · 16 GB RAM · Tesla T4 16 GB", "purple")]
for i, (lab, col) in enumerate(layers):
    s.box(100, 480 + i * 90, 420, 76, lab, [], col, title_size=21)
# right: namespaces
def ns(x, y, name, color, pods, sub=None):
    s.container(x, y, 410, 340, name, color, sub)
    for i, (t, d, pc, dashed) in enumerate(pods):
        by = y + 60 + i * 68
        dash = ' stroke-dasharray="8 6"' if dashed else ""
        s.add(f'<rect x="{x + 20}" y="{by}" width="370" height="58" rx="12" fill="{C[pc]}" fill-opacity="0.10" '
              f'stroke="{C[pc]}" stroke-width="2"{dash}/>')
        s.text(x + 40, by + 36, t, 19, TEXT, weight=700)
        s.text(x + 372, by + 35, d, 15, MUTED, anchor="end")
ns(560, 215, "lawfirm", "teal", [("model-server", "GPU · serves model", "teal", False),
                                  ("training", "GPU · fine-tune", "teal", False),
                                  ("notebook", "Jupyter, no auth", "coral", False),
                                  ("model-weights", "PVC · 288 MB", "teal", True)], "victim")
ns(1000, 215, "platform", "purple", [("gpu-telemetry", "GPU · nvidia-smi", "purple", False),
                                       ("notebook-edge", "socat → tailnet", "purple", False),
                                       ("agent-readonly", "identity: look", "blue", True),
                                       ("agent-executor", "identity: fix", "blue", True)], "operator")
ns(560, 575, "drop-site", "coral", [("drop", "receives stolen files", "coral", False),
                                     ("sink", "DDoS victim", "coral", False)], "attacker")
s.text(765, 850, "ClusterIP only: nothing leaves the VM", 17, C["coral"], anchor="middle", weight=700)
ns(1000, 575, "kube-system", "gray", [("nvidia-device-plugin", "8 GPU slots", "gray", False),
                                       ("coredns", "cluster DNS", "gray", False),
                                       ("local-path", "volumes on disk", "gray", False),
                                       ("metrics-server", "CPU / memory", "gray", False)], "k3s plumbing")
s.save("02-inside-the-brev-vm")

# 3 ── The attack path ────────────────────────────────────────────────────────
s = Svg("The attack path", "Judges click a step; Python runs inside the hijacked notebook and calls Kubernetes with its stolen token.")
xs = [60, 340, 620, 900, 1180]
row1 = [("Attacker laptop", ["judge clicks a step"], "coral"),
        ("Backend", ["writes a Python cell"], "blue"),
        ("notebook-edge", ["tailnet → Jupyter :8888"], "purple"),
        ("Jupyter kernel", ["no auth · runs in pod"], "coral"),
        ("Stolen token", ["mounted SA token"], "coral")]
for x, (t, l, c) in zip(xs, row1):
    s.box(x, 190, 240, 120, t, l, c)
for a, b in zip(xs, xs[1:]):
    s.arrow([(a + 240, 250), (b - 4, 250)], "coral")
s.arrow([(1300, 310), (1300, 376)], "coral")
s.box(1180, 380, 240, 130, "k3s API server", ["RBAC: notebook-dev", "create pods ✓ cronjobs ✓"], "teal")
s.add(f'<path d="M1300 510 L1300 570 L190 570" stroke="{C["coral"]}" stroke-width="2.5" fill="none"/>')
objs = [("Miner pod", ["asks for 1 GPU", "process named xmrig"]),
        ("Exfil pod", ["mounts model-weights", "PUTs file to drop"]),
        ("CronJob", ["“log-rotate”", "every minute"]),
        ("DDoS pod", ["≤200 conns, 20 s", "hard-coded target"])]
oxs = [60, 350, 640, 930]
for x, (t, l) in zip(oxs, objs):
    s.arrow([(x + 130, 570), (x + 130, 606)], "coral")
    s.box(x, 610, 260, 130, t, l, "coral")
effects = [("T4 pinned ~100%", "training slows"), ("288 MB at drop", "model stolen"),
           ("Miner respawns", "survives cleanup"), ("Sink flooded", "egress spike")]
for x, (t, l) in zip(oxs, effects):
    s.arrow([(x + 130, 740), (x + 130, 786)], "gray")
    s.box(x, 790, 260, 110, t, [l], "gray")
s.box(1240, 610, 200, 290, "Kill switch", ["defender deletes", "RoleBinding", "notebook-dev", "", "every call →", "403 Forbidden"], "teal")
s.pill(340, 440, "1. Gain access steals the badge", C["coral"], 18)
s.pill(340, 490, "2–5. Every attack = “API server, create this”", C["coral"], 18)
s.save("03-attack-path")

# 4 ── The defender pipeline ──────────────────────────────────────────────────
s = Svg("The defender pipeline", "Rules raise the alarm; three Nemotron agents investigate and contain; the cluster is re-checked.")
stages = [("Detector", ["plain code, every 4 s", "unknown pod", "weights mount", "rogue CronJob", "GPU spike"], "gray"),
          ("Triage", ["Nemotron 3 Nano", "severity, phase,", "category", "look-only", "6 rounds"], "purple"),
          ("Investigator", ["Nemotron 3 Nano", "hypotheses + evidence", "CVE via NVD", "mining $ via CoinGecko", "8 rounds"], "purple"),
          ("Advisor", ["Nemotron 3 Ultra", "ranked containment", "can consult", "the Investigator", "8 rounds"], "coral"),
          ("Verify", ["re-run detection", "anything respawned?", "send Advisor back", "max 2 passes", ""], "teal")]
for x, (t, l, c) in zip(xs, stages):
    s.box(x, 200, 240, 260, t, l, c)
for (a, b), lab in zip(zip(xs, xs[1:]), ["alert", "handoff", "handoff", "check"]):
    s.arrow([(a + 240, 330), (b - 4, 330)], "purple", label=lab, lx=(a + 240 + b) / 2, ly=300)
s.arrow([(1300, 460), (1300, 520), (1020, 520), (1020, 464)], "teal", dashed=True,
        label="still rogue → re-converge", lx=1160, ly=522)
s.container(60, 590, 1380, 330, "How every agent works", "purple")
cards = [("Rounds", ["model asks for tools", "backend runs them, feeds back", "last round: tools withheld,", "must answer"]),
         ("Handoffs", ["each agent's summary", "is pasted into the next", "agent's instructions", "(visible as traces)"]),
         ("Scoped tools", ["per-agent allowlists:", "Triage + Investigator only look", "Advisor alone can act", "temperature 0"]),
         ("Outputs", ["live timeline + traces", "scope board", "NIST SP 800-61 record", "approval cards"])]
for i, (t, l) in enumerate(cards):
    s.box(90 + i * 335, 650, 310, 240, t, l, ["blue", "purple", "teal", "amber"][i])
s.save("04-defender-pipeline")

# 5 ── Guardrails ─────────────────────────────────────────────────────────────
s = Svg("Guardrails: who can change what", "The AI only asks; the backend decides; a human signs off on anything that touches real work.")
s.box(60, 190, 240, 130, "Advisor", ["Nemotron asks for", "a tool call"], "coral")
s.box(340, 190, 240, 130, "Tool allowlist", ["only the Advisor", "gets write tools"], "teal")
s.box(620, 190, 240, 130, "classify()", ["safe or risky?", "unknown → risky"], "teal")
s.arrow([(300, 255), (336, 255)], "teal")
s.arrow([(580, 255), (616, 255)], "teal")
s.box(1180, 190, 240, 130, "Executor identity", ["1-hour token", "narrow RBAC"], "blue")
s.arrow([(860, 255), (1176, 255)], "teal", label="safe & reversible: run now", lx=1018, ly=228)
s.arrow([(740, 320), (740, 416)], "amber", label="risky", lx=740, ly=370)
s.box(620, 420, 240, 120, "Pending approval", ["parked, not run"], "gray")
s.arrow([(860, 480), (896, 480)], "amber")
s.box(900, 420, 240, 120, "Cartesia call", ["phones the on-call", "engineer"], "amber")
s.arrow([(740, 540), (740, 616)], "amber")
s.box(620, 620, 240, 120, "Human approves", ["console button,", "role-checked"], "amber")
s.arrow([(860, 680), (1300, 680), (1300, 324)], "amber")
s.arrow([(1380, 320), (1380, 816)], "blue")
s.box(1180, 820, 240, 110, "k3s API", ["RBAC has the last word"], "teal")
s.container(60, 400, 520, 530, "Two scoped identities", "blue")
s.box(90, 460, 460, 190, "agent-readonly", ["get / list / watch everywhere", "pods, logs, nodes, jobs, policies", "no secrets, no writes"], "blue")
s.box(90, 670, 460, 230, "agent-executor", ["delete pods · quarantine pods", "delete CronJobs · cordon node",
                                              "delete exactly ONE RoleBinding:", "notebook-dev"], "blue")
s.text(60, 968, "The admin kubeconfig never leaves the backend; the AI only ever holds these two scoped tokens.", 17, MUTED)
s.save("05-guardrails")

# 6 ── The three mistakes ─────────────────────────────────────────────────────
s = Svg("Three mistakes, one breach", "The demo's vulnerabilities are real ones. Any single fix would have stopped the attack.")
mistakes = [("1. Jupyter, no auth", ["token='' , password=''", "anyone who reaches :8888", "runs code in the pod"],
             "Fix: SSO / JupyterHub"),
            ("2. Token mounted", ["Kubernetes leaves the", "pod's identity on disk", "readable by any code"],
             "Fix: automount: false"),
            ("3. Role too broad", ["notebook-dev may create", "pods, jobs, cronjobs", "in the law firm's namespace"],
             "Fix: least privilege")]
mx = [60, 420, 780]
for x, (t, l, fix) in zip(mx, mistakes):
    s.box(x, 220, 320, 260, t, l, "coral")
    s.box(x, 530, 320, 90, fix, [], "teal", title_size=21)
    s.arrow([(x + 160, 480), (x + 160, 526)], "teal", dashed=True)
for a, b in zip(mx, mx[1:]):
    s.arrow([(a + 320, 350), (b - 4, 350)], "coral")
s.arrow([(1100, 350), (1136, 350)], "coral")
s.box(1140, 220, 300, 400, "= namespace takeover", ["create any pod:", "• grab a GPU slot", "• mount the weights",
                                                      "• plant a CronJob", "", "create pods ≈ own", "the namespace"], "coral")
s.container(60, 680, 1380, 240, "Also missing", "amber")
extra = [("Separate namespace", ["notebooks can't mount", "lawfirm's volumes"]),
         ("Admission policy", ["block foreign volumes,", "images, privileged pods"]),
         ("GPU ResourceQuota", ["cap slots per", "namespace"])]
for i, (t, l) in enumerate(extra):
    s.box(100 + i * 450, 740, 400, 150, t, l, "amber")
s.save("06-three-mistakes")
print("ok")

# 7 ── The law firm under attack (Winstead) ───────────────────────────────────
s = Svg("The law firm under attack", "Winstead PC: synthetic workloads running for real on a Tesla T4, tracked on the scope board.")
s.text(90, 205, "WHAT THE FIRM RUNS ON ITS GPU CLUSTER", 18, C["teal"], weight=800, spacing=1.5)
s.text(840, 205, "SCOPE BOARD AFTER THE ATTACK", 18, C["coral"], weight=800, spacing=1.5)
rows = [
    ("Contracts AI", "model-server · real PyTorch inference on the T4,", "standing in for the firm's contract model", "teal",
     "● Clean", "kept serving the whole time;", "the defender never touched it", "teal"),
    ("Fine-tuning job", "training · a live GPU training loop", "(forward, backprop, optimizer steps)", "teal",
     "● Clean", "slowed while the miner stole GPU time,", "recovered once it was killed", "teal"),
    ("Research notebook", "notebook · where analysts prototype;", "open Jupyter = the way in", "amber",
     "◐ → ◆ Investigating, then contained", "entry point: its stolen identity", "was revoked (with human approval)", "blue"),
    ("Model weights", "contracts-ft-v3.pt · a real 288 MB checkpoint", "standing in for the firm's IP", "coral",
     "▲ Exfiltrated", "302 MB left to the attacker's server;", "72-hour notification clock starts", "coral"),
]
for i, (t, l1, l2, c, st, n1, n2, sc) in enumerate(rows):
    y = 230 + i * 172
    s.box(90, y, 620, 140, t, [l1, l2], c)
    s.arrow([(710, y + 70), (836, y + 70)], sc)
    s.box(840, y, 600, 140, st, [n1, n2], sc)
s.save("07-law-firm-under-attack")

# 8 ── Winstead brief → what I built ────────────────────────────────────────
s = Svg("Winstead brief, built", "Each required component of the cyber incident response dashboard, and how the command center delivers it.")
reqs = [
    ("01 Secure & isolated", ["runs off the attacked cluster · own login, HttpOnly session", "an attacker who owns the cluster can't erase the record or approve"]),
    ("02 Access control", ["admins add people and set roles: admin · approver ·", "responder · operator · viewer, enforced on the server"]),
    ("03 Incident documentation", ["NIST SP 800-61 record filled live by agents + team · PDF export", "breach-notification countdowns: 72-hour clock on exfiltration"]),
    ("04 Scope definitions", ["clean · investigating · exfiltrated · encrypted/locked · contained", "with evidence, e.g. “302 MB left to the attacker's server”"]),
    ("05 Real-time comms", ["out-of-band war room chat · plain-English Briefing for partners", "Cartesia phones the on-call engineer when a decision waits"]),
]
for i, (t, ls) in enumerate(reqs):
    y = 170 + i * 124
    s.box(60, y, 400, 104, t, [], "amber", title_size=23)
    s.arrow([(460, y + 52), (496, y + 52)], "amber")
    s.add(f'<rect x="500" y="{y}" width="940" height="104" rx="14" fill="{C["purple"]}" fill-opacity="0.10" '
          f'stroke="{C["purple"]}" stroke-width="2"/>')
    for j, ln in enumerate(ls):
        s.text(970, y + 44 + j * 32, ln, 20, TEXT if j == 0 else MUTED, anchor="middle")
crit = [("Security", ["assume the attacker owns", "everything inside"], "teal"),
        ("Ease of use", ["one band: what to do now", "one-click Approve / Deny"], "blue"),
        ("Creativity", ["judges attack it live;", "AI fills in the record"], "pink")]
for i, (t, ls, c) in enumerate(crit):
    s.box(60 + i * 470, 805, 440, 130, t, ls, c)
s.save("08-winstead-brief-built")
print("ok")
