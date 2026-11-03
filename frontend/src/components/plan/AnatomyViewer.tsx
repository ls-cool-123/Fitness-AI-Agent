import { Loader2, RefreshCw, Bone } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { DRACOLoader } from "three/addons/loaders/DRACOLoader.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

import { Button } from "@/components/ui/button";
import { groupForMuscle } from "@/lib/anatomy";
import type { MuscleGroupId } from "@/types/plan";

type ViewerStatus = "loading" | "ready" | "error";

interface ViewerApi {
  selectGroup: (group: MuscleGroupId | null) => void;
  resetView: () => void;
  setBonesVisible: (visible: boolean) => void;
}

interface AnatomyMeta {
  type?: string;
  name?: string;
  nameDetail?: string;
}

const BASE_COLOR = 0xc98b6b;
const DIM_COLOR = 0x6b5a52;
const HIGHLIGHT_COLOR = 0xd99a72;
const BRAND_COLOR = 0xff6a2b;

/** 从 mesh 自身或祖先节点读取 glTF extras。 */
function anatomyMeta(object: THREE.Object3D): AnatomyMeta {
  let node: THREE.Object3D | null = object;
  let fallbackName = "";
  while (node) {
    const data = node.userData as Record<string, unknown>;
    const name = typeof data.name === "string" ? data.name : node.name;
    if (!fallbackName) fallbackName = name;
    if (typeof data.type === "string") {
      return {
        type: data.type,
        name,
        nameDetail:
          typeof data.nameDetail === "string" ? data.nameDetail : name,
      };
    }
    node = node.parent;
  }
  return { name: fallbackName };
}

/** 释放一个已加载模型（加载完成时组件可能已经卸载）。 */
function disposeObject(root: THREE.Object3D): void {
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry?.dispose();
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of materials) material?.dispose();
  });
}

/**
 * Three.js 人体肌肉图。
 *
 * 交互：
 * - 拖拽旋转、滚轮缩放；
 * - 点击某块肌肉 → 按肌群高亮 + 镜头聚焦（从该肌群所在的前/后/侧方向看）；
 * - 顶部可切换骨骼、重置视角。
 *
 * 模型有 800+ 个 mesh，所以只把肌肉 mesh 放进 raycast 列表，骨骼默认隐藏。
 */
export function AnatomyViewer({
  selectedGroup,
  onSelectGroup,
}: {
  selectedGroup: MuscleGroupId | null;
  onSelectGroup: (group: MuscleGroupId) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<ViewerApi | null>(null);
  const selectedRef = useRef<MuscleGroupId | null>(selectedGroup);
  const onSelectRef = useRef(onSelectGroup);
  const bonesVisibleRef = useRef(false);
  const [status, setStatus] = useState<ViewerStatus>("loading");
  const [showBones, setShowBones] = useState(false);

  useEffect(() => {
    selectedRef.current = selectedGroup;
    apiRef.current?.selectGroup(selectedGroup);
  }, [selectedGroup]);

  useEffect(() => {
    onSelectRef.current = onSelectGroup;
  }, [onSelectGroup]);

  useEffect(() => {
    bonesVisibleRef.current = showBones;
    apiRef.current?.setBonesVisible(showBones);
  }, [showBones]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const host = container;

    let disposed = false;
    let frame = 0;
    let resizeObserver: ResizeObserver | null = null;
    let renderer: THREE.WebGLRenderer;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.05, 100);
    camera.position.set(0, 0.3, 4);

    try {
      renderer = new THREE.WebGLRenderer({
        antialias: true,
        alpha: true,
        powerPreference: "high-performance",
      });
    } catch (error) {
      console.error("WebGLRenderer 初始化失败", error);
      setStatus("error");
      return;
    }

    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(1, 1);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.15;
    renderer.setClearColor(0x000000, 0);
    renderer.domElement.style.touchAction = "none";
    renderer.domElement.style.display = "block";
    host.appendChild(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.screenSpacePanning = false;
    controls.minDistance = 0.5;
    controls.maxDistance = 12;

    scene.add(new THREE.HemisphereLight(0xffffff, 0x2a2a2a, 1.4));
    const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
    keyLight.position.set(3, 5, 4);
    scene.add(keyLight);
    const fillLight = new THREE.DirectionalLight(0xffffff, 0.9);
    fillLight.position.set(-4, 2, -3);
    scene.add(fillLight);

    const defaultMuscleMaterial = new THREE.MeshStandardMaterial({
      color: BASE_COLOR,
      roughness: 0.72,
      metalness: 0.04,
    });
    const boneMaterial = new THREE.MeshStandardMaterial({
      color: 0xd9d4c8,
      roughness: 0.9,
      metalness: 0.02,
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
    });

    const groupMaterials = new Map<MuscleGroupId, THREE.MeshStandardMaterial>();
    const groupMeshes = new Map<MuscleGroupId, THREE.Mesh[]>();
    const muscleMeshes: THREE.Mesh[] = [];
    const boneMeshes: THREE.Mesh[] = [];
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();

    const defaultCameraPos = new THREE.Vector3(0, 0.3, 4);
    const defaultTarget = new THREE.Vector3(0, 0, 0);
    let bodyCenter = new THREE.Vector3();
    let focusTween: {
      startedAt: number;
      fromPosition: THREE.Vector3;
      toPosition: THREE.Vector3;
      fromTarget: THREE.Vector3;
      toTarget: THREE.Vector3;
    } | null = null;

    function groupMaterial(group: MuscleGroupId): THREE.MeshStandardMaterial {
      const existing = groupMaterials.get(group);
      if (existing) return existing;
      const material = new THREE.MeshStandardMaterial({
        color: BASE_COLOR,
        roughness: 0.7,
        metalness: 0.04,
      });
      groupMaterials.set(group, material);
      return material;
    }

    function applySelection(group: MuscleGroupId | null): void {
      const highlight = new THREE.Color(BRAND_COLOR);
      const base = new THREE.Color(BASE_COLOR);
      const dim = new THREE.Color(DIM_COLOR);
      const highlightSurface = new THREE.Color(HIGHLIGHT_COLOR);

      for (const [id, material] of groupMaterials) {
        if (group === null) {
          material.color.copy(base);
          material.emissive.setHex(0x000000);
          material.emissiveIntensity = 0;
        } else if (id === group) {
          material.color.copy(highlightSurface);
          material.emissive.copy(highlight);
          material.emissiveIntensity = 0.32;
        } else {
          material.color.copy(dim);
          material.emissive.setHex(0x000000);
          material.emissiveIntensity = 0;
        }
      }

      if (group === null) {
        focusTween = {
          startedAt: performance.now(),
          fromPosition: camera.position.clone(),
          toPosition: defaultCameraPos.clone(),
          fromTarget: controls.target.clone(),
          toTarget: defaultTarget.clone(),
        };
      } else {
        focusGroup(group);
      }
    }

    function focusGroup(group: MuscleGroupId): void {
      const meshes = groupMeshes.get(group);
      if (!meshes || meshes.length === 0) return;

      const box = new THREE.Box3();
      for (const mesh of meshes) box.expandByObject(mesh);
      const center = box.getCenter(new THREE.Vector3());
      const sphere = box.getBoundingSphere(new THREE.Sphere());
      const radius = Math.max(sphere.radius, 0.15);

      // 从肌群所在的前/后/侧方向看过去：胸/腹在前，背/臀在后，四肢偏侧
      const direction = new THREE.Vector3(
        Math.sign(center.x - bodyCenter.x) * 0.55,
        0.18,
        Math.sign(center.z - bodyCenter.z) || 1,
      );
      if (direction.lengthSq() < 0.01) direction.set(0, 0.2, 1);
      direction.normalize();

      const distance = Math.max(radius * 3.6, 0.7);
      focusTween = {
        startedAt: performance.now(),
        fromPosition: camera.position.clone(),
        toPosition: center.clone().add(direction.multiplyScalar(distance)),
        fromTarget: controls.target.clone(),
        toTarget: center,
      };
    }

    function setBonesVisible(visible: boolean): void {
      bonesVisibleRef.current = visible;
      for (const mesh of boneMeshes) mesh.visible = visible;
    }

    apiRef.current = {
      selectGroup: applySelection,
      resetView: () => {
        focusTween = {
          startedAt: performance.now(),
          fromPosition: camera.position.clone(),
          toPosition: defaultCameraPos.clone(),
          fromTarget: controls.target.clone(),
          toTarget: defaultTarget.clone(),
        };
      },
      setBonesVisible,
    };

    function onResize(): void {
      const width = host.clientWidth;
      const height = host.clientHeight;
      if (!width || !height) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    }

    resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(host);
    onResize();

    let pointerDownX = 0;
    let pointerDownY = 0;
    function onPointerDown(event: PointerEvent): void {
      if (event.button !== 0) return;
      pointerDownX = event.clientX;
      pointerDownY = event.clientY;
    }
    function onPointerUp(event: PointerEvent): void {
      if (event.button !== 0) return;
      if (
        Math.hypot(event.clientX - pointerDownX, event.clientY - pointerDownY) >
        6
      ) {
        return;
      }
      const rect = renderer.domElement.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
      raycaster.setFromCamera(pointer, camera);
      const hits = raycaster.intersectObjects(muscleMeshes, false);
      for (const hit of hits) {
        const data = hit.object.userData as Record<string, unknown>;
        const group = data.__group as MuscleGroupId | undefined;
        if (group) {
          onSelectRef.current(group);
          break;
        }
      }
    }
    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointerup", onPointerUp);

    const loader = new GLTFLoader();
    const draco = new DRACOLoader();
    draco.setDecoderPath(`${import.meta.env.BASE_URL}draco/`);
    loader.setDRACOLoader(draco);

    loader.load(
      `${import.meta.env.BASE_URL}models/body.glb`,
      (gltf) => {
        if (disposed) {
          disposeObject(gltf.scene);
          return;
        }
        const model = gltf.scene;
        scene.add(model);

        // 统一缩放到约 2.2 个世界单位高，并把身体中心移到原点
        const rawBox = new THREE.Box3().setFromObject(model);
        const rawSize = rawBox.getSize(new THREE.Vector3());
        const maxDim = Math.max(rawSize.x, rawSize.y, rawSize.z) || 1;
        model.scale.setScalar(2.2 / maxDim);
        const scaledBox = new THREE.Box3().setFromObject(model);
        const center = scaledBox.getCenter(new THREE.Vector3());
        model.position.sub(center);

        const finalBox = new THREE.Box3().setFromObject(model);
        const sphere = finalBox.getBoundingSphere(new THREE.Sphere());
        bodyCenter = sphere.center.clone();
        defaultTarget.copy(sphere.center);
        defaultCameraPos.set(
          sphere.center.x,
          sphere.center.y + sphere.radius * 0.12,
          sphere.center.z + sphere.radius * 3.1,
        );
        camera.position.copy(defaultCameraPos);
        controls.target.copy(defaultTarget);
        controls.update();

        model.traverse((object) => {
          const mesh = object as THREE.Mesh;
          if (!mesh.isMesh) return;
          const meta = anatomyMeta(mesh);
          if (meta.type === "bone") {
            mesh.material = boneMaterial;
            mesh.visible = bonesVisibleRef.current;
            boneMeshes.push(mesh);
            return;
          }
          if (meta.type !== "muscle") {
            mesh.visible = false;
            return;
          }
          const group = groupForMuscle(meta.nameDetail || meta.name || mesh.name);
          if (group) {
            mesh.material = groupMaterial(group);
            const list = groupMeshes.get(group) ?? [];
            list.push(mesh);
            groupMeshes.set(group, list);
            mesh.userData.__group = group;
          } else {
            mesh.material = defaultMuscleMaterial;
          }
          muscleMeshes.push(mesh);
        });

        setStatus("ready");
        applySelection(selectedRef.current);
      },
      undefined,
      (error) => {
        if (disposed) return;
        console.error("人体模型加载失败", error);
        setStatus("error");
      },
    );

    function animate(): void {
      frame = requestAnimationFrame(animate);
      if (focusTween) {
        const elapsed = performance.now() - focusTween.startedAt;
        const t = Math.min(1, elapsed / 450);
        const eased = t * t * (3 - 2 * t);
        camera.position.lerpVectors(
          focusTween.fromPosition,
          focusTween.toPosition,
          eased,
        );
        controls.target.lerpVectors(
          focusTween.fromTarget,
          focusTween.toTarget,
          eased,
        );
        if (t >= 1) focusTween = null;
      }
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      resizeObserver?.disconnect();
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointerup", onPointerUp);
      controls.dispose();
      draco.dispose();
      apiRef.current = null;
      scene.traverse((object) => {
        const mesh = object as THREE.Mesh;
        if (!mesh.isMesh) return;
        mesh.geometry?.dispose();
      });
      for (const material of [
        ...groupMaterials.values(),
        defaultMuscleMaterial,
        boneMaterial,
      ]) {
        material.dispose();
      }
      renderer.dispose();
      renderer.domElement.remove();
      scene.clear();
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="relative h-[26rem] w-full overflow-hidden rounded-xl border border-hairline bg-page sm:h-[34rem]"
    >
      <div className="pointer-events-none absolute top-3 left-3 z-10 rounded-full border border-hairline bg-card/90 px-2.5 py-1 text-[11px] text-ink-muted">
        拖拽旋转 · 滚轮缩放 · 点击肌肉
      </div>

      <div className="absolute top-3 right-3 z-10 flex gap-1.5">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="h-7 bg-card/90 px-2 text-xs"
          onClick={() => setShowBones((value) => !value)}
          aria-pressed={showBones}
        >
          <Bone />
          {showBones ? "隐藏骨骼" : "显示骨骼"}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          className="size-7 bg-card/90"
          onClick={() => apiRef.current?.resetView()}
          aria-label="重置视角"
        >
          <RefreshCw />
        </Button>
      </div>

      {status === "loading" ? (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-card/60 text-sm text-ink-2 backdrop-blur-[2px]">
          <Loader2 className="size-5 animate-spin text-brand" />
          正在加载人体模型…
        </div>
      ) : null}

      {status === "error" ? (
        <div className="absolute inset-0 z-20 flex flex-col items-center justify-center gap-2 bg-card/85 px-6 text-center text-sm text-ink-2">
          <span className="font-medium text-ink">3D 模型加载失败</span>
          <span className="text-xs">
            仍可使用右侧肌群列表选择部位并生成计划；也可以刷新页面重试。
          </span>
        </div>
      ) : null}
    </div>
  );
}
