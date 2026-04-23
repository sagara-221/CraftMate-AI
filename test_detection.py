import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), 'src', 'backend'))

from ai_modules.parts_detection import detect_parts_from_bytes

with open("images/shelf.jpg", "rb") as f:
    b = f.read()

try:
    print("Calling detect_parts_from_bytes...")
    res = detect_parts_from_bytes(b, "image/jpeg")
    print(res)
except Exception as e:
    import traceback
    traceback.print_exc()
