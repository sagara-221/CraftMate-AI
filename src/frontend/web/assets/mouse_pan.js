// mouse_pan.js
export function enableMousePan(camera, renderer, options = {}) {
    const panSpeed = options.panSpeed ?? 0.005;

    let isPanning = false;
    let previousPosition = { x: 0, y: 0 };

    renderer.domElement.addEventListener("mousedown", (event) => {
        if (event.button === 1) { // 中ボタン
            isPanning = true;
            previousPosition = { x: event.clientX, y: event.clientY };
            event.preventDefault();
        }
    });

    renderer.domElement.addEventListener("mousemove", (event) => {
        if (!isPanning) return;

        const deltaX = event.clientX - previousPosition.x;
        const deltaY = event.clientY - previousPosition.y;

        camera.position.x -= deltaX * panSpeed;
        camera.position.y += deltaY * panSpeed;

        previousPosition = { x: event.clientX, y: event.clientY };
    });

    window.addEventListener("mouseup", () => {
        isPanning = false;
    });
}
