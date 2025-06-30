// mouse_zoom.js
export function enableMouseZoom(camera, renderer, options = {}) {
    const zoomSpeed = options.zoomSpeed ?? 0.01;
    const minZ = options.minZ ?? 0.5;
    const maxZ = options.maxZ ?? 100;

    renderer.domElement.addEventListener("wheel", (event) => {
        event.preventDefault();

        // Z位置を更新
        camera.position.z += event.deltaY * zoomSpeed;

        // 範囲制限
        camera.position.z = Math.min(Math.max(camera.position.z, minZ), maxZ);
    }, { passive: false });
}
