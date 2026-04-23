import requests
import time
import json
import os

BASE_URL = "http://localhost:8000/api"
TOKEN = "changeme-token"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}"
}

IMAGE_PATH = "/Users/sagara/craftmate-agent/images/shelf.jpg"


def poll_ready(plan_id, endpoint, label, max_attempts=60, interval=10):
    """指定エンドポイントが ready になるまでポーリング"""
    print(f"  Waiting for {label}...")
    for i in range(max_attempts):
        res = requests.get(f"{BASE_URL}/{plan_id}/{endpoint}", headers=HEADERS)
        if res.status_code == 200 and res.json().get("ready"):
            print(f"  {label} is ready!")
            return True
        print(f"  Waiting... ({i+1}/{max_attempts})")
        time.sleep(interval)
    print(f"  Timeout waiting for {label}.")
    return False


def main():
    # ============================================================
    # Step 1: Upload
    # ============================================================
    print("=" * 60)
    print("1. Uploading image...")
    with open(IMAGE_PATH, "rb") as f:
        files = {"file": ("shelf.jpg", f, "image/jpeg")}
        res = requests.post(f"{BASE_URL}/upload", headers=HEADERS, files=files)

    if res.status_code != 200:
        print(f"   FAIL: Upload failed ({res.status_code}): {res.text}")
        return
    plan_id = res.json()["plan_id"]
    print(f"   OK: Plan ID = {plan_id}")

    # ============================================================
    # Step 2: Wait for parts_list
    # ============================================================
    print("=" * 60)
    print("2. Waiting for parts_list to be generated...")
    if not poll_ready(plan_id, "parts/ready", "parts_list"):
        return

    # Fetch parts list
    res = requests.get(f"{BASE_URL}/{plan_id}/parts", headers=HEADERS)
    if res.status_code == 200:
        parts = res.json()
        print(f"   OK: {len(parts)} parts detected")
        for p in parts:
            print(f"     - {p.get('part_name', p.get('name', '?'))}: {p.get('size', '?')}")
    else:
        print(f"   FAIL: Could not fetch parts ({res.status_code})")

    # ============================================================
    # Step 3: Wait for 3D model
    # ============================================================
    print("=" * 60)
    print("3. Waiting for 3D model to be generated...")
    if not poll_ready(plan_id, "model/ready", "3D model"):
        return

    # Fetch model
    res = requests.get(f"{BASE_URL}/{plan_id}/model", headers=HEADERS)
    if res.status_code == 200:
        obj_text = res.body if hasattr(res, 'body') else res.text
        lines = obj_text.strip().split('\n')
        print(f"   OK: OBJ model received ({len(lines)} lines)")
    else:
        print(f"   FAIL: Could not fetch model ({res.status_code})")

    # ============================================================
    # Step 4: Chat API (A2A)
    # ============================================================
    print("=" * 60)
    print("4. Testing Chat API (A2A workflow)...")
    chat_payload = {"message": "棚板の高さを5cm高くしてください"}
    print("   Sending chat request...")
    print("   (Designer Agent と Reviewer Agent が連携して設計を修正します)")
    res = requests.post(
        f"{BASE_URL}/{plan_id}/chat",
        headers={**HEADERS, "Content-Type": "application/json"},
        json=chat_payload,
    )

    if res.status_code == 200:
        data = res.json()
        print("   OK: Chat completed successfully!")
        print()
        print("   --- Agent Logs (A2A やりとり) ---")
        for log in data.get("agent_logs", []):
            print(f"   {log}")
        print("   ---------------------------------")
        print()
        updated_parts = data.get("parts_list", [])
        print(f"   Updated parts count: {len(updated_parts)}")
    else:
        print(f"   FAIL: Chat failed ({res.status_code}): {res.text}")

    # ============================================================
    # Step 5: Verify local storage
    # ============================================================
    print("=" * 60)
    print("5. Verifying local storage...")
    local_dir = f"/Users/sagara/craftmate-agent/src/backend/local_data/{plan_id}"
    if os.path.isdir(local_dir):
        files = os.listdir(local_dir)
        print(f"   OK: local_data/{plan_id}/ contains {len(files)} files:")
        for fname in sorted(files):
            fpath = os.path.join(local_dir, fname)
            size = os.path.getsize(fpath)
            print(f"     - {fname} ({size:,} bytes)")
    else:
        print(f"   FAIL: Directory not found: {local_dir}")

    print("=" * 60)
    print("All tests completed.")


if __name__ == "__main__":
    main()
