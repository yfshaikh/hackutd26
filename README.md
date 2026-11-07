# HackUTD 2026: attacker vs. defender on real GPUs

A scripted attacker compromises a k3s GPU cluster running a law firm's private model. Nemotron defender agents
detect, contain, scope and document the attack from a command center that runs outside the cluster.
Judges play the attacker.

- **Explainer** (architecture, Kubernetes basics, progress): [HackUTD26 System Map](https://claude.ai/artifact/U8vejvt5z7uz58qVWnEgZW)
- **Design:** [docs/design-summary.md](docs/design-summary.md), with full reasoning in [docs/design-log.md](docs/design-log.md)

```
your Mac                         Brev box (AWS g4dn.xlarge, Tesla T4)        NVIDIA cloud
  console    :5173                 k3s (Kubernetes) API :6443                  Nemotron API
  backend    :8000  ──Tailscale──►  pods: lawfirm/*, platform/*, drop-site/*
  kubectl / k9s                     T4 shared as 8 time-sliced GPUs
```

| Folder | What it holds |
|---|---|
| `deploy/` | Kubernetes manifests: the GPU device plugin with time-slicing, and the law-firm workloads plus the drop site |
| `backend/` | FastAPI command center: API, real attack chain, detection, Nemotron defender, autonomy policy ([backend/README.md](backend/README.md)) |
| `console/` | React defender dashboard + 3D floor view ([console/README.md](console/README.md), API contract in [console/API.md](console/API.md)) |
| `attacker/` | The judges' attacker workstation: a 3D laptop that opens into a live attacker terminal (port 5180) |
| `docs/` | Design docs and the system-map source |

---

## Run it (cluster already set up)

You need **Tailscale** running on your Mac (the menu-bar icon shows connected) and the Brev box **running**.

**1. Check the cluster is reachable**

```bash
KUBECONFIG=~/.kube/hackutd.yaml kubectl get pods -A
```

You should see `lawfirm`: model-server, training, notebook. `platform`: gpu-telemetry. `drop-site`: drop.

**2. Create `backend/.env`** (first time only).

Copy the template from [backend/README.md](backend/README.md#backendenv-template). You need **one** key for Nemotron:

- **`OPENROUTER_API_KEY`**: from openrouter.ai/keys. The default model is then `nvidia/nemotron-3-super-120b-a12b`, which supports tool calling and costs about $0.08 per million input tokens.
- **or `NVIDIA_API_KEY`**: from build.nvidia.com. Open a Nemotron model page and click **Get API Key**. It starts with `nvapi-`.

If both are set, OpenRouter wins. To change the model, set `NEMOTRON_MODEL`.

Without a key, detection still runs and the console says "Nemotron not configured". The defender doesn't act, and nothing is faked.

**3. Start the backend** (terminal 1)

```bash
cd backend && KUBECONFIG=~/.kube/hackutd.yaml uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**4. Start the console** (terminal 2)

```bash
cd console && npm install && npm run dev
```

Open http://localhost:5173 and sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`. The defaults are `admin@halloran-vance.example` / `changeme-hackutd`. The console is **defender-only** now; `/attack` just points at the attacker app below.

**5. Start the attacker app** (terminal 3)

```bash
cd attacker && npm install && npm run dev
```

Open http://localhost:5180. This is the **judges' attacker workstation**: a 3D laptop in a dark room. Click it to open the lid; the screen becomes an attacker terminal that streams the real attack.

**6. Demo**

- On the attacker app (http://localhost:5180): open the laptop, then run **Gain access → Start miner → Steal weights → Persistence**. The terminal streams the real code sent to the exposed notebook, the live API-server calls, and the outputs. When the defender revokes the stolen token, the attacker sees a real **403 Forbidden** — "access lost".
- Watch the defender on the command center (http://localhost:5173, `/` and `/floor`) side by side. Approve or deny the actions that need a human. Each agent action and attack event expands to show the full tool call, Nemotron's reasoning, pod logs, and the attacker transcript that caused it.
- Click **Reset** (on either app) between judges. It takes a few seconds and removes everything the attacker created.

### How initial access is real

The `notebook` pod runs a **real JupyterLab with auth disabled**, exposed — like a ShadowRay-style open notebook — **only on the tailnet** (`100.106.83.89:8888`) by a `hostNetwork` proxy bound to the Tailscale IP (`deploy/15-notebook-edge.yaml`), never the public interface. The attack creates a kernel over the Jupyter REST API and runs Python in it; that in-pod code reads the mounted service-account token and calls the Kubernetes API server with it. See [backend/README.md](backend/README.md).

**Optional live view of the cluster:** `brew install k9s`, then:

```bash
KUBECONFIG=~/.kube/hackutd.yaml k9s
```

---

## Set up from scratch

This is how the current cluster was built. Each step only needs doing once per box.

**1. Rent the GPU box** (Brev CLI at `~/.local/bin/brev`)

```bash
brev login
brev create hackutd-gpu --type g4dn.xlarge --min-disk 60
```

A T4 with 16 GB at about $0.63/hr. It's stoppable, so its disk survives `brev stop`.

**2. Check that the GPU works in containers**

```bash
ssh hackutd-gpu 'nvidia-smi -L && docker run --rm --gpus all ubuntu nvidia-smi -L'
```

**3. Tailscale** (a private network between your Mac and the box)

- **On the Mac:** install the Tailscale app and sign in.
- **On the box:**

```bash
ssh hackutd-gpu 'curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up --hostname hackutd-gpu'
```

Open the link it prints and approve the box. Check from the Mac:

```bash
tailscale ping hackutd-gpu
```

**4. k3s**, with its certificate valid for the tailnet address. The current box is `100.106.83.89`:

```bash
ssh hackutd-gpu 'curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--tls-san <TAILSCALE_IP> --tls-san hackutd-gpu --write-kubeconfig-mode 600 --disable traefik" sh -'
```

k3s detects the NVIDIA container toolkit and creates the `nvidia` RuntimeClass by itself. If the installer stalls after "Enabling k3s unit", run `sudo systemctl start k3s` on the box.

**5. kubeconfig on the Mac**, so kubectl talks to the box over Tailscale:

```bash
ssh hackutd-gpu 'sudo cat /etc/rancher/k3s/k3s.yaml' | sed 's#https://127.0.0.1:6443#https://<TAILSCALE_IP>:6443#' > ~/.kube/hackutd.yaml && chmod 600 ~/.kube/hackutd.yaml
```

**6. GPU device plugin and workloads**

```bash
KUBECONFIG=~/.kube/hackutd.yaml kubectl apply -f deploy/00-gpu-plugin.yaml
```

```bash
KUBECONFIG=~/.kube/hackutd.yaml kubectl apply -f deploy/10-lawfirm.yaml
```

The first start pulls the 2.9 GB PyTorch image and takes a few minutes. Check that the GPU is advertised as 8:

```bash
KUBECONFIG=~/.kube/hackutd.yaml kubectl get node -o jsonpath='{.items[0].status.allocatable.nvidia\.com/gpu}'
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ssh hackutd-gpu` fails with "Connection closed by … port 30478" | Brev's SSH gateway is flaky. Go over Tailscale instead: `ssh -o HostName=<TAILSCALE_IP> -o Port=22 -o ProxyCommand=none hackutd-gpu` |
| kubectl times out | Tailscale isn't connected on the Mac, or the box is stopped (check with `brev ls`) |
| Console says "Not connected to the command center" | The backend isn't running on :8000 |
| Console says "Nemotron not configured" | `NVIDIA_API_KEY` is missing from `backend/.env` |
| Pods stuck `Pending` asking for `nvidia.com/gpu` | The device plugin isn't running. Re-apply `deploy/00-gpu-plugin.yaml` |

**Costs:** the box bills while running. Stop it when you're done: `brev stop hackutd-gpu`. k3s, Tailscale and the images all survive a stop and start, and the Tailscale address stays the same.
