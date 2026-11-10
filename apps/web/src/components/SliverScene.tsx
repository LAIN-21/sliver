import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type RefObject,
} from "react";
import * as THREE from "three";
import "./SliverScene.css";

type SliverSceneProps = {
  progressRef: RefObject<number>;
  paused: boolean;
};

type DataConnection = EventTarget & { saveData?: boolean };

// The illustration contains only structural rulings, never dataset contents.
function plateGeometry() {
  const width = 3.65;
  const depth = 2.3;
  const radius = 0.1;
  const x = -width / 2;
  const y = -depth / 2;
  const shape = new THREE.Shape();
  shape.moveTo(x + radius, y);
  shape.lineTo(x + width - radius, y);
  shape.quadraticCurveTo(x + width, y, x + width, y + radius);
  shape.lineTo(x + width, y + depth - radius);
  shape.quadraticCurveTo(x + width, y + depth, x + width - radius, y + depth);
  shape.lineTo(x + radius, y + depth);
  shape.quadraticCurveTo(x, y + depth, x, y + depth - radius);
  shape.lineTo(x, y + radius);
  shape.quadraticCurveTo(x, y, x + radius, y);
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth: 0.065,
    bevelEnabled: true,
    bevelSegments: 2,
    steps: 1,
    bevelSize: 0.018,
    bevelThickness: 0.014,
    curveSegments: 6,
  });
  geometry.translate(0, 0, -0.0325);
  geometry.rotateX(-Math.PI / 2);
  return geometry;
}

function rulingGeometry() {
  const points: number[] = [];
  const top = 0.05;
  for (let row = 0; row < 9; row += 1) {
    const z = -0.94 + row * 0.235;
    points.push(-1.6, top, z, 1.6, top, z);
  }
  for (const x of [-1.6, -0.88, 0.52, 1.6]) {
    points.push(x, top, -0.94, x, top, 0.94);
  }
  return new THREE.BufferGeometry().setAttribute(
    "position",
    new THREE.Float32BufferAttribute(points, 3),
  );
}

export default function SliverScene({ progressRef, paused }: SliverSceneProps) {
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const pausedRef = useRef(paused);
  const syncRef = useRef<(() => void) | null>(null);
  const [rendererKind, setRendererKind] = useState<"webgl" | "fallback">(
    "fallback",
  );

  useEffect(() => {
    pausedRef.current = paused;
    syncRef.current?.();
  }, [paused]);

  useEffect(() => {
    const host = canvasHostRef.current;
    if (!host) return;

    const motionPreference = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    );
    const connection = (
      navigator as Navigator & { connection?: DataConnection }
    ).connection;
    const requestedTime = new URLSearchParams(window.location.search).get("t");
    const parsedTime = requestedTime === null ? null : Number(requestedTime);
    const frozenTime =
      parsedTime !== null && Number.isFinite(parsedTime)
        ? Math.max(0, parsedTime)
        : null;
    let disposed = false;
    let visible = false;
    let failed = false;
    let animationFrame = 0;
    let runningSince: number | null = null;
    let elapsed = 0;
    let width = 0;
    let height = 0;
    let renderer: THREE.WebGLRenderer | null = null;
    let scene: THREE.Scene | null = null;
    let camera: THREE.OrthographicCamera | null = null;
    let shadowLight: THREE.DirectionalLight | null = null;
    let stack: THREE.Group | null = null;
    let selected: THREE.Group | null = null;
    let canvasRevealed = false;
    const geometries = new Set<THREE.BufferGeometry>();
    const materials = new Set<THREE.Material>();

    const preferFallback = () =>
      motionPreference.matches || connection?.saveData === true;
    const canRender = () =>
      !disposed &&
      visible &&
      document.visibilityState === "visible" &&
      !pausedRef.current &&
      !preferFallback() &&
      !failed;

    const stop = () => {
      if (animationFrame) cancelAnimationFrame(animationFrame);
      animationFrame = 0;
      if (runningSince !== null)
        elapsed += (performance.now() - runningSince) / 1000;
      runningSince = null;
    };

    const release = () => {
      stop();
      if (renderer) {
        renderer.domElement.removeEventListener(
          "webglcontextlost",
          onContextLost,
        );
        renderer.dispose();
        renderer.forceContextLoss();
        renderer.domElement.remove();
      }
      geometries.forEach((geometry) => geometry.dispose());
      materials.forEach((material) => material.dispose());
      shadowLight?.shadow.dispose();
      geometries.clear();
      materials.clear();
      renderer = null;
      scene = null;
      camera = null;
      shadowLight = null;
      stack = null;
      selected = null;
      canvasRevealed = false;
      width = 0;
      height = 0;
      if (!disposed) setRendererKind("fallback");
    };

    function onContextLost(event: Event) {
      event.preventDefault();
      failed = true;
      release();
    }

    const initialize = () => {
      try {
        renderer = new THREE.WebGLRenderer({
          alpha: true,
          antialias: true,
          powerPreference: "low-power",
        });
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
        renderer.setClearColor(0x000000, 0);
        renderer.outputColorSpace = THREE.SRGBColorSpace;
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type = THREE.PCFShadowMap;
        renderer.domElement.setAttribute("aria-hidden", "true");
        renderer.domElement.addEventListener("webglcontextlost", onContextLost);
        host.appendChild(renderer.domElement);

        scene = new THREE.Scene();
        camera = new THREE.OrthographicCamera(-3, 3, 2.7, -2.7, 0.1, 40);
        camera.position.set(5.6, 4.8, 7.2);
        camera.lookAt(0.25, 0, 0);
        scene.add(new THREE.HemisphereLight(0xf9f9ed, 0x52604c, 2.5));
        const light = new THREE.DirectionalLight(0xfffbed, 3);
        shadowLight = light;
        light.position.set(-3, 7, 5);
        light.castShadow = true;
        light.shadow.mapSize.set(1024, 1024);
        light.shadow.camera.left = -5;
        light.shadow.camera.right = 5;
        light.shadow.camera.top = 5;
        light.shadow.camera.bottom = -5;
        light.shadow.normalBias = 0.035;
        light.shadow.bias = -0.0001;
        light.shadow.blurSamples = 6;
        scene.add(light);
        const fill = new THREE.DirectionalLight(0xe7efda, 0.7);
        fill.position.set(4, 2, -4);
        scene.add(fill);

        const plate = plateGeometry();
        const rulings = rulingGeometry();
        const outline = new THREE.EdgesGeometry(plate, 28);
        geometries.add(plate);
        geometries.add(rulings);
        geometries.add(outline);
        const dark = new THREE.MeshStandardMaterial({
          color: 0x35513b,
          roughness: 0.85,
          metalness: 0,
        });
        const charcoal = new THREE.MeshStandardMaterial({
          color: 0x2b3c2f,
          roughness: 0.86,
          metalness: 0,
        });
        const sage = new THREE.MeshStandardMaterial({
          color: 0xc1d99d,
          roughness: 0.8,
          metalness: 0,
        });
        const darkRulings = new THREE.LineBasicMaterial({
          color: 0xa1b591,
          transparent: true,
          opacity: 0.19,
        });
        const sageRulings = new THREE.LineBasicMaterial({
          color: 0x35513b,
          transparent: true,
          opacity: 0.34,
        });
        const edgeMaterial = new THREE.LineBasicMaterial({
          color: 0xa9b59b,
          transparent: true,
          opacity: 0.15,
        });
        for (const material of [
          dark,
          charcoal,
          sage,
          darkRulings,
          sageRulings,
          edgeMaterial,
        ])
          materials.add(material);

        stack = new THREE.Group();
        for (let index = 0; index < 9; index += 1) {
          const layer = new THREE.Group();
          const isSelected = index === 6;
          layer.position.y = -0.84 + index * 0.21;
          const mesh = new THREE.Mesh(
            plate,
            isSelected ? sage : index % 2 === 0 ? dark : charcoal,
          );
          mesh.castShadow = true;
          mesh.receiveShadow = true;
          layer.add(mesh);
          layer.add(
            new THREE.LineSegments(
              rulings,
              isSelected ? sageRulings : darkRulings,
            ),
          );
          layer.add(new THREE.LineSegments(outline, edgeMaterial));
          stack.add(layer);
          if (isSelected) selected = layer;
        }
        scene.add(stack);
        const floorGeometry = new THREE.PlaneGeometry(14, 14);
        const floorMaterial = new THREE.ShadowMaterial({ opacity: 0.16 });
        geometries.add(floorGeometry);
        materials.add(floorMaterial);
        const floor = new THREE.Mesh(floorGeometry, floorMaterial);
        floor.rotation.x = -Math.PI / 2;
        floor.position.y = -1.17;
        floor.receiveShadow = true;
        scene.add(floor);
        return true;
      } catch {
        failed = true;
        release();
        return false;
      }
    };

    const render = (time: number) => {
      if (!renderer || !scene || !camera || !stack || !selected) return;
      const rect = host.getBoundingClientRect();
      const nextWidth = Math.max(1, Math.round(rect.width));
      const nextHeight = Math.max(1, Math.round(rect.height));
      if (width !== nextWidth || height !== nextHeight) {
        width = nextWidth;
        height = nextHeight;
        renderer.setSize(width, height, false);
        const aspect = width / height;
        const vertical = Math.max(2.55, 3.1 / aspect);
        camera.left = -vertical * aspect;
        camera.right = vertical * aspect;
        camera.top = vertical;
        camera.bottom = -vertical;
        camera.updateProjectionMatrix();
      }
      const progress = THREE.MathUtils.clamp(progressRef.current, 0, 1);
      const separation = 0.25 + progress * 0.75;
      stack.rotation.y = -0.18 + Math.sin(time * 0.16) * 0.025;
      stack.position.set(-0.2, Math.sin(time * 0.5) * 0.035, 0);
      selected.position.x = separation * 0.9;
      selected.position.z = separation * 0.95;
      selected.position.y = 0.42 + separation * 0.12;
      renderer.render(scene, camera);
      if (!canvasRevealed) {
        canvasRevealed = true;
        setRendererKind("webgl");
      }
    };

    const frame = (timestamp: number) => {
      animationFrame = 0;
      if (!canRender()) {
        stop();
        return;
      }
      try {
        render(
          frozenTime ??
            elapsed + (timestamp - (runningSince ?? timestamp)) / 1000,
        );
      } catch {
        failed = true;
        release();
        return;
      }
      if (frozenTime === null) animationFrame = requestAnimationFrame(frame);
    };

    const sync = () => {
      if (preferFallback()) {
        release();
        return;
      }
      if (!canRender()) {
        stop();
        return;
      }
      if (!renderer && !initialize()) return;
      if (animationFrame) return;
      runningSince ??= performance.now();
      animationFrame = requestAnimationFrame(frame);
    };
    syncRef.current = sync;
    const intersection = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting && entry.intersectionRatio > 0;
      sync();
    });
    const resize = new ResizeObserver(sync);
    intersection.observe(host);
    resize.observe(host);
    document.addEventListener("visibilitychange", sync);
    motionPreference.addEventListener("change", sync);
    connection?.addEventListener("change", sync);

    return () => {
      disposed = true;
      syncRef.current = null;
      intersection.disconnect();
      resize.disconnect();
      document.removeEventListener("visibilitychange", sync);
      motionPreference.removeEventListener("change", sync);
      connection?.removeEventListener("change", sync);
      release();
    };
  }, [progressRef]);

  return (
    <div
      className="sliver-scene"
      data-renderer={rendererKind}
      aria-hidden="true"
    >
      <div className="sliver-scene__fallback">
        {Array.from({ length: 9 }, (_, index) => (
          <span
            key={index}
            className={`sliver-scene__plate${index === 6 ? " sliver-scene__plate--selected" : ""}`}
            style={{ "--plate-index": index } as CSSProperties}
          >
            <i />
            <i />
            <i />
            <i />
            <i />
            <i />
          </span>
        ))}
      </div>
      <div className="sliver-scene__canvas" ref={canvasHostRef} />
    </div>
  );
}
