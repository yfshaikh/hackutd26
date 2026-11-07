# Attacker laptop

The attacker's side of the demo, made to sit next to the defender console (`:5173`) in a second window.
It shows a 3D desk with a closed laptop. Click **Open laptop**: the lid opens, the camera moves into the
screen, and the attacker terminal takes over.

```bash
cd attacker && npm install && npm run dev      # http://localhost:5180
```

Point it at another backend with `VITE_API_URL=http://host:8000 npm run dev`. The default is `http://localhost:8000`.

Everything on screen comes from the backend. Nothing is invented: with no backend running, it says "No connection".

| File | What it does |
|---|---|
| `src/App.tsx` | Three stages: closed (desk), opening (animation), open (terminal). Skips straight to the terminal when reduced motion is on. |
| `src/Scene.tsx` | The three.js scene (react-three-fiber): room, desk lamp, laptop with a hinged lid. Animates the lid, then dollies the camera into the screen. |
| `src/Terminal.tsx` | The attacker screen: target and recon panel, the 4 attack steps with "what a real attacker is doing" and "seen in the wild" notes, the live transcript, an "access lost" banner, and reset. |
| `src/api.ts` | All network calls: `GET /attack`, `POST /attack/{step}`, `POST /reset`, `GET /attack/recon`, and the SSE `GET /attack/stream`. |
| `src/styles.css` | One dark look: a dim room and a terminal. Fonts are bundled locally (JetBrains Mono, IBM Plex Sans). |

**How it reads the backend:**
- **Steps** come from `GET /attack` (locked, ready, running, done), polled every 4 s and refreshed after each action.
- **Recon** comes from `GET /attack/recon`: whether Jupyter is reachable, the stolen identity's rules (a real `SelfSubjectRulesReview`), and the GPU.
- **Transcript:** `GET /attack/stream` sends `{type: "history"}` first, then one `{type: "transcript", entry}` per line. Entry kinds are `code` (code sent to Jupyter), `http` (API request and status), `output`, `cmd` and `note`.
- **Access lost:** shown when a real response comes back 401 or 403, or "Forbidden", or when a pod or CronJob turns out to be gone. That's how the attacker's window shows the defender's revoke.
