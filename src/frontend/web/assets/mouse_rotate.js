export function enableMouseRotation(renderer, targetMeshRef) {
    let isDragging = false;
    let previousMousePosition = { x: 0, y: 0 };
    const rotationSpeed = 0.01;

    renderer.domElement.addEventListener('mousedown', (event) => {
        if (event.button === 2) { // 右クリックのみ
            isDragging = true;
            previousMousePosition = { x: event.clientX, y: event.clientY };
            event.preventDefault();
        }
    });

    renderer.domElement.addEventListener('mousemove', (event) => {
        if (!isDragging || !targetMeshRef.mesh) return;

        const deltaMove = {
            x: event.clientX - previousMousePosition.x,
            y: event.clientY - previousMousePosition.y
        };

        const deltaRotation = new THREE.Quaternion()
            .setFromEuler(new THREE.Euler(
                deltaMove.y * rotationSpeed,
                deltaMove.x * rotationSpeed,
                0,
                'XYZ'
            ));

        targetMeshRef.mesh.quaternion.multiplyQuaternions(
            deltaRotation,
            targetMeshRef.mesh.quaternion
        );

        previousMousePosition = { x: event.clientX, y: event.clientY };
    });

    document.addEventListener('mouseup', () => {
        isDragging = false;
    });

    // コンテキストメニュー（右クリックメニュー）を無効化
    renderer.domElement.addEventListener('contextmenu', (e) => e.preventDefault());
}
