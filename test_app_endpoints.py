"""
Test app.py POST endpoints on port 8001:
- POST /analyze-image (lighting analysis)
- POST /remove-background (PNG binary)
- POST /remove-bg (base64 JSON)
- POST /style-image (editorial PNG)
"""
import json
import io
import requests
from PIL import Image

BASE = "http://localhost:8001"
RESULTS = []


def ok(name, r, expected_status=None):
    status = r.status_code
    try:
        body = r.json()
    except Exception:
        body = r.text[:300]
    passed = True
    if expected_status and status != expected_status:
        passed = False
    emoji = "PASS" if passed else "FAIL"
    print(f"[{emoji}] [{status}] {name}")
    if not passed:
        print(f"   Expected: {expected_status}, Got: {status}")
    body_str = json.dumps(body) if isinstance(body, (dict, list)) else str(body)
    print(f"   Body: {body_str[:300]}")
    RESULTS.append({"name": name, "status": status, "passed": passed, "body": body})
    return body if passed else None


def make_png(w=200, h=200, color=(200, 150, 120)):
    img = Image.new("RGB", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


print("=" * 60)
print("app.py Image Processing Endpoints (port 8001)")
print("=" * 60)

# 1. POST /analyze-image
print("\n--- 1. Lighting Analysis (/analyze-image) ---")
buf = make_png(color=(100, 120, 140))
r = requests.post(f"{BASE}/analyze-image", files={"file": ("test.png", buf, "image/png")})
ok("POST /analyze-image", r, 200)

# 2. POST /remove-background (returns PNG binary)
print("\n--- 2. Remove Background (/remove-background) ---")
buf = make_png(color=(200, 100, 100))
r = requests.post(f"{BASE}/remove-background", files={"file": ("test.png", buf, "image/png")})
status_ok = r.status_code == 200
print(f"  [{'PASS' if status_ok else 'FAIL'}] [{r.status_code}] POST /remove-background")
if status_ok:
    print(f"   Content-Type: {r.headers.get('content-type')}, Size: {len(r.content)} bytes")
    RESULTS.append({"name": "POST /remove-background", "status": r.status_code, "passed": True, "body": "binary PNG"})
else:
    try:
        body = r.json()
    except Exception:
        body = r.text[:200]
    print(f"   Body: {body}")
    RESULTS.append({"name": "POST /remove-background", "status": r.status_code, "passed": False, "body": body})

# 3. POST /remove-bg (base64 JSON)
print("\n--- 3. Remove Background Base64 (/remove-bg) ---")
buf = make_png(color=(100, 200, 100))
r = requests.post(f"{BASE}/remove-bg", files={"file": ("test.png", buf, "image/png")})
body = ok("POST /remove-bg", r, 200)
if body and isinstance(body, dict):
    img_b64 = body.get("image", "")
    print(f"   base64 image length: {len(img_b64)} chars")

# 4. POST /remove-bg with empty file (should fail)
print("\n--- 4. Empty File to /remove-bg ---")
r = requests.post(f"{BASE}/remove-bg", files={"file": ("empty.png", io.BytesIO(b""), "image/png")})
ok("POST /remove-bg (empty => 400)", r, 400)

# 5. POST /style-image (editorial background + rembg)
print("\n--- 5. Style Image (/style-image) ---")
buf = make_png(w=300, h=400, color=(80, 120, 200))
r = requests.post(f"{BASE}/style-image", files={"file": ("test.png", buf, "image/png")})
status_ok = r.status_code == 200
print(f"  [{'PASS' if status_ok else 'FAIL'}] [{r.status_code}] POST /style-image")
if status_ok:
    print(f"   Content-Type: {r.headers.get('content-type')}, Size: {len(r.content)} bytes")
    RESULTS.append({"name": "POST /style-image", "status": r.status_code, "passed": True, "body": "binary JPEG"})
else:
    try:
        body = r.json()
    except Exception:
        body = r.text[:200]
    print(f"   Body: {body}")
    RESULTS.append({"name": "POST /style-image", "status": r.status_code, "passed": False, "body": body})

# Summary
print("\n" + "=" * 60)
print("TEST SUMMARY (app.py)")
print("=" * 60)
passed = sum(1 for r in RESULTS if r['passed'])
total = len(RESULTS)
print(f"  Passed: {passed}/{total}")
failed = [r for r in RESULTS if not r['passed']]
if failed:
    print("\n  FAILED TESTS:")
    for f in failed:
        print(f"  FAIL: {f['name']} (got {f['status']})")
        print(f"     {json.dumps(f['body'])[:300]}")
print("=" * 60)
