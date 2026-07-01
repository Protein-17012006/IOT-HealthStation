import { Suspense, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Float, Sphere, Icosahedron, MeshDistortMaterial } from '@react-three/drei'
import { EffectComposer, Bloom } from '@react-three/postprocessing'
import * as THREE from 'three'

// The signature 3D element: a glowing, organically-distorted "vitals core" that
// embodies the patient's overall state. It is driven by the live snapshot via a
// mutable ref (so the React tree doesn't re-render every tick): the distortion
// grows with the ambient-sound level and the colour follows the status —
// teal (stable) → amber (attention) → red, flaring on a fall.

const STATUS_COLOR: Record<string, string> = { ok: '#34D399', warn: '#FBBF24', crit: '#FF3B47' }

export interface Live3D { soundFrac: number; status: 'ok' | 'warn' | 'crit'; fall: boolean }
type LiveRef = { current: Live3D }

function Core({ liveRef, reduced }: { liveRef: LiveRef; reduced: boolean }) {
  const mat = useRef<any>(null)
  const wire = useRef<any>(null)
  const mesh = useRef<THREE.Mesh>(null)
  const shell = useRef<THREE.Mesh>(null)
  const tmp = useRef(new THREE.Color('#34D399'))

  useFrame((_, delta) => {
    const L = liveRef.current
    tmp.current.set(STATUS_COLOR[L.status] || STATUS_COLOR.ok)
    if (mat.current) {
      const base = L.fall ? 0.6 : 0.28
      mat.current.distort = THREE.MathUtils.lerp(mat.current.distort ?? base, base + L.soundFrac * 0.45, 0.08)
      mat.current.color.lerp(tmp.current, 0.06)
      mat.current.emissive.lerp(tmp.current, 0.06)
      mat.current.emissiveIntensity = THREE.MathUtils.lerp(mat.current.emissiveIntensity ?? 0.7, L.fall ? 1.5 : 0.7, 0.06)
    }
    if (wire.current) wire.current.color.lerp(tmp.current, 0.06)
    if (!reduced) {
      const spin = L.fall ? 0.9 : 0.2
      if (mesh.current) mesh.current.rotation.y += delta * spin
      if (shell.current) { shell.current.rotation.y -= delta * spin * 0.7; shell.current.rotation.x += delta * 0.1 }
    }
  })

  const body = (
    <>
      <Sphere ref={mesh as any} args={[1.25, 96, 96]}>
        <MeshDistortMaterial ref={mat} color="#34D399" emissive="#34D399" emissiveIntensity={0.7}
          roughness={0.18} metalness={0.2} distort={0.3} speed={2.2} />
      </Sphere>
      <Icosahedron ref={shell as any} args={[1.85, 1]}>
        <meshBasicMaterial ref={wire} wireframe transparent opacity={0.14} color="#34D399" />
      </Icosahedron>
    </>
  )

  return reduced ? body : (
    <Float speed={1.1} rotationIntensity={0.35} floatIntensity={0.7}>{body}</Float>
  )
}

export default function VitalsCore({ liveRef, reduced }: { liveRef: LiveRef; reduced: boolean }) {
  return (
    <Canvas camera={{ position: [0, 0, 4.2], fov: 42 }} dpr={[1, 2]} gl={{ antialias: true, alpha: true }}>
      <ambientLight intensity={0.5} />
      <pointLight position={[3, 3, 4]} intensity={1.3} />
      <pointLight position={[-4, -2, -2]} intensity={0.7} color="#22D3EE" />
      <Suspense fallback={null}>
        <Core liveRef={liveRef} reduced={reduced} />
      </Suspense>
      {!reduced && (
        <EffectComposer>
          <Bloom mipmapBlur intensity={0.9} luminanceThreshold={0.25} luminanceSmoothing={0.4} />
        </EffectComposer>
      )}
    </Canvas>
  )
}
