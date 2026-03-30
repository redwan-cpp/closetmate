"""
ClosetMate Backend Test Script
Tests all endpoints: root, auth (register, login, profile), wardrobe (add, list, delete), 
recommend, skin_tone, upload (analyze-clothing), image processing.
"""
import json
import sys
import os
import requests
import time
import io
from PIL import Image

BASE = "http://localhost:8000"
RESULTS = []

def ok(name, r, expected_status=None):
    status = r.status_code
    try:
        body = r.json()
    except Exception:
        body = r.text[:200]
    
    passed = True
    if expected_status and status != expected_status:
        passed = False
    
    emoji = "PASS" if passed else "FAIL"
    print(f"[{emoji}] [{status}] {name}")
    if not passed:
        print(f"   Expected: {expected_status}, Got: {status}")
    print(f"   Body: {json.dumps(body, indent=2)[:300]}")
    RESULTS.append({"name": name, "status": status, "passed": passed, "body": body})
    return body if passed else None

print("=" * 60)
print("ClosetMate Backend Test Suite")
print("=" * 60)

# 1. Root
print("\n--- 1. Root ---")
r = requests.get(f"{BASE}/")
ok("GET /", r, 200)

# 2. Register
print("\n--- 2. Auth: Register ---")
unique = str(int(time.time()))
reg_payload = {
    "name": "Test User",
    "email": f"testuser{unique}@closetmate.app",
    "password": "Secure123!",
    "gender": "male",
    "body_shape": "athletic",
    "skin_tone": "warm",
    "style_preference": "casual"
}
r = requests.post(f"{BASE}/auth/register", json=reg_payload)
reg_body = ok("POST /auth/register", r, 201)

user_id = None
token = None
if reg_body:
    user_id = reg_body.get("user_id")

# 3. Login
print("\n--- 3. Auth: Login ---")
login_payload = {"email": reg_payload["email"], "password": reg_payload["password"]}
r = requests.post(f"{BASE}/auth/login", json=login_payload)
login_body = ok("POST /auth/login", r, 200)
if login_body:
    token = login_body.get("token")
    if not user_id:
        user_id = login_body.get("user_id")

# 4. Profile (authenticated)
print("\n--- 4. Auth: Profile ---")
if token:
    r = requests.get(f"{BASE}/auth/profile", headers={"Authorization": f"Bearer {token}"})
    ok("GET /auth/profile", r, 200)
else:
    print("   Skipped (no token)")

# 5. Duplicate email register (should fail)
print("\n--- 5. Auth: Duplicate Registration ---")
r = requests.post(f"{BASE}/auth/register", json=reg_payload)
ok("POST /auth/register (duplicate => 400)", r, 400)

# 6. Wrong password login
print("\n--- 6. Auth: Wrong Password ---")
r = requests.post(f"{BASE}/auth/login", json={"email": reg_payload["email"], "password": "wrongpass"})
ok("POST /auth/login (wrong pw => 401)", r, 401)

# 7. Add wardrobe item
print("\n--- 7. Wardrobe: Add Item ---")
item_id = None
if user_id:
    wrd_payload = {
        "user_id": user_id,
        "category": "Shirt",
        "primary_color": "blue",
        "material": "cotton",
        "pattern": "solid",
        "formality_level": "casual",
        "cultural_style": None,
        "image_path": "uploads/processed/test.png"
    }
    r = requests.post(f"{BASE}/wardrobe/add-item", json=wrd_payload)
    wrd_body = ok("POST /wardrobe/add-item", r, 201)
    if wrd_body:
        item_id = wrd_body.get("item_id")
else:
    print("   Skipped (no user_id)")

# Add a bottom item for outfit recommendation
print("\n--- 7b. Wardrobe: Add Bottom Item ---")
if user_id:
    bot_payload = {
        "user_id": user_id,
        "category": "Jeans",
        "primary_color": "black",
        "material": "denim",
        "pattern": "solid",
        "formality_level": "casual",
        "cultural_style": None,
        "image_path": "uploads/processed/test2.png"
    }
    r = requests.post(f"{BASE}/wardrobe/add-item", json=bot_payload)
    ok("POST /wardrobe/add-item (jeans)", r, 201)

# 8. List wardrobe items
print("\n--- 8. Wardrobe: List Items ---")
if user_id:
    r = requests.get(f"{BASE}/wardrobe/items/{user_id}")
    ok("GET /wardrobe/items/{user_id}", r, 200)
else:
    print("   Skipped (no user_id)")

# 9. Outfit recommendation
print("\n--- 9. Recommend: Outfit ---")
if user_id:
    rec_payload = {
        "user_id": user_id,
        "occasion": "casual",
        "environment": "outdoor",
        "temperature": 28.5,
        "humidity": 60.0
    }
    r = requests.post(f"{BASE}/recommend/outfit", json=rec_payload)
    ok("POST /recommend/outfit", r, 200)
else:
    print("   Skipped (no user_id)")

# 10. Delete wardrobe item
print("\n--- 10. Wardrobe: Delete Item ---")
if item_id:
    r = requests.delete(f"{BASE}/wardrobe/item/{item_id}")
    ok("DELETE /wardrobe/item/{item_id}", r, 200)
else:
    print("   Skipped (no item_id)")

# 11. Delete non-existent item
print("\n--- 11. Wardrobe: Delete Non-existent ---")
r = requests.delete(f"{BASE}/wardrobe/item/nonexistent-id")
ok("DELETE /wardrobe/item (not found => 404)", r, 404)

# 12. Profile without auth (should fail)
print("\n--- 12. Auth: Profile Without Token ---")
r = requests.get(f"{BASE}/auth/profile")
ok("GET /auth/profile (no auth => 401)", r, 401)

# 13. Skin tone detection with a dummy image
print("\n--- 13. Skin Tone Detection ---")
img = Image.new("RGB", (100, 100), color=(200, 150, 120))
buf = io.BytesIO()
img.save(buf, format="PNG")
buf.seek(0)
r = requests.post(f"{BASE}/analyze-skin-tone", files={"file": ("test.png", buf, "image/png")})
ok("POST /analyze-skin-tone", r, 200)

# 14. Analyze image (lighting)
print("\n--- 14. Lighting Analysis ---")
img2 = Image.new("RGB", (100, 100), color=(180, 160, 140))
buf2 = io.BytesIO()
img2.save(buf2, format="PNG")
buf2.seek(0)
r = requests.post(f"{BASE}/analyze-image", files={"file": ("test.png", buf2, "image/png")})
ok("POST /analyze-image", r, 200)

# 15. OpenAPI docs accessible?
print("\n--- 15. OpenAPI Docs ---")
r = requests.get(f"{BASE}/docs")
print(f"  {'PASS' if r.status_code == 200 else 'FAIL'} [{r.status_code}] GET /docs")

# Summary
print("\n" + "=" * 60)
print("TEST SUMMARY")
print("=" * 60)
passed = sum(1 for r in RESULTS if r['passed'])
total = len(RESULTS)
print(f"  Passed: {passed}/{total}")
failed = [r for r in RESULTS if not r['passed']]
if failed:
    print("\n  FAILED TESTS:")
    for f in failed:
        print(f"  FAIL: {f['name']} (got {f['status']})")
        print(f"     {json.dumps(f['body'])[:200]}")
print("=" * 60)
