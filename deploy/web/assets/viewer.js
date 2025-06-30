import { enableMouseRotation } from "./mouse_rotate.js";
import { enableMouseZoom } from "./mouse_zoom.js";
import { enableMousePan } from "./mouse_pan.js";

/* ---------- DOM 取得 ---------- */
const container = document.getElementById("viewer");

/* ---------- Three.js 基本 ---------- */
const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(
    75,
    container.clientWidth / container.clientHeight,
    0.1,
    1000
);
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.setSize(container.clientWidth, container.clientHeight, false);
renderer.setClearColor(0xffffff);
container.appendChild(renderer.domElement);

/* ---------- ライト ---------- */
scene.add(new THREE.AmbientLight(0xffffff, 0.6));
const dirLight = new THREE.DirectionalLight(0xffffff, 0.4);
dirLight.position.set(5, 5, 5);
scene.add(dirLight);

/* ---------- 操作系 ---------- */
const target = { mesh: null };
enableMouseRotation(renderer, target);
enableMouseZoom(camera, renderer);
enableMousePan(camera, renderer, { panSpeed: 0.005 });

/* ---------- カメラをメッシュにフィットさせる関数 ---------- */
function fitCameraToObject(cam, object, offset = 1.2) {
    if (!object) return;

    const box = new THREE.Box3().setFromObject(object);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());

    /* ---------- 距離計算 ---------- */
    // 縦方向（既存）
    const vFov = THREE.MathUtils.degToRad(cam.fov);
    let distV = (size.y / 2) / Math.tan(vFov / 2);

    // 横方向（追加）
    const hFov = 2 * Math.atan(Math.tan(vFov / 2) * cam.aspect);
    let distH = (size.x / 2) / Math.tan(hFov / 2);

    // 最終距離 ＝ 大きい方
    let dist = Math.max(distV, distH) * offset;

    /* ---------- カメラセット ---------- */
    cam.near = dist / 100;
    cam.far = dist * 100;
    cam.position.set(center.x, center.y, center.z + dist);
    cam.lookAt(center);
    cam.updateProjectionMatrix();
}


/* ---------- ★ リサイズ監視 ---------- */
function handleResize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (w === 0 || h === 0) return;

    camera.aspect = w / h;
    camera.updateProjectionMatrix();   // ← 先にアスペクト反映
    renderer.setSize(w, h);            // ★ 第3引数を省略（true）
    fitCameraToObject(camera, target.mesh, 1.05);
}

new ResizeObserver(handleResize).observe(container);
window.addEventListener("resize", handleResize);

/* ---------- OBJ 受信 ---------- */
window.addEventListener("message", async ({ data }) => {
    const objText = data?.objText;
    const groupColors = data?.groupColors || {};
    if (!objText) return;

    /* --- OBJ 解析 --- */
    const { vertices, faces, groups, groupNames } = parseOBJ(objText);

    const geom = new THREE.BufferGeometry();
    const flat = [];
    faces.forEach(f => f.forEach(i => flat.push(...vertices[i])));
    geom.setAttribute("position", new THREE.Float32BufferAttribute(flat, 3));
    geom.computeVertexNormals();
    geom.clearGroups();
    groups.forEach((g, i) => geom.addGroup(i * 3, 3, g));

    /* index→name マップ */
    const idx2name = {};
    groupNames.forEach((n, i) => idx2name[groups[i]] ??= n);

    /* マテリアル配列生成 */
    const maxIndex = Math.max(...groups, 0);   // 欠番を含めた最大値
    const materials = Array.from({ length: maxIndex + 1 }).map((_, idx) => {
        const name = groupNames[groups.indexOf(idx)] || "";   // 見つからない場合は空文字
        const hex = groupColors[name] || "#cccccc";
        return new THREE.MeshStandardMaterial({ color: new THREE.Color(hex), side: THREE.DoubleSide });
    });
    /* 既存メッシュを置き換え */
    if (target.mesh) scene.remove(target.mesh);
    target.mesh = new THREE.Mesh(geom, materials);
    scene.add(target.mesh);

    /* ▼ ここで毎回カメラをフィットさせる */
    fitCameraToObject(camera, target.mesh, 1.1);
    handleResize();                   // 内部バッファも今のサイズで再設定
});

/* ---------- レンダリングループ ---------- */
(function animate() {
    requestAnimationFrame(animate);
    renderer.render(scene, camera);
})();
window.parent.postMessage({ threeViewerReady: true }, '*');
// function logState(tag) {
//     // 子メッシュ数
//     const meshCount = scene.children.filter(o => o.isMesh).length;
//     // Canvas サイズ
//     const { width, height } = renderer.getSize(new THREE.Vector2());
//     // コンテキストが lost していないか
//     const lost = renderer.getContext().isContextLost();
//     console.log(`[${tag}] mesh=${meshCount}  size=${width}x${height}  lost=${lost}`);
// }

// window.addEventListener('resize', () => logState('window.resize'));
// window.addEventListener('message', () => logState('message'));
// new ResizeObserver(() => logState('ResizeObserver')).observe(container);

/* ---------- OBJ パーサ ---------- */
function parseOBJ(text) {
    const v = [], f = [], g = [], names = [];
    let curIdx = 0, curName = "";
    const map = {};
    text.split("\n").forEach(line => {
        const l = line.trim();
        if (l.startsWith("v ")) {
            const [, x, y, z] = l.split(/\s+/);
            v.push([+x, +y, +z]);
        } else if (l.startsWith("f ")) {
            const [, ...idx] = l.split(/\s+/).map(s => +s.split("/")[0] - 1);
            for (let i = 1; i < idx.length - 1; i++) {
                f.push([idx[0], idx[i], idx[i + 1]]);
                g.push(curIdx);
                names.push(curName);
            }
        } else if (l.startsWith("g ")) {
            const n = l.slice(2).trim();
            map[n] ??= Object.keys(map).length;
            curIdx = map[n];
            curName = n;
        }
    });

    /* 正規化 [-1,1] */
    let m = 0;
    v.forEach(([x, y, z]) => m = Math.max(m, Math.abs(x), Math.abs(y), Math.abs(z)));
    if (m) v.forEach(p => { p[0] /= m; p[1] /= m; p[2] /= m; });
    return { vertices: v, faces: f, groups: g, groupNames: names };
}


const params = new URLSearchParams(window.location.search);
const role = params.get('role') || 'unknown';

window.parent.postMessage({ threeViewerReady: true, role }, '*');