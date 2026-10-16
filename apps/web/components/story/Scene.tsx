"use client";

import { PerformanceMonitor } from "@react-three/drei";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { ChromaticAberration, EffectComposer, Noise, Vignette } from "@react-three/postprocessing";
import { BlendFunction } from "postprocessing";
import { useMemo, useRef, useState } from "react";
import * as THREE from "three";
import type { XY } from "@/lib/formations";
import { pitchFragment, pitchVertex } from "./pitchShader";
import { CHAPTERS, chapterAt, clamp01, smooth, story } from "./store";

const TURF = new THREE.Color("#23402F");
const CHALK = new THREE.Color("#F6F3EA");
const INK = new THREE.Color("#141414");
const RED = new THREE.Color("#D7261E");

export interface SceneProps {
  scatter: XY[]; // 22 start positions
  home: XY[]; // the club's XI in its formation
  away: XY[]; // opposition
  candidateSlot: number; // index in `home` the candidate takes (-1: none)
  gap: XY; // centre of the gap zone
}

// Six camera keyframes, one per chapter: board -> dive -> follow candidate -> overview -> grass level -> pull back.
function cameraCurves(gap: XY) {
  const [gx, gz] = [gap[0], -gap[1]];
  const pos = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0, 98, 0.1),
    new THREE.Vector3(gx + 30, 40, gz + 36),
    new THREE.Vector3(gx - 22, 16, gz + 30),
    new THREE.Vector3(0, 62, 58),
    new THREE.Vector3(-6, 2.4, 44),
    new THREE.Vector3(0, 150, 130),
  ]);
  const look = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(gx + 16, 0, gz - 4), // look past the gap so it sits left of the chapter text
    new THREE.Vector3(gx + 4, 0, gz),
    new THREE.Vector3(0, 0, 0),
    new THREE.Vector3(0, 1.2, 0),
    new THREE.Vector3(0, 0, 0),
  ]);
  return { pos, look };
}

function Pitch({ gap }: { gap: XY }) {
  const mat = useRef<THREE.ShaderMaterial>(null);
  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uLift: { value: 0 },
      uGapCenter: { value: new THREE.Vector2(gap[0], gap[1]) },
      uGapStrength: { value: 0 },
      uTurf: { value: TURF },
      uChalk: { value: CHALK },
      uRed: { value: RED },
    }),
    [gap],
  );
  useFrame((_, dt) => {
    // update the material's own uniforms: R3F may copy the object passed as a prop
    const u = (mat.current?.uniforms ?? uniforms) as typeof uniforms;
    if (process.env.NODE_ENV !== "production") (window as unknown as { __pitch: unknown }).__pitch = u; // debugging aid
    u.uTime.value += dt;
    const { index, local } = chapterAt(story.progress);
    // the gap bleeds in during chapter two and stays while the fix is scouted
    const target = index === 1 ? smooth(clamp01(local * 1.6)) : index === 2 ? 1 - smooth(clamp01(local - 0.4)) * 0.6 : index > 2 ? 0.25 : 0;
    u.uGapStrength.value += (target - u.uGapStrength.value) * 0.08;
    // the board lifts briefly between chapters
    const lift = Math.sin(Math.PI * clamp01(local < 0.12 ? local / 0.12 : 0)) * 0.6;
    u.uLift.value += (lift - u.uLift.value) * 0.1;
  });
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]}>
      {/* 105 x 68 m, dense enough for the paper ripple */}
      <planeGeometry args={[105, 68, 256, 160]} />
      <shaderMaterial ref={mat} vertexShader={pitchVertex} fragmentShader={pitchFragment} uniforms={uniforms} />
    </mesh>
  );
}

function Players({ scatter, home, away, candidateSlot }: Omit<SceneProps, "gap">) {
  const mesh = useRef<THREE.InstancedMesh>(null);
  const dummy = useMemo(() => new THREE.Object3D(), []);
  const n = home.length + away.length;
  const colors = useMemo(() => {
    const c = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) (i < home.length ? CHALK : INK).toArray(c, i * 3);
    return c;
  }, [n, home.length]);
  // the candidate's entry: a curve from beyond the touchline into the gap slot
  const entry = useMemo(() => {
    if (candidateSlot < 0) return null;
    const [x, y] = home[candidateSlot];
    return new THREE.QuadraticBezierCurve(new THREE.Vector2(x - 30, y - 30), new THREE.Vector2(x - 26, y + 6), new THREE.Vector2(x, y));
  }, [home, candidateSlot]);

  useFrame(({ clock }) => {
    const m = mesh.current;
    if (!m) return;
    const { index, local } = chapterAt(story.progress);
    const settle = index === 0 ? smooth(clamp01(local * 1.4)) : 1;
    for (let i = 0; i < n; i++) {
      const target = i < home.length ? home[i] : away[i - home.length];
      const start = scatter[i];
      let x = start[0] + (target[0] - start[0]) * settle;
      let y = start[1] + (target[1] - start[1]) * settle;
      let s = 1;
      if (i === candidateSlot && entry) {
        if (index < 2) s = 0.0001; // the gap is empty until the fix arrives
        else {
          const t = index === 2 ? smooth(clamp01(local * 1.3)) : 1;
          const p = entry.getPoint(t);
          [x, y] = [p.x, p.y];
        }
      }
      const bob = Math.sin(clock.elapsedTime * 1.3 + i) * 0.08;
      dummy.position.set(x, 0.35 + bob, -y);
      dummy.scale.setScalar(s);
      dummy.updateMatrix();
      m.setMatrixAt(i, dummy.matrix);
    }
    m.instanceMatrix.needsUpdate = true;
    if (candidateSlot >= 0) {
      const c = index >= 2 ? RED : CHALK;
      m.setColorAt(candidateSlot, c);
      if (m.instanceColor) m.instanceColor.needsUpdate = true;
    }
  });
  return (
    <instancedMesh ref={mesh} args={[undefined, undefined, n]}>
      <cylinderGeometry args={[1.1, 1.1, 0.5, 40]}>
        <instancedBufferAttribute attach="attributes-color" args={[colors, 3]} />
      </cylinderGeometry>
      <meshBasicMaterial vertexColors toneMapped={false} />
    </instancedMesh>
  );
}

function Rig({ gap }: { gap: XY }) {
  const { camera } = useThree();
  const curves = useMemo(() => cameraCurves(gap), [gap]);
  const p = useRef(0);
  const look = useMemo(() => new THREE.Vector3(), []);
  useFrame(() => {
    p.current += (story.progress - p.current) * 0.08; // scrub with a little inertia
    // chapter i's midpoint sits exactly on keyframe i; the camera travels between keyframes across boundaries
    const t = clamp01((p.current * CHAPTERS - 0.5) / (CHAPTERS - 1));
    camera.position.copy(curves.pos.getPoint(t));
    camera.position.x += story.mouse[0] * 1.2; // cursor parallax
    camera.position.y += story.mouse[1] * 0.8;
    curves.look.getPoint(t, look);
    camera.lookAt(look);
  });
  return null;
}

export default function Scene(props: SceneProps) {
  const [dpr, setDpr] = useState(1.5);
  return (
    <Canvas
      dpr={dpr}
      camera={{ fov: 38, near: 0.5, far: 600, position: [0, 98, 0.1] }}
      gl={{ antialias: true, powerPreference: "high-performance" }}
      style={{ background: "#ECE6D8" }}
      aria-hidden="true"
    >
      <PerformanceMonitor onDecline={() => setDpr(1)} onIncline={() => setDpr(1.5)} />
      <color attach="background" args={["#ECE6D8"]} />
      <Pitch gap={props.gap} />
      <Players scatter={props.scatter} home={props.home} away={props.away} candidateSlot={props.candidateSlot} />
      <Rig gap={props.gap} />
      <EffectComposer multisampling={0}>
        <Noise premultiply blendFunction={BlendFunction.SOFT_LIGHT} opacity={0.35} />
        <ChromaticAberration offset={new THREE.Vector2(0.0006, 0.0004)} radialModulation={false} modulationOffset={0} />
        <Vignette eskil={false} offset={0.32} darkness={0.42} />
      </EffectComposer>
    </Canvas>
  );
}
