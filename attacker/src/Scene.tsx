// The desk scene: a dim room, a warm desk lamp, and a closed laptop. Clicking the laptop opens the lid
// on its hinge and dollies the camera into the screen; App then swaps in the terminal overlay.
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Html, RoundedBox, ContactShadows } from "@react-three/drei";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";

const LID_CLOSED = Math.PI / 2;   // lid lying on the keyboard
const LID_OPEN = -0.22;           // tilted slightly back
const CAM_FAR = new THREE.Vector3(0.9, 1.25, 2.3);
const CAM_NEAR = new THREE.Vector3(0, 0.5, 0.42);
const LOOK_FAR = new THREE.Vector3(0, 0.15, -0.1);
const LOOK_NEAR = new THREE.Vector3(0, 0.46, -0.53);   // screen centre when open
const ease = (t: number) => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2);

function Keys() {
  const mats = useMemo(() => {
    const m: THREE.Matrix4[] = [];
    for (let r = 0; r < 5; r++)
      for (let c = 0; c < 14; c++)
        m.push(new THREE.Matrix4().setPosition(-0.52 + c * 0.08, 0.026, -0.3 + r * 0.075));
    return m;
  }, []);
  return (
    <instancedMesh args={[undefined, undefined, mats.length]} onUpdate={(s) => { mats.forEach((m, i) => s.setMatrixAt(i, m)); s.instanceMatrix.needsUpdate = true; }}>
      <boxGeometry args={[0.066, 0.008, 0.062]} />
      <meshStandardMaterial color="#1a1c20" roughness={0.6} />
    </instancedMesh>
  );
}

function Laptop({ opening, onOpened, onHover }: { opening: boolean; onOpened: () => void; onHover: (h: boolean) => void }) {
  const lid = useRef<THREE.Group>(null!);
  const screen = useRef<THREE.MeshStandardMaterial>(null!);
  const t = useRef(0);
  const done = useRef(false);
  const { camera } = useThree();
  const look = useRef(LOOK_FAR.clone());

  useFrame((_, dt) => {
    if (opening && t.current < 1) t.current = Math.min(1, t.current + dt / 1.8);
    const k = ease(t.current);
    const lidK = ease(Math.min(1, t.current / 0.6));            // lid first,
    const camK = ease(Math.max(0, (t.current - 0.35) / 0.65));    // then the camera dives in
    lid.current.rotation.x = THREE.MathUtils.lerp(LID_CLOSED, LID_OPEN, lidK);
    screen.current.emissiveIntensity = THREE.MathUtils.lerp(0, 1.4, Math.max(0, (k - 0.3) / 0.7));
    camera.position.lerpVectors(CAM_FAR, CAM_NEAR, camK);
    look.current.lerpVectors(LOOK_FAR, LOOK_NEAR, camK);
    camera.lookAt(look.current);
    if (t.current >= 1 && !done.current) { done.current = true; onOpened(); }
  });

  return (
    <group
      onClick={(e) => { e.stopPropagation(); if (!opening) onHover(false); }}
      onPointerOver={() => !opening && onHover(true)}
      onPointerOut={() => onHover(false)}
    >
      {/* base */}
      <RoundedBox args={[1.3, 0.04, 0.9]} radius={0.015} smoothness={4} position={[0, 0, 0]}>
        <meshStandardMaterial color="#2b2e33" metalness={0.75} roughness={0.35} />
      </RoundedBox>
      <Keys />
      <mesh position={[0, 0.0205, 0.27]}>
        <boxGeometry args={[0.42, 0.001, 0.22]} />
        <meshStandardMaterial color="#25282d" metalness={0.6} roughness={0.25} />
      </mesh>
      {/* lid, pivoting on the back edge */}
      <group ref={lid} position={[0, 0.02, -0.45]} rotation={[LID_CLOSED, 0, 0]}>
        <RoundedBox args={[1.3, 0.9, 0.025]} radius={0.012} smoothness={4} position={[0, 0.45, 0]}>
          <meshStandardMaterial color="#2b2e33" metalness={0.75} roughness={0.35} />
        </RoundedBox>
        <mesh position={[0, 0.46, 0.0135]}>
          <planeGeometry args={[1.18, 0.74]} />
          <meshStandardMaterial ref={screen} color="#050608" emissive="#0f2a33" emissiveIntensity={0} roughness={0.2} />
        </mesh>
      </group>
    </group>
  );
}

function Lamp() {
  return (
    <group position={[-1.25, 0, -0.55]}>
      <mesh position={[0, 0.02, 0]}><cylinderGeometry args={[0.16, 0.18, 0.04, 32]} /><meshStandardMaterial color="#1b1b1d" metalness={0.5} roughness={0.5} /></mesh>
      <mesh position={[0.08, 0.42, 0]} rotation={[0, 0, -0.35]}><cylinderGeometry args={[0.012, 0.012, 0.85, 12]} /><meshStandardMaterial color="#1b1b1d" metalness={0.6} roughness={0.4} /></mesh>
      <mesh position={[0.32, 0.8, 0.05]} rotation={[0.2, 0, -1.05]}><coneGeometry args={[0.14, 0.22, 32, 1, true]} /><meshStandardMaterial color="#1b1b1d" side={THREE.DoubleSide} metalness={0.4} roughness={0.5} /></mesh>
      <pointLight position={[0.38, 0.72, 0.08]} intensity={4.5} distance={4} decay={1.6} color="#ffb46b" castShadow />
    </group>
  );
}

export default function Scene({ opening, onOpen, onOpened }: { opening: boolean; onOpen: () => void; onOpened: () => void }) {
  const [hover, setHover] = useState(false);
  return (
    <Canvas shadows camera={{ position: CAM_FAR.toArray(), fov: 42 }} dpr={[1, 2]} style={{ cursor: hover ? "pointer" : "default" }}>
      <color attach="background" args={["#07080a"]} />
      <fog attach="fog" args={["#07080a", 3, 8]} />
      <ambientLight intensity={0.12} />
      <directionalLight position={[2, 3, 2]} intensity={0.25} color="#8fa3c7" />
      {/* desk */}
      <mesh position={[0, -0.04, 0]} receiveShadow>
        <boxGeometry args={[3.6, 0.06, 1.8]} />
        <meshStandardMaterial color="#2a1f17" roughness={0.8} />
      </mesh>
      <mesh position={[0, 1.2, -1.4]}><planeGeometry args={[10, 5]} /><meshStandardMaterial color="#0c0d10" roughness={1} /></mesh>
      <Lamp />
      <group position={[0, 0, 0.15]} onClick={() => !opening && onOpen()}>
        <Laptop opening={opening} onOpened={onOpened} onHover={setHover} />
        {!opening && (
          <Html position={[0, 0.16, 0.62]} center distanceFactor={2.4}>
            <button className={`open-cue${hover ? " hot" : ""}`} onClick={onOpen}>Open laptop</button>
          </Html>
        )}
      </group>
      <ContactShadows position={[0, -0.005, 0.15]} opacity={0.6} scale={3} blur={2.4} far={0.6} />
    </Canvas>
  );
}
