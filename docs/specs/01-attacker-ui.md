# Spec 01 — Attacker laptop UI: run-another-attack, grouped reveal, collapsible code

**Lane:** A (independent — touches only `attacker/`)
**Files:** `attacker/src/Terminal.tsx`, `attacker/src/styles.css`
**Read first:** `attacker/src/Terminal.tsx` (the whole component), `attacker/src/App.tsx` (do NOT change the laptop pose math).

The attacker laptop already has an attack-selection menu that appears after `gain-access` settles
(`!chosen && settled` → "choose one attack" with the four payload buttons). Three changes:

## 1. Run another attack (the menu gap)
Today, once you pick an attack and it finishes, the only control is **"⟲ reset & close"** (`reset()`,
which also closes the laptop). You cannot run a second attack without closing and redoing the 18-step
break-in.

- In the attack-complete branch (`chosen && !runningChosen && settled`), add a **primary** button
  **"▸ run another attack"** that returns to the picker **without** resetting the backend or closing the laptop.
- Implement `backToMenu()`: `setChosen(null)` and show the menu **immediately** — do NOT replay the boot
  preamble or the gain-access log. Since `access` is already `done`, jump the reveal straight to settled
  for the `gain-access` focus (e.g. track an `everAccessed` ref, and when `chosen` returns to `null` with
  access already granted, set `reveal` to `items.length` instead of 0 so the "choose one attack" menu
  renders at once).
- Keep **"⟲ reset & close"** as a secondary (ghost) button next to it.
- Re-running an already-`done` attack: leave the buttons clickable (they already are); the backend returns
  updated status via `runStep`.

## 2. Next reveals logical GROUPS, not one line at a time
Today `advance()` reveals exactly one `item`. Make **Next** reveal the next **logical group** so a comment
and the call it describes appear together (e.g. the `# recon…` note **and** the following `GET` line in one
step; the `# no token yet` note **and** the `POST` in one step).

- Add a `groups` memo over `items`: a new group **starts** at each `note` or `cmd` entry (a human-readable
  comment/command) and **absorbs** the following `http` / `code` / `out` lines until the next `note`/`cmd`.
  Entries with no leading comment form their own single-item group.
- `advance()` reveals the next whole group: set `reveal` to the index of the end of the next group.
- The button count becomes **groups remaining**, not lines remaining: `Next ▸ · N more`.
- Boot lines keep their existing auto-play (unchanged).

## 3. Code blocks: collapsible, collapsed by default
The running code (the token-theft script, the miner matmul loop) prints as many `code`/`note` lines and
dominates the screen. Collapse it.

- A run of consecutive `code` entries (interleaved `note` comments allowed) renders as a single native
  `<details class="code-block">` element, **collapsed by default**, with `<summary>` reading
  **"▸ code · N lines"**. Expanding shows the lines.
- Use native `<details>` — no React state needed.
- Style `.code-block` in `styles.css` to match the terminal (monospace, dim border, the Zero Day palette).

## Acceptance
- After running Miner, **"run another attack"** returns to the four-attack menu with the laptop still open
  and gain-access NOT replayed; picking Steal weights runs it.
- **Next** advances by logical groups (comment + its call together); the "· N more" count reflects groups.
- Code blocks start collapsed and expand on click.
- **"reset & close"** still resets + closes; reduced-motion path still works.

## Gotchas
- The attacker app must run on **:5180** (backend CORS allows only 5173/5180).
- Don't touch the CSS-3D pose math in `App.tsx`; keep the SSE transcript wiring (`streamTranscript`).
- Keep `linkify` / `entryNode` behavior for URLs.
