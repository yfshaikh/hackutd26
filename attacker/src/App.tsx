// The Zero Day laptop: a CSS-3D laptop on a night-city desk. Click it -> the lid swings open
// -> the camera dives into the screen -> it boots -> the Terminal (wired to the real backend)
// takes over. Ported from scratch/hacker-laptop.html; the pose math is unchanged.
import { useEffect, useRef, useState } from "react";
import Terminal from "./Terminal";

const reduced = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
const wait = (ms: number) => new Promise((r) => setTimeout(r, reduced ? 0 : ms));
const LID_OPEN_DEG = 10; // the lid opens 10deg past vertical; the camera tilts back to match

// The keyboard: 4 rows x 14 keys, with a wide modifier and a spacebar.
function keyCells() {
  const cells: { cls: string; key: string }[] = [];
  for (let r = 0; r < 4; r++)
    for (let c = 0; c < 14; c++) {
      if (r === 3 && c > 1 && c < 9) { if (c === 2) cells.push({ cls: "space", key: `${r}-${c}` }); continue; }
      cells.push({ cls: r === 3 && c === 0 ? "wide" : "", key: `${r}-${c}` });
    }
  return cells;
}

export default function App() {
  const [booted, setBooted] = useState(reduced);
  const root = useRef<HTMLDivElement>(null);
  const rig = useRef<HTMLDivElement>(null);
  const laptop = useRef<HTMLDivElement>(null);
  const opened = useRef(reduced);
  const closeFn = useRef<() => void>(() => {});

  useEffect(() => {
    const r = root.current!, rg = rig.current!, lp = laptop.current!;
    const setPose = (s: number, ty: number, tz: number, ax: number, ay: number) => {
      rg.style.setProperty("--s", String(s));
      rg.style.setProperty("--ty", ty + "px");
      rg.style.setProperty("--tz", tz + "px");
      rg.style.setProperty("--ax", ax + "deg");
      rg.style.setProperty("--ay", ay + "deg");
    };
    // Camera pose that puts the open screen face-on, centred, filling the window.
    const zoomPose = () => {
      const css = getComputedStyle(r);
      const w = parseFloat(css.getPropertyValue("--w")), lid = parseFloat(css.getPropertyValue("--lid"));
      const deck = parseFloat(css.getPropertyValue("--deck"));
      const t = (LID_OPEN_DEG * Math.PI) / 180, L = lid / 2, D = deck / 2;
      const y = -L * Math.cos(t), z = -D - L * Math.sin(t);
      const y2 = y * Math.cos(t) + z * Math.sin(t);
      const z2 = -y * Math.sin(t) + z * Math.cos(t);
      const s = Math.min((innerWidth * 0.98) / w, (innerHeight * 0.98) / lid);
      setPose(s, -y2, -z2, -LID_OPEN_DEG, 0);
    };

    const open = async () => {
      if (opened.current) return;
      opened.current = true;
      r.classList.add("open");
      setPose(0.9, 150, 0, -26, 0);
      r.style.setProperty("--open", "1");          // 1. swing the lid open
      lp.setAttribute("aria-label", "Laptop, open");
      await wait(1250);
      r.classList.add("zooming");                   // 2. dive into the screen
      zoomPose();
      await wait(1350);
      r.classList.add("booting");                   // 3. power on
      await wait(250);
      r.classList.add("booted");
      setBooted(true);
    };
    // Reverse of open(): the camera eases back out and the lid shuts, back to the closed desk.
    const close = () => {
      if (!opened.current) return;
      opened.current = false;
      setBooted(false);
      r.classList.remove("booted", "booting", "zooming");
      r.style.setProperty("--open", "0");
      setPose(0.9, 150, 0, -26, 0);
      window.setTimeout(() => { if (!opened.current) r.classList.remove("open"); }, reduced ? 0 : 1450);
    };
    closeFn.current = close;

    if (reduced) { r.classList.add("open", "booted"); r.style.setProperty("--open", "1"); }
    else setPose(0.9, 150, 0, -26, 0);

    const onClick = () => open();
    const onKey = (e: KeyboardEvent) => { if ((e.key === "Enter" || e.key === " ") && !opened.current) { e.preventDefault(); open(); } };
    const onMove = (e: MouseEvent) => {
      if (opened.current) return;
      const x = e.clientX / innerWidth - 0.5, y = e.clientY / innerHeight - 0.5;
      setPose(0.9, 150, 0, -26 - y * 8, x * 18);
    };
    const onResize = () => { if (r.classList.contains("zooming")) zoomPose(); };
    lp.addEventListener("click", onClick);
    lp.addEventListener("keydown", onKey);
    if (!reduced) addEventListener("mousemove", onMove);
    addEventListener("resize", onResize);
    return () => {
      lp.removeEventListener("click", onClick);
      lp.removeEventListener("keydown", onKey);
      removeEventListener("mousemove", onMove);
      removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <div className="app" ref={root}>
      <div className="moon" aria-hidden />
      <svg className="skyline" viewBox="0 0 1200 400" preserveAspectRatio="none" aria-hidden>
        <g fill="#120c24">
          <rect x="0" y="220" width="90" height="180" /><rect x="80" y="150" width="70" height="250" /><rect x="160" y="250" width="110" height="150" />
          <rect x="260" y="120" width="60" height="280" /><rect x="330" y="200" width="120" height="200" /><rect x="460" y="90" width="80" height="310" />
          <rect x="760" y="140" width="90" height="260" /><rect x="850" y="230" width="120" height="170" /><rect x="980" y="110" width="70" height="290" />
          <rect x="1050" y="210" width="150" height="190" />
        </g>
        <g fill="#7828ff" opacity=".7">
          <rect x="95" y="170" width="6" height="8" /><rect x="120" y="200" width="6" height="8" /><rect x="275" y="150" width="6" height="8" />
          <rect x="290" y="210" width="6" height="8" /><rect x="480" y="120" width="6" height="8" /><rect x="510" y="180" width="6" height="8" />
          <rect x="780" y="170" width="6" height="8" /><rect x="820" y="230" width="6" height="8" /><rect x="1000" y="140" width="6" height="8" />
        </g>
        <g fill="#ff3fd8" opacity=".6"><rect x="350" y="230" width="6" height="8" /><rect x="900" y="260" width="6" height="8" /><rect x="1100" y="240" width="6" height="8" /></g>
      </svg>

      <div className="title">
        <h1>the city needs <em>you</em>…</h1>
        <p>HackUTD 2026 · Zero Day · red team</p>
      </div>

      <main className="stage">
        <div className="rig" ref={rig}>
          <div className="floor" aria-hidden />
          <div className="laptop" ref={laptop} tabIndex={0} role="button" aria-label="Open the laptop">
            <div className="deck" aria-hidden>
              <div className="keys">{keyCells().map((k) => <i key={k.key} className={k.cls} />)}</div>
              <div className="trackpad" />
              <div className="deck-front" />
            </div>
            <div className="lid">
              <div className="lid-back" aria-hidden>
                <img className="logo" src="/mascots/logo.png" alt="" onError={(e) => e.currentTarget.remove()} />
                <div className="sticker raccoon"><img src="/mascots/raccoon.png" alt="" onError={(e) => e.currentTarget.remove()} /></div>
                <div className="sticker tag">zero day</div>
              </div>
              <div className="lid-front">
                <div className="screen">
                  <div className="flash" />
                  <Terminal booted={booted} onClose={() => closeFn.current()} />
                </div>
              </div>
            </div>
          </div>
        </div>
      </main>

      <div className="hint">Click the laptop to open it</div>
    </div>
  );
}
