// 3D data-center floor, built only from real cluster state.
// One k8s node = one rack. Each GPU = a glowing slot. Pods = thin sleds below the GPUs.
// Lazy-loaded (three.js stays out of the main bundle).

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import type { Selection } from "../components/NodeDetail";
import { useLive } from "../context";
import { useReducedMotion } from "../hooks";
import type { Cluster, ClusterNode, Pod } from "../types";

// State colours. Same meaning as the 2D view and the legend below.
const C = {
  normal: 0x34c98a,
  high: 0xf3b23c,
  attack: 0xff4d42,
  contained: 0x5aa2f0,
  fault: 0xe07bdb,
  rack: 0x2a3644,
  rackEdge: 0x5d7387,
  floor: 0x1b2632,
  grid: 0x31455a,
};

const RACK_W = 0.9;
const RACK_H = 2.1;
const RACK_D = 1.0;
const SPACING = 1.7;

/** A node is under attack while an unknown-owner pod on it is still running un-quarantined. */
function nodeUnderAttack(n: ClusterNode, pods: Pod[]): boolean {
  if (n.health === "critical") return true;
  return pods.some((p) => p.node === n.name && p.owner === "unknown" && !p.quarantined && p.phase === "Running");
}

function gpuColor(util: number, attacked: boolean, fault?: string): number {
  if (fault) return C.fault;
  if (attacked && util >= 50) return C.attack;
  if (util >= 90) return C.attack;
  if (util >= 70) return C.high;
  return C.normal;
}

function label(text: string, sub: string): THREE.Sprite {
  const cv = document.createElement("canvas");
  cv.width = 512;
  cv.height = 128;
  const g = cv.getContext("2d")!;
  g.fillStyle = "rgba(10,20,30,0.82)";
  g.beginPath();
  g.roundRect(4, 4, 504, 120, 16);
  g.fill();
  g.fillStyle = "#e8eef4";
  g.font = "700 46px 'IBM Plex Mono', monospace";
  g.fillText(text, 24, 58, 470);
  g.fillStyle = "#a2b3c3";
  g.font = "400 32px 'Atkinson Hyperlegible Next', sans-serif";
  g.fillText(sub, 24, 104, 470);
  const tex = new THREE.CanvasTexture(cv);
  tex.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  s.scale.set(1.6, 0.4, 1);
  s.renderOrder = 10;
  return s;
}

interface Pulse {
  mat: THREE.MeshStandardMaterial;
  base: number;
}

interface Built {
  group: THREE.Group;
  pulses: Pulse[];
  rackPos: Map<string, THREE.Vector3>;
}

function build(cluster: Cluster): Built {
  const group = new THREE.Group();
  const pulses: Pulse[] = [];
  const rackPos = new Map<string, THREE.Vector3>();
  const n = cluster.nodes.length;

  cluster.nodes.forEach((node, i) => {
    const x = (i - (n - 1) / 2) * SPACING;
    const rack = new THREE.Group();
    rack.position.set(x, 0, 0);
    rackPos.set(node.name, new THREE.Vector3(x, 0, 0));
    const attacked = nodeUnderAttack(node, cluster.pods);

    // Cabinet
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(RACK_W, RACK_H, RACK_D),
      new THREE.MeshStandardMaterial({ color: C.rack, roughness: 0.7, metalness: 0.3 }),
    );
    body.position.y = RACK_H / 2;
    body.userData = { node: node.name } satisfies Selection;
    rack.add(body);
    const edges = new THREE.LineSegments(
      new THREE.EdgesGeometry(body.geometry),
      new THREE.LineBasicMaterial({ color: attacked ? C.attack : C.rackEdge }),
    );
    edges.position.copy(body.position);
    rack.add(edges);

    // GPU slots, top of the rack, on the front face (+z)
    const slotH = 0.16;
    node.gpus.forEach((g, gi) => {
      const color = gpuColor(g.utilization, attacked, g.simulatedFault);
      const intensity = 0.35 + (g.utilization / 100) * 1.4;
      const mat = new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: intensity, roughness: 0.4 });
      const slot = new THREE.Mesh(new THREE.BoxGeometry(RACK_W * 0.82, slotH, 0.04), mat);
      slot.position.set(0, RACK_H - 0.28 - gi * (slotH + 0.07), RACK_D / 2 + 0.021);
      slot.userData = { node: node.name, gpu: g.index } satisfies Selection;
      rack.add(slot);
      if (attacked && color === C.attack) pulses.push({ mat, base: intensity });
    });

    // Pod sleds, below the GPUs
    const pods = cluster.pods.filter((p) => p.node === node.name);
    const top = RACK_H - 0.36 - node.gpus.length * (slotH + 0.07);
    pods.slice(0, 12).forEach((p, pi) => {
      const y = top - pi * 0.11;
      if (y < 0.12) return;
      const hostile = p.owner === "unknown" && !p.quarantined;
      const color = p.quarantined ? C.contained : hostile ? C.attack : 0x8da2b5;
      const mat = new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: p.quarantined || hostile ? 0.6 : 0.08,
      });
      const sled = new THREE.Mesh(new THREE.BoxGeometry(RACK_W * 0.82, 0.07, 0.03), mat);
      sled.position.set(0, y, RACK_D / 2 + 0.016);
      sled.userData = { node: node.name } satisfies Selection;
      rack.add(sled);
      if (hostile) pulses.push({ mat, base: 0.6 });
      if (p.quarantined) {
        // Barrier: a cage drawn around the quarantined sled
        const cage = new THREE.LineSegments(
          new THREE.EdgesGeometry(new THREE.BoxGeometry(RACK_W * 0.92, 0.11, 0.12)),
          new THREE.LineBasicMaterial({ color: C.contained }),
        );
        cage.position.set(0, y, RACK_D / 2 + 0.04);
        rack.add(cage);
      }
    });

    // Cordoned: a barrier ring on the floor around the rack
    if (node.cordoned) {
      const ring = new THREE.Mesh(
        new THREE.RingGeometry(0.85, 0.95, 48),
        new THREE.MeshBasicMaterial({ color: C.contained, side: THREE.DoubleSide, transparent: true, opacity: 0.85 }),
      );
      ring.rotation.x = -Math.PI / 2;
      ring.position.y = 0.01;
      rack.add(ring);
    }

    const util = node.gpus.length ? Math.round(node.gpus.reduce((s, g) => s + g.utilization, 0) / node.gpus.length) : 0;
    const tag = label(
      node.name,
      `${node.gpus.length} GPU${node.gpus.length === 1 ? "" : "s"}, ${util}%${node.cordoned ? ", cordoned" : ""}`,
    );
    tag.position.set(0, RACK_H + 0.4, 0);
    rack.add(tag);

    group.add(rack);
  });

  return { group, pulses, rackPos };
}

function dispose(obj: THREE.Object3D) {
  obj.traverse((o) => {
    const m = o as THREE.Mesh;
    m.geometry?.dispose();
    const mat = m.material as THREE.Material | THREE.Material[] | undefined;
    for (const x of Array.isArray(mat) ? mat : mat ? [mat] : []) {
      (x as THREE.SpriteMaterial).map?.dispose();
      x.dispose();
    }
  });
}

export default function Floor3D({ onSelect }: { onSelect: (s: Selection) => void }) {
  const { snapshot, lastAttack } = useLive();
  const reduced = useReducedMotion();
  const hostRef = useRef<HTMLDivElement>(null);
  const world = useRef<{
    scene: THREE.Scene;
    camera: THREE.PerspectiveCamera;
    renderer: THREE.WebGLRenderer;
    controls: OrbitControls;
    built: Built | null;
    flash: { mesh: THREE.Mesh; start: number } | null;
    fitted: number;
  } | null>(null);
  const reducedRef = useRef(reduced);
  reducedRef.current = reduced;
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

  // One-time scene setup
  useEffect(() => {
    const host = hostRef.current!;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    host.appendChild(renderer.domElement);
    renderer.domElement.setAttribute("aria-label", "3D view of the cluster racks. Use the list view for a text version.");
    renderer.domElement.setAttribute("role", "img");

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    camera.position.set(2.6, 2.6, 4.4);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.target.set(0, 1, 0);
    controls.maxPolarAngle = Math.PI / 2.05;
    controls.minDistance = 2;
    controls.maxDistance = 18;
    controls.enableDamping = !reducedRef.current;

    scene.add(new THREE.HemisphereLight(0xbfd4ea, 0x0d1822, 1.1));
    const key = new THREE.DirectionalLight(0xffffff, 1.4);
    key.position.set(3, 6, 4);
    scene.add(key);

    // Room: floor tiles and two low walls
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(14, 10), new THREE.MeshStandardMaterial({ color: C.floor, roughness: 0.95 }));
    floor.rotation.x = -Math.PI / 2;
    scene.add(floor);
    const grid = new THREE.GridHelper(14, 23, C.grid, C.grid);
    grid.position.y = 0.002;
    scene.add(grid);
    const wallMat = new THREE.MeshStandardMaterial({ color: 0x22303e, roughness: 1 });
    const back = new THREE.Mesh(new THREE.BoxGeometry(14, 2.8, 0.1), wallMat);
    back.position.set(0, 1.4, -2.5);
    scene.add(back);

    const w = { scene, camera, renderer, controls, built: null, flash: null, fitted: -1 } as NonNullable<typeof world.current>;
    world.current = w;

    const resize = () => {
      const { clientWidth: cw, clientHeight: ch } = host;
      if (!cw || !ch) return;
      renderer.setSize(cw, ch, false);
      camera.aspect = cw / ch;
      camera.updateProjectionMatrix();
    };
    const ro = new ResizeObserver(resize);
    ro.observe(host);
    resize();

    // Click to select a rack or GPU
    const ray = new THREE.Raycaster();
    const ptr = new THREE.Vector2();
    let down = { x: 0, y: 0 };
    const onDown = (e: PointerEvent) => (down = { x: e.clientX, y: e.clientY });
    const onUp = (e: PointerEvent) => {
      if (Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5 || !w.built) return; // was a drag
      const r = renderer.domElement.getBoundingClientRect();
      ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ptr, camera);
      const hit = ray.intersectObjects(w.built.group.children, true).find((h) => h.object.userData.node);
      if (hit) selectRef.current(hit.object.userData as Selection);
    };
    const onMove = (e: PointerEvent) => {
      if (!w.built) return;
      const r = renderer.domElement.getBoundingClientRect();
      ptr.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      ray.setFromCamera(ptr, camera);
      const over = ray.intersectObjects(w.built.group.children, true).some((h) => h.object.userData.node);
      renderer.domElement.style.cursor = over ? "pointer" : "grab";
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);
    renderer.domElement.addEventListener("pointermove", onMove);

    let raf = 0;
    const tick = (t: number) => {
      raf = requestAnimationFrame(tick);
      const still = reducedRef.current;
      controls.enableDamping = !still;
      controls.update();
      if (w.built && !still) {
        const k = 0.5 + 0.5 * Math.sin(t / 220);
        for (const p of w.built.pulses) p.mat.emissiveIntensity = p.base * (0.45 + 0.9 * k);
      }
      if (w.flash) {
        const age = (t - w.flash.start) / 1600;
        const m = w.flash.mesh.material as THREE.MeshBasicMaterial;
        if (age >= 1) {
          scene.remove(w.flash.mesh);
          dispose(w.flash.mesh);
          w.flash = null;
        } else if (still) {
          m.opacity = 0.8; // reduced motion: a steady highlight, no expanding ring
        } else {
          const s = 1 + age * 2.2;
          w.flash.mesh.scale.set(s, s, s);
          m.opacity = 0.9 * (1 - age);
        }
      }
      renderer.render(scene, camera);
    };
    raf = requestAnimationFrame(tick);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      renderer.domElement.removeEventListener("pointermove", onMove);
      controls.dispose();
      dispose(scene);
      renderer.dispose();
      host.removeChild(renderer.domElement);
      world.current = null;
    };
  }, []);

  // Rebuild racks whenever the cluster changes
  const cluster = snapshot?.cluster;
  const clusterRef = useRef(cluster);
  clusterRef.current = cluster;
  useEffect(() => {
    const w = world.current;
    if (!w || !cluster) return;
    if (w.built) {
      w.scene.remove(w.built.group);
      dispose(w.built.group);
    }
    w.built = build(cluster);
    w.scene.add(w.built.group);
    // Fit the camera when the rack count changes, not on every metrics update
    const n = cluster.nodes.length;
    if (w.fitted !== n) {
      w.fitted = n;
      const span = Math.max(1, n) * SPACING;
      const d = Math.max(4.6, span * 1.25);
      w.camera.position.set(d * 0.5, 2.4 + d * 0.15, d);
      w.controls.target.set(0, 1, 0);
    }
  }, [cluster]);

  // Flash where an attack event hit
  useEffect(() => {
    const w = world.current;
    const cluster = clusterRef.current;
    if (!w || !w.built || !lastAttack || !cluster) return;
    let node = lastAttack.target && cluster.nodes.find((n) => n.name === lastAttack.target)?.name;
    if (!node && lastAttack.target) node = cluster.pods.find((p) => p.name === lastAttack.target)?.node;
    // No target given: flash only if exactly one rack could be meant
    if (!node && cluster.nodes.length === 1) node = cluster.nodes[0].name;
    const pos = node && w.built.rackPos.get(node);
    if (!pos) return;
    if (w.flash) {
      w.scene.remove(w.flash.mesh);
      dispose(w.flash.mesh);
    }
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.7, 0.86, 48),
      new THREE.MeshBasicMaterial({ color: C.attack, transparent: true, opacity: 0.9, side: THREE.DoubleSide }),
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(pos.x, 0.02, pos.z);
    w.scene.add(ring);
    w.flash = { mesh: ring, start: performance.now() };
  }, [lastAttack]);

  return (
    <div className="floor-wrap">
      <div ref={hostRef} style={{ position: "absolute", inset: 0 }} />
      <div className="floor-legend" aria-hidden>
        <span className="chip t-clean">Normal</span>
        <span className="chip t-invest">High use</span>
        <span className="chip t-exfil">Under attack</span>
        <span className="chip t-contained">Quarantined or cordoned</span>
        <span className="chip t-locked">Simulated fault</span>
      </div>
    </div>
  );
}
