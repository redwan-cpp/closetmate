"""Private photo storage: services/photo_store.py, POST /photos, GET /files, DELETE /photos/{id},
?store=1 on /studio-shot, and how items / looks / worn history / chat present and clean up photos."""
from __future__ import annotations

import io

import pytest
from PIL import Image

from conftest import make_photo
from services import photo_store as ps

BOX = (100, 100, 300, 400)
PHOTO = make_photo(size=(400, 500), subjects=[(BOX, (200, 30, 30))])
UID = "11111111-2222-3333-4444-555555555555"
PID = "a" * 32
KEY = f"photos/{UID}/{PID}.webp"


def png(size=(40, 50), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def cutout_png(size=(60, 80)) -> bytes:
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    img.paste((30, 90, 200, 255), (15, 20, 45, 60))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def upload(client, account, data=None, content_type="image/png", name="p.png"):
    return client.post("/photos", headers=account.headers,
                       files={"file": (name, png() if data is None else data, content_type)})


def fetch(client, link):
    return client.get("/" + link)


def rows(sql, user_id=None):
    if user_id:
        return sql("SELECT * FROM photos WHERE user_id = :u", u=user_id)
    return sql("SELECT * FROM photos")


# ---------------------------------------------------------------------------
# Keys and links
# ---------------------------------------------------------------------------

class TestKeys:
    @pytest.mark.parametrize("key", [KEY, f"photos/{UID}/{PID}.jpg", f"photos/{UID}/{PID}_t.webp", "photos/u_1-x/" + PID + ".jpg"])
    def test_well_formed_keys_match(self, key):
        assert ps.KEY_RE.match(key)

    @pytest.mark.parametrize("key", [
        "", "photos/", "photos/../x.webp", f"photos/{UID}/../{PID}.webp", f"photos/{UID}/{PID}.png",
        f"photos/{UID}/{PID.upper()}.webp", f"photos/{UID}/short.webp", f"photos/{UID}/{PID}.webp/x",
        f"photos//{PID}.webp", f"/photos/{UID}/{PID}.webp", f"photos/{UID}/{PID}.webp\n", "uploads/a.webp",
        f"photos/a b/{PID}.webp", f"photos/{'u' * 65}/{PID}.webp", f"photos/{UID}/{PID}_t_t.webp",
    ])
    def test_everything_else_is_refused(self, key):
        assert ps.KEY_RE.match(key) is None

    def test_key_owner_only_for_full_size_keys(self):
        assert ps.key_owner(KEY) == UID
        assert ps.key_owner(f"photos/{UID}/{PID}_t.webp") is None
        assert ps.key_owner("uploads/x.jpg") is None and ps.key_owner(None) is None and ps.key_owner("") is None

    def test_make_keys(self):
        pid, key, thumb = ps.make_keys(UID, "jpg")
        assert len(pid) == 32 and key == f"photos/{UID}/{pid}.jpg" and thumb == f"photos/{UID}/{pid}_t.jpg"
        assert ps.make_keys(UID, "webp", photo_id=PID)[0] == PID

    def test_content_types(self):
        assert ps.content_type_for(KEY) == "image/webp"
        assert ps.content_type_for(f"photos/{UID}/{PID}.jpg") == "image/jpeg"
        assert ps.content_type_for("nope") == "application/octet-stream"


class TestLinks:
    def test_a_link_verifies(self):
        link = ps.link(KEY)
        assert link.startswith(f"files/{KEY}?e=")
        e, s = link.split("?")[1].split("&")
        assert ps.verify_link(KEY, e[2:], s[2:])

    def test_the_same_photo_gets_the_same_link_within_a_window(self):
        now = 1_000_000.0
        assert ps.link(KEY, now) == ps.link(KEY, now + 60)

    def test_a_link_lives_between_half_and_all_of_the_ttl(self, set_env):
        set_env(PHOTO_URL_TTL_SECONDS=3600)
        for now in (0.0, 1799.0, 1800.0, 12345.0, 99999.0):
            expires = int(ps.link(KEY, now).split("e=")[1].split("&")[0])
            assert 1800 <= expires - now <= 3600

    def test_different_windows_give_different_links(self):
        assert ps.link(KEY, 0) != ps.link(KEY, 10 * 3600)

    def test_the_signature_is_bound_to_the_key(self):
        e, s = ps.link(KEY).split("?")[1].split("&")
        other = f"photos/{UID}/{'b' * 32}.webp"
        assert not ps.verify_link(other, e[2:], s[2:])
        assert not ps.verify_link(f"photos/{UID}/{PID}_t.webp", e[2:], s[2:])       # nor to its thumbnail

    def test_the_signature_is_bound_to_the_expiry(self):
        e, s = ps.link(KEY).split("?")[1].split("&")
        assert not ps.verify_link(KEY, str(int(e[2:]) + 1), s[2:])

    def test_tampering_is_refused(self):
        e, s = (x[2:] for x in ps.link(KEY).split("?")[1].split("&"))
        assert not ps.verify_link(KEY, e, s[:-1] + ("A" if s[-1] != "A" else "B"))
        assert not ps.verify_link(KEY, e, "")
        assert not ps.verify_link(KEY, "", s)
        assert not ps.verify_link(KEY, "abc", s)
        assert not ps.verify_link(KEY, "-5", s)
        assert not ps.verify_link(KEY, "9" * 20, s)
        assert not ps.verify_link("photos/../x", e, s)

    def test_an_expired_link_is_refused(self):
        link = ps.link(KEY, now=1000.0)
        e, s = (x[2:] for x in link.split("?")[1].split("&"))
        assert not ps.verify_link(KEY, e, s)                      # expired decades ago
        assert ps.verify_link(KEY, e, s, now=float(e) - 1)
        assert not ps.verify_link(KEY, e, s, now=float(e) + 1)

    def test_a_different_jwt_secret_invalidates_every_link(self, set_env):
        set_env(JWT_SECRET="first-secret-" + "a" * 40)
        e, s = (x[2:] for x in ps.link(KEY).split("?")[1].split("&"))
        assert ps.verify_link(KEY, e, s)
        set_env(JWT_SECRET="second-secret-" + "b" * 40)
        assert not ps.verify_link(KEY, e, s)


class TestPresent:
    def test_a_photo_key_becomes_two_links(self):
        image, thumb = ps.present(KEY)
        assert image.startswith(f"files/{KEY}?e=") and thumb.startswith(f"files/photos/{UID}/{PID}_t.webp?e=")

    def test_the_jpeg_variant_keeps_its_extension(self):
        image, thumb = ps.present(f"photos/{UID}/{PID}.jpg")
        assert ".jpg?" in image and "_t.jpg?" in thumb

    @pytest.mark.parametrize("path", [
        "file:///data/x.jpg", "uploads/processed/x.jpg", "https://storage.googleapis.com/b/x.jpg",
        f"photos/{UID}/{PID}_t.webp", "photos/garbage", "", None,
    ])
    def test_anything_else_is_returned_unchanged_without_a_thumbnail(self, path):
        assert ps.present(path) == (path, None)


# ---------------------------------------------------------------------------
# DiskStore
# ---------------------------------------------------------------------------

class TestDiskStore:
    def test_put_get_delete(self, tmp_path):
        store = ps.DiskStore(tmp_path)
        store.put(KEY, b"abc", "image/webp")
        assert store.get(KEY) == b"abc"
        store.delete(KEY)
        assert store.get(KEY) is None
        store.delete(KEY)                                         # deleting twice is fine

    def test_a_missing_key_is_none_not_an_error(self, tmp_path):
        assert ps.DiskStore(tmp_path).get(KEY) is None

    @pytest.mark.parametrize("bad", ["../x.webp", "photos/../../x.webp", "/etc/passwd", "photos/u/x.webp", ""])
    def test_keys_that_could_escape_the_root_are_refused(self, tmp_path, bad):
        store = ps.DiskStore(tmp_path / "root")
        with pytest.raises(ValueError):
            store.put(bad, b"x", "image/webp")
        with pytest.raises(ValueError):
            store.get(bad)
        with pytest.raises(ValueError):
            store.delete(bad)

    def test_delete_user_removes_only_that_users_folder(self, tmp_path):
        store = ps.DiskStore(tmp_path)
        mine = [f"photos/{UID}/{i:032x}.webp" for i in range(3)]
        theirs = f"photos/other-user/{PID}.webp"
        for k in mine + [theirs]:
            store.put(k, b"x", "image/webp")
        assert store.delete_user(UID) == 3
        assert all(store.get(k) is None for k in mine) and store.get(theirs) == b"x"
        assert store.delete_user(UID) == 0

    @pytest.mark.parametrize("bad", ["..", "../x", "a/../..", ""])
    def test_delete_user_refuses_paths_outside_photos(self, tmp_path, bad):
        with pytest.raises(ValueError):
            ps.DiskStore(tmp_path).delete_user(bad)


# ---------------------------------------------------------------------------
# prepare_photo
# ---------------------------------------------------------------------------

def decode(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


class TestPreparePhoto:
    def test_an_opaque_photo_becomes_a_jpeg(self):
        p = ps.prepare_photo(png())
        assert p.ext == "jpg" and decode(p.full).format == "JPEG" and decode(p.thumb).format == "JPEG"

    def test_a_cutout_stays_a_transparent_webp(self):
        p = ps.prepare_photo(cutout_png())
        assert p.ext == "webp" and decode(p.full).format == "WEBP"
        assert decode(p.full).convert("RGBA").getchannel("A").getextrema()[0] == 0

    def test_a_png_whose_alpha_is_fully_opaque_is_just_a_jpeg(self):
        img = Image.new("RGBA", (30, 30), (10, 20, 30, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        assert ps.prepare_photo(buf.getvalue()).ext == "jpg"

    def test_a_palette_png_with_transparency_counts_as_a_cutout(self):
        img = Image.new("P", (20, 20), 0)
        img.putpalette([255, 0, 0] * 256)
        buf = io.BytesIO()
        img.save(buf, format="PNG", transparency=0)
        assert ps.prepare_photo(buf.getvalue()).ext == "webp"

    def test_large_photos_are_capped_and_a_thumbnail_is_made(self):
        p = ps.prepare_photo(png(size=(3000, 2000)))
        assert max(decode(p.full).size) == ps.MAX_SIDE and (p.width, p.height) == decode(p.full).size
        w, h = decode(p.thumb).size
        assert w <= 320 and h <= 400 and (w == 320 or h == 400)

    def test_small_photos_are_not_upscaled(self):
        p = ps.prepare_photo(png(size=(50, 60)))
        assert decode(p.full).size == (50, 60) and decode(p.thumb).size == (50, 60)

    def test_exif_is_dropped_and_the_orientation_applied(self):
        jpeg = make_photo(size=(400, 500), fmt="JPEG", exif_orientation=6)
        assert len(decode(jpeg).getexif()) > 0                                # the input does carry EXIF
        out = decode(ps.prepare_photo(jpeg).full)
        assert len(out.getexif()) == 0 and "exif" not in out.info
        assert out.size == (500, 400)                                         # rotated upright

    def test_the_output_is_never_the_clients_bytes(self):
        data = png()
        assert ps.prepare_photo(data).full != data

    @pytest.mark.parametrize("junk", [b"", b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"\x89PNG\r\n\x1a\n" + b"0" * 20])
    def test_junk_is_a_photo_error(self, junk):
        with pytest.raises(ps.PhotoError, match="Cannot decode"):
            ps.prepare_photo(junk)

    def test_a_decompression_bomb_is_a_photo_error(self, monkeypatch):
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
        with pytest.raises(ps.PhotoError):
            ps.prepare_photo(png(size=(400, 400)))


# ---------------------------------------------------------------------------
# POST /photos
# ---------------------------------------------------------------------------

class TestUploadEndpoint:
    def test_a_photo_is_stored_and_recorded(self, client, alice, sql):
        resp = upload(client, alice)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert set(body) == {"photo_id", "image_path", "bytes", "image_url", "thumb_url", "mime", "width", "height"}
        assert body["image_path"] == f"photos/{alice.user_id}/{body['photo_id']}.jpg" and body["mime"] == "image/jpeg"
        assert (body["width"], body["height"]) == (40, 50)
        store = ps.get_store()
        assert store.get(body["image_path"]) and store.get(f"photos/{alice.user_id}/{body['photo_id']}_t.jpg")
        (row,) = rows(sql, alice.user_id)
        assert row["key"] == body["image_path"] and row["size_bytes"] == body["bytes"] > 0

    def test_a_cutout_is_kept_as_a_transparent_webp(self, client, alice):
        body = upload(client, alice, cutout_png()).json()
        assert body["image_path"].endswith(".webp") and body["mime"] == "image/webp"

    def test_the_returned_links_work_without_a_token(self, client, alice):
        body = upload(client, alice).json()
        for link in (body["image_url"], body["thumb_url"]):
            resp = fetch(client, link)
            assert resp.status_code == 200 and resp.headers["content-type"] == "image/jpeg"
            assert Image.open(io.BytesIO(resp.content)).format == "JPEG"

    def test_the_stored_file_is_re_encoded_not_the_upload(self, client, alice):
        data = make_photo(size=(400, 500), fmt="JPEG", exif_orientation=3)
        body = upload(client, alice, data, "image/jpeg", "p.jpg").json()
        stored = ps.get_store().get(body["image_path"])
        assert stored != data and len(decode(stored).getexif()) == 0

    def test_it_needs_a_token(self, client):
        assert client.post("/photos", files={"file": ("p.png", png(), "image/png")}).status_code == 401

    def test_the_content_type_must_be_an_image(self, client, alice):
        assert upload(client, alice, b"<html>", "text/html", "x.html").status_code == 400

    def test_bytes_that_are_not_an_image_are_422(self, client, alice):
        assert upload(client, alice, b"definitely not a picture").status_code == 422

    def test_an_empty_upload_is_400(self, client, alice):
        assert upload(client, alice, b"").status_code == 400

    def test_a_missing_file_field_is_422(self, client, alice):
        assert client.post("/photos", headers=alice.headers).status_code == 422

    def test_oversize_uploads_are_413_and_store_nothing(self, client, alice, set_env, sql):
        set_env(MAX_UPLOAD_BYTES=100)
        assert upload(client, alice, png(size=(200, 200))).status_code == 413
        assert rows(sql) == []

    def test_too_many_pixels_is_413(self, client, alice, set_env):
        set_env(MAX_IMAGE_PIXELS=1000)
        assert upload(client, alice, png(size=(100, 100))).status_code == 413

    def test_nothing_is_stored_for_a_rejected_upload(self, client, alice, sql):
        upload(client, alice, b"junk")
        assert rows(sql) == [] and not list(ps.get_store().root.rglob("*.*"))

    def test_the_per_user_cap(self, client, alice, bob, set_env, sql):
        set_env(MAX_PHOTOS_PER_USER=2)
        assert [upload(client, alice).status_code for _ in range(2)] == [201, 201]
        full = upload(client, alice)
        assert full.status_code == 403 and full.json()["detail"]["code"] == "photos_full"
        assert upload(client, bob).status_code == 201             # the cap is per user
        assert len(rows(sql, alice.user_id)) == 2

    def test_a_storage_failure_is_a_500_and_leaves_nothing_behind(self, client, alice, sql, monkeypatch):
        store = ps.get_store()
        monkeypatch.setattr(store, "put", lambda *a, **k: (_ for _ in ()).throw(OSError("disk on fire")))
        resp = upload(client, alice)
        assert resp.status_code == 500 and "disk on fire" not in resp.text
        assert rows(sql) == []

    def test_if_the_thumbnail_fails_the_full_image_is_removed_again(self, client, alice, sql, monkeypatch):
        store = ps.get_store()
        real_put, calls = store.put, []

        def flaky(key, data, content_type):
            calls.append(key)
            if len(calls) == 2:
                raise OSError("second write failed")
            real_put(key, data, content_type)

        monkeypatch.setattr(store, "put", flaky)
        assert upload(client, alice).status_code == 500
        assert store.get(calls[0]) is None and rows(sql) == []

    def test_sixty_a_minute_then_429(self, client, alice):
        codes = [upload(client, alice, png(size=(8, 8))).status_code for _ in range(61)]
        assert codes[:60] == [201] * 60 and codes[60] == 429


# ---------------------------------------------------------------------------
# GET /files
# ---------------------------------------------------------------------------

class TestServeEndpoint:
    def test_the_response_is_cacheable_and_not_sniffable(self, client, alice):
        resp = fetch(client, upload(client, alice).json()["image_url"])
        assert resp.headers["cache-control"] == "private, max-age=31536000, immutable"
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_a_bad_signature_is_403(self, client, alice):
        link = upload(client, alice).json()["image_url"]
        assert fetch(client, link[:-2] + "xx").status_code == 403

    def test_a_missing_signature_is_403(self, client, alice):
        key = upload(client, alice).json()["image_path"]
        assert client.get(f"/files/{key}").status_code == 403
        assert client.get(f"/files/{key}?e=9999999999").status_code == 403

    def test_an_expired_link_is_403(self, client, alice):
        key = upload(client, alice).json()["image_path"]
        assert fetch(client, ps.link(key, now=1000.0)).status_code == 403

    def test_a_link_for_another_photo_does_not_work(self, client, alice):
        a, b = (upload(client, alice).json() for _ in range(2))
        e_s = a["image_url"].split("?", 1)[1]
        assert client.get(f"/files/{b['image_path']}?{e_s}").status_code == 403

    def test_a_valid_link_to_a_deleted_object_is_404(self, client, alice):
        body = upload(client, alice).json()
        ps.get_store().delete(body["image_path"])
        assert fetch(client, body["image_url"]).status_code == 404

    @pytest.mark.parametrize("path", [
        "files/photos/../../main.py?e=9999999999&s=x", "files/../main.py", "files/photos/x/y.webp?e=1&s=2",
        "files/uploads/processed/a.jpg?e=9999999999&s=x", "files/%2e%2e/main.py",
    ])
    def test_nothing_outside_the_photo_keys_is_ever_served(self, client, path):
        assert client.get("/" + path).status_code in (403, 404)

    def test_a_storage_error_is_502_without_details(self, client, alice, monkeypatch):
        body = upload(client, alice).json()
        monkeypatch.setattr(ps.get_store(), "get", lambda key: (_ for _ in ()).throw(OSError("secret path /srv/x")))
        resp = fetch(client, body["image_url"])
        assert resp.status_code == 502 and "secret" not in resp.text

    def test_a_link_cannot_be_retargeted_at_another_users_key(self, client, two_users):
        alice, bob = two_users
        mine = upload(client, alice).json()
        guess = f"photos/{bob.user_id}/{mine['photo_id']}.jpg"
        assert fetch(client, mine["image_url"].replace(mine["image_path"], guess)).status_code == 403


# ---------------------------------------------------------------------------
# Using a stored photo on an item
# ---------------------------------------------------------------------------

def add(client, account, image_path, **extra):
    payload = {"user_id": account.user_id, "image_path": image_path, "category": "top", "subcategory": "shirt",
               "primary_color": "white", **extra}
    return client.post("/wardrobe/add-item", headers=account.headers, json=payload)


def items(client, account):
    return client.get(f"/wardrobe/items/{account.user_id}", headers=account.headers).json()


class TestItemsWithStoredPhotos:
    def test_the_database_keeps_the_key_and_responses_show_links(self, client, alice, sql):
        key = upload(client, alice).json()["image_path"]
        item = add(client, alice, key).json()["item_id"]
        assert sql("SELECT image_path FROM wardrobe_items WHERE item_id = :i", i=item)[0]["image_path"] == key
        (listed,) = items(client, alice)
        assert listed["image_path"].startswith(f"files/{key}?e=") and "_t.jpg?e=" in listed["thumb_url"]
        assert fetch(client, listed["image_path"]).status_code == 200 and fetch(client, listed["thumb_url"]).status_code == 200

    def test_legacy_paths_are_unchanged_and_have_no_thumbnail(self, client, alice):
        add(client, alice, "uploads/processed/old.jpg")
        (listed,) = items(client, alice)
        assert listed["image_path"] == "uploads/processed/old.jpg" and listed["thumb_url"] is None

    def test_a_photo_that_is_not_yours_is_404(self, client, two_users):
        alice, bob = two_users
        key = upload(client, alice).json()["image_path"]
        assert add(client, bob, key).status_code == 404

    def test_a_key_that_was_never_uploaded_is_404(self, client, alice):
        assert add(client, alice, f"photos/{alice.user_id}/{'c' * 32}.webp").status_code == 404

    def test_a_key_naming_another_user_is_404_even_if_it_exists(self, client, two_users):
        alice, bob = two_users
        key = upload(client, bob).json()["image_path"]
        assert add(client, alice, key).status_code == 404

    def test_one_photo_cannot_back_two_items(self, client, alice):
        key = upload(client, alice).json()["image_path"]
        assert add(client, alice, key).status_code == 201
        assert add(client, alice, key).status_code == 409

    @pytest.mark.parametrize("bad", [f"photos/{UID}/x.webp", "photos/", "photos/../x", f"photos/{UID}/{PID}_t.webp"])
    def test_malformed_photo_keys_are_422(self, client, alice, bad):
        assert add(client, alice, bad).status_code == 422

    def test_deleting_the_item_deletes_its_photo(self, client, alice, sql):
        body = upload(client, alice).json()
        item = add(client, alice, body["image_path"]).json()["item_id"]
        assert client.delete(f"/wardrobe/item/{item}", headers=alice.headers).status_code == 200
        store = ps.get_store()
        assert store.get(body["image_path"]) is None and store.get(f"photos/{alice.user_id}/{body['photo_id']}_t.jpg") is None
        assert rows(sql, alice.user_id) == []

    def test_deleting_a_legacy_item_touches_no_photos(self, client, alice, sql):
        keep = upload(client, alice).json()
        item = add(client, alice, "uploads/processed/old.jpg").json()["item_id"]
        client.delete(f"/wardrobe/item/{item}", headers=alice.headers)
        assert ps.get_store().get(keep["image_path"]) and len(rows(sql)) == 1

    def test_deleting_someone_elses_item_deletes_nothing(self, client, two_users, sql):
        alice, bob = two_users
        body = upload(client, alice).json()
        item = add(client, alice, body["image_path"]).json()["item_id"]
        assert client.delete(f"/wardrobe/item/{item}", headers=bob.headers).status_code == 404
        assert ps.get_store().get(body["image_path"]) and len(rows(sql)) == 1


class TestReplacingWithStoredPhotos:
    def replace(self, client, account, item, path):
        return client.patch(f"/wardrobe/item/{item}/image", headers=account.headers, json={"image_path": path})

    def test_the_replaced_stored_photo_is_deleted(self, client, alice, sql):
        old, new = upload(client, alice).json(), upload(client, alice).json()
        item = add(client, alice, old["image_path"]).json()["item_id"]
        assert self.replace(client, alice, item, new["image_path"]).status_code == 200
        store = ps.get_store()
        assert store.get(old["image_path"]) is None and store.get(new["image_path"])
        assert [r["key"] for r in rows(sql, alice.user_id)] == [new["image_path"]]
        assert items(client, alice)[0]["image_path"].startswith(f"files/{new['image_path']}")

    def test_replacing_with_a_legacy_path_still_deletes_the_stored_photo(self, client, alice, sql):
        old = upload(client, alice).json()
        item = add(client, alice, old["image_path"]).json()["item_id"]
        self.replace(client, alice, item, "uploads/processed/x.jpg")
        assert ps.get_store().get(old["image_path"]) is None and rows(sql) == []

    def test_replacing_a_legacy_photo_with_a_stored_one_works(self, client, alice):
        item = add(client, alice, "file:///data/old.jpg").json()["item_id"]
        new = upload(client, alice).json()
        assert self.replace(client, alice, item, new["image_path"]).status_code == 200

    def test_setting_the_same_photo_again_keeps_it(self, client, alice):
        body = upload(client, alice).json()
        item = add(client, alice, body["image_path"]).json()["item_id"]
        assert self.replace(client, alice, item, body["image_path"]).status_code == 200
        assert ps.get_store().get(body["image_path"])

    def test_you_cannot_attach_someone_elses_photo(self, client, two_users):
        alice, bob = two_users
        theirs = upload(client, bob).json()["image_path"]
        mine = add(client, alice, "file:///x.jpg").json()["item_id"]
        assert self.replace(client, alice, mine, theirs).status_code == 404

    def test_you_cannot_steal_a_photo_from_your_other_item(self, client, alice):
        a, b = upload(client, alice).json(), upload(client, alice).json()
        add(client, alice, a["image_path"])
        second = add(client, alice, b["image_path"]).json()["item_id"]
        assert self.replace(client, alice, second, a["image_path"]).status_code == 409
        assert ps.get_store().get(b["image_path"])                 # and nothing was deleted by the failed attempt

    def test_a_missing_item_is_404_and_deletes_nothing(self, client, alice):
        body = upload(client, alice).json()
        assert self.replace(client, alice, "no-such-item", body["image_path"]).status_code == 404
        assert ps.get_store().get(body["image_path"])


class TestOtherListingsShowLinks:
    def make(self, client, alice, **kw):
        body = upload(client, alice).json()
        item = add(client, alice, body["image_path"], **kw).json()["item_id"]
        return body, item

    def test_saved_looks(self, client, alice):
        body, item = self.make(client, alice)
        client.post("/wardrobe/looks", headers=alice.headers, json={"user_id": alice.user_id, "item_ids": [item]})
        (look,) = client.get(f"/wardrobe/looks/{alice.user_id}", headers=alice.headers).json()
        (shown,) = look["items"]
        assert shown["image_path"].startswith(f"files/{body['image_path']}?e=") and "_t.jpg?e=" in shown["thumb_url"]
        assert fetch(client, shown["thumb_url"]).status_code == 200

    def test_worn_history(self, client, alice):
        body, item = self.make(client, alice)
        client.post("/wardrobe/log-worn", headers=alice.headers, json={"user_id": alice.user_id, "item_ids": [item]})
        (log,) = client.get(f"/wardrobe/worn-history/{alice.user_id}", headers=alice.headers).json()
        assert log["items"][0]["image_path"].startswith(f"files/{body['image_path']}?e=")
        assert "_t.jpg?e=" in log["items"][0]["thumb_url"]

    def test_stylist_suggestions(self, client, alice, fake_llm):
        import json

        body, item = self.make(client, alice, subcategory="shirt", primary_color="white")
        fake_llm.openai_reply = "Wear it. <outfit>" + json.dumps(
            {"items": [{"item_id": item, "subcategory": "shirt", "color": "white"}]}) + "</outfit>"
        resp = client.post("/chat/message", headers=alice.headers,
                           json={"user_id": alice.user_id, "message": "what should I wear?", "history": []})
        (suggested,) = resp.json()["suggested_items"]
        assert suggested["image_url"].startswith(f"files/{body['image_path']}?e=")
        assert "_t.jpg?e=" in suggested["thumb_url"]


# ---------------------------------------------------------------------------
# DELETE /photos/{photo_id}
# ---------------------------------------------------------------------------

class TestDiscardingAnUnusedPhoto:
    def test_an_unattached_photo_can_be_discarded(self, client, alice, sql):
        body = upload(client, alice).json()
        resp = client.delete(f"/photos/{body['photo_id']}", headers=alice.headers)
        assert resp.status_code == 200 and resp.json() == {"status": "deleted", "photo_id": body["photo_id"]}
        assert ps.get_store().get(body["image_path"]) is None and rows(sql) == []

    def test_a_photo_in_use_is_409_and_kept(self, client, alice):
        body = upload(client, alice).json()
        add(client, alice, body["image_path"])
        assert client.delete(f"/photos/{body['photo_id']}", headers=alice.headers).status_code == 409
        assert ps.get_store().get(body["image_path"])

    def test_someone_elses_photo_is_404_and_kept(self, client, two_users):
        alice, bob = two_users
        body = upload(client, alice).json()
        assert client.delete(f"/photos/{body['photo_id']}", headers=bob.headers).status_code == 404
        assert ps.get_store().get(body["image_path"])

    @pytest.mark.parametrize("bad", ["x", "A" * 32, "a" * 31, "%2e%2e", "a" * 33, "a" * 32 + "%0a"])
    def test_malformed_ids_are_404(self, client, alice, bad):
        assert client.delete(f"/photos/{bad}", headers=alice.headers).status_code == 404

    def test_it_needs_a_token(self, client, alice):
        body = upload(client, alice).json()
        assert client.delete(f"/photos/{body['photo_id']}").status_code == 401

    def test_discarding_twice_is_404(self, client, alice):
        body = upload(client, alice).json()
        client.delete(f"/photos/{body['photo_id']}", headers=alice.headers)
        assert client.delete(f"/photos/{body['photo_id']}", headers=alice.headers).status_code == 404


# ---------------------------------------------------------------------------
# POST /studio-shot?store=1
# ---------------------------------------------------------------------------

@pytest.fixture
def model(fake_cutout):
    fake_cutout.boxes = [BOX]
    return fake_cutout


def shot(client, account, query="", path="/studio-shot", data=PHOTO):
    return client.post(path + query, headers=account.headers, files={"file": ("p.png", data, "image/png")})


@pytest.mark.parametrize("path", ["/studio-shot", "/images/studio-shot"])
class TestStudioShotStore:
    def test_without_the_flag_nothing_is_stored(self, client, alice, model, sql, path):
        body = shot(client, alice, path=path).json()
        assert "image_path" not in body and rows(sql) == []

    def test_with_the_flag_it_is_stored_and_the_response_says_where(self, client, alice, model, sql, path):
        resp = shot(client, alice, "?store=1", path)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["image_path"] == f"photos/{alice.user_id}/{body['photo_id']}.webp"
        assert body["image"] and body["thumb"] and body["cutout_ok"] is True       # the preview is still there
        assert fetch(client, body["image_url"]).status_code == 200 and fetch(client, body["thumb_url"]).status_code == 200
        assert len(rows(sql, alice.user_id)) == 1

    def test_the_stored_file_is_the_studio_shot_itself(self, client, alice, model, path):
        import base64

        body = shot(client, alice, "?store=1", path).json()
        stored = ps.get_store().get(body["image_path"])
        assert stored == base64.b64decode(body["image"])
        assert decode(ps.get_store().get(f"photos/{alice.user_id}/{body['photo_id']}_t.webp")).size == (320, 400)

    def test_the_stored_photo_can_go_straight_onto_an_item(self, client, alice, model, path):
        body = shot(client, alice, "?store=1", path).json()
        assert add(client, alice, body["image_path"]).status_code == 201

    def test_it_costs_one_unit_like_before(self, client, alice, model, usage_count, path):
        shot(client, alice, "?store=1", path)
        assert usage_count(alice.user_id, "bgremove") == 1

    def test_an_unusable_photo_stores_nothing_and_costs_nothing(self, client, alice, model, sql, usage_count, path):
        model.boxes = []
        assert shot(client, alice, "?store=1", path).status_code == 422
        assert rows(sql) == [] and usage_count(alice.user_id, "bgremove") == 0

    def test_a_full_photo_store_is_403_and_the_unit_comes_back(self, client, alice, model, set_env, usage_count, path):
        set_env(MAX_PHOTOS_PER_USER=1)
        assert shot(client, alice, "?store=1", path).status_code == 200
        full = shot(client, alice, "?store=1", path)
        assert full.status_code == 403 and full.json()["detail"]["code"] == "photos_full"
        assert usage_count(alice.user_id, "bgremove") == 1                    # only the first one was charged

    def test_a_storage_failure_is_a_500_and_the_unit_comes_back(self, client, alice, model, usage_count, monkeypatch, path):
        monkeypatch.setattr(ps.get_store(), "put", lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
        assert shot(client, alice, "?store=1", path).status_code == 500
        assert usage_count(alice.user_id, "bgremove") == 0

    @pytest.mark.parametrize("flag", ["?store=0", "?store=false", ""])
    def test_other_values_do_not_store(self, client, alice, model, sql, path, flag):
        shot(client, alice, flag, path)
        assert rows(sql) == []


# ---------------------------------------------------------------------------
# GcsStore (production backend) against a fake client — no network, no credentials
# ---------------------------------------------------------------------------

class _FakeBlob:
    def __init__(self, bucket, name):
        self.bucket, self.name, self.cache_control = bucket, name, None

    def upload_from_string(self, data, content_type=None):
        self.bucket.objects[self.name] = {"data": data, "content_type": content_type, "cache_control": self.cache_control}

    def download_as_bytes(self):
        from google.api_core.exceptions import NotFound

        if self.name not in self.bucket.objects:
            raise NotFound("missing")
        return self.bucket.objects[self.name]["data"]

    def delete(self):
        from google.api_core.exceptions import NotFound

        if self.name not in self.bucket.objects:
            raise NotFound("missing")
        del self.bucket.objects[self.name]

    # Deliberately NO make_public() and NO generate_signed_url(): photos are private, and the
    # code must never try to publish or sign one. Calling either raises AttributeError.


class _FakeBucket:
    def __init__(self, name):
        self.name, self.objects = name, {}

    def blob(self, name):
        return _FakeBlob(self, name)


class _FakeClient:
    buckets: dict = {}

    def bucket(self, name):
        return self.buckets.setdefault(name, _FakeBucket(name))

    def list_blobs(self, bucket, prefix=""):
        return [_FakeBlob(bucket, n) for n in sorted(bucket.objects) if n.startswith(prefix)]


@pytest.fixture
def gcs(monkeypatch):
    import google.cloud.storage as storage

    _FakeClient.buckets = {}
    monkeypatch.setattr(storage, "Client", _FakeClient)
    store = ps.GcsStore("closet-photos")
    return store, _FakeClient.buckets["closet-photos"]


class TestGcsStore:
    def test_put_stores_the_bytes_with_type_and_long_cache_headers(self, gcs):
        store, bucket = gcs
        store.put(KEY, b"abc", "image/webp")
        assert bucket.objects[KEY] == {"data": b"abc", "content_type": "image/webp",
                                       "cache_control": "private, max-age=31536000, immutable"}

    def test_get_returns_the_bytes_or_none(self, gcs):
        store, _ = gcs
        store.put(KEY, b"abc", "image/webp")
        assert store.get(KEY) == b"abc" and store.get(f"photos/{UID}/{'b' * 32}.webp") is None

    def test_delete_is_idempotent(self, gcs):
        store, bucket = gcs
        store.put(KEY, b"abc", "image/webp")
        store.delete(KEY)
        store.delete(KEY)
        assert bucket.objects == {}

    def test_delete_user_removes_only_that_prefix(self, gcs):
        store, bucket = gcs
        for i in range(3):
            store.put(f"photos/{UID}/{i:032x}.webp", b"x", "image/webp")
        store.put(f"photos/{UID}2/{PID}.webp", b"x", "image/webp")           # a different user whose id starts the same
        store.put(f"photos/other/{PID}.webp", b"x", "image/webp")
        assert store.delete_user(UID) == 3
        assert set(bucket.objects) == {f"photos/other/{PID}.webp", f"photos/{UID}2/{PID}.webp"}

    def test_nothing_is_ever_made_public_or_signed(self, gcs):
        store, _ = gcs
        store.put(KEY, b"abc", "image/webp")                                  # would raise if it called make_public()
        assert not hasattr(_FakeBlob, "make_public") and not hasattr(_FakeBlob, "generate_signed_url")

    def test_the_bucket_setting_selects_the_backend(self, gcs, set_env):
        ps.set_store(None)
        set_env(GCS_BUCKET="closet-photos")
        assert isinstance(ps.get_store(), ps.GcsStore)
        ps.set_store(None)
        set_env(GCS_BUCKET="")
        store = ps.get_store()
        assert isinstance(store, ps.DiskStore) and store.root.name == "photo_store"      # NOT under uploads/

    def test_the_whole_flow_works_on_the_gcs_backend(self, client, alice, gcs, sql):
        store, bucket = gcs
        ps.set_store(store)
        body = upload(client, alice).json()
        assert set(bucket.objects) == {body["image_path"], f"photos/{alice.user_id}/{body['photo_id']}_t.jpg"}
        assert fetch(client, body["image_url"]).status_code == 200
        item = add(client, alice, body["image_path"]).json()["item_id"]
        client.delete(f"/wardrobe/item/{item}", headers=alice.headers)
        assert bucket.objects == {} and rows(sql) == []


class TestGcsStoreAgainstTheRealClientApi:
    """The fake above can't catch a typo in a method name; the real classes can."""

    def test_every_call_the_store_makes_exists_on_the_real_library(self):
        import inspect

        import google.cloud.storage as storage
        from google.api_core.exceptions import NotFound

        for name in ("upload_from_string", "download_as_bytes", "delete"):
            assert callable(getattr(storage.Blob, name)), name
        assert "cache_control" in dir(storage.Blob)
        assert callable(storage.Client.bucket) and callable(storage.Bucket.blob)
        assert "prefix" in inspect.signature(storage.Client.list_blobs).parameters
        assert issubclass(NotFound, Exception)
        # ...and it is only ever used through these, never to publish or sign:
        import services.photo_store as mod
        source = inspect.getsource(mod.GcsStore)
        assert "make_public" not in source and "generate_signed_url" not in source and "public_url" not in source


# ---------------------------------------------------------------------------
# Hardening from the security review
# ---------------------------------------------------------------------------

class TestHostileLinks:
    """GET /files is public: whatever arrives in the query string must end in 403, never a 500."""

    @pytest.mark.parametrize("e,s", [("²", "x"), ("٣٣", "x"), ("9999999999", "é"), ("9999999999", "\u0000"),
                                      ("1e10", "x"), (" 99999999999", "x"), ("+99999999999", "x"), ("9" * 400, "x")])
    def test_verify_link_never_raises(self, e, s):
        assert ps.verify_link(KEY, e, s) is False

    @pytest.mark.parametrize("query", ["e=%C2%B2&s=x", "e=9999999999&s=%C3%A9", "e=%D9%A3&s=x", "e=%00&s=%00", "e=9999999999&s=" + "A" * 5000])
    def test_the_endpoint_answers_403_not_500(self, client_no_raise, alice, query):
        key = upload(client_no_raise, alice).json()["image_path"]
        assert client_no_raise.get(f"/files/{key}?{query}").status_code == 403


class TestNothingPersonalSurvivesReEncoding:
    def test_a_jpeg_comment_is_dropped(self):
        buf = io.BytesIO()
        Image.new("RGB", (30, 30), (5, 6, 7)).save(buf, format="JPEG", comment=b"owner=Jane;home=12 Elm St")
        assert decode(buf.getvalue()).info.get("comment")                           # the input carries it
        out = decode(ps.prepare_photo(buf.getvalue()).full)
        assert "comment" not in out.info and b"Elm St" not in ps.prepare_photo(buf.getvalue()).full

    def test_png_text_chunks_and_icc_profiles_are_dropped(self):
        from PIL.PngImagePlugin import PngInfo

        meta = PngInfo()
        meta.add_text("Author", "Jane Doe")
        buf = io.BytesIO()
        Image.new("RGB", (30, 30), (5, 6, 7)).save(buf, format="PNG", pnginfo=meta)
        prepared = ps.prepare_photo(buf.getvalue())
        assert b"Jane" not in prepared.full and b"Jane" not in prepared.thumb

    def test_only_photo_formats_are_decoded(self):
        # EPS would go through Ghostscript if it were installed; nothing but photo formats is accepted.
        eps = b"%!PS-Adobe-3.0 EPSF-3.0\n%%BoundingBox: 0 0 10 10\nshowpage\n"
        with pytest.raises(ps.PhotoError):
            ps.prepare_photo(eps)

    def test_a_big_jpeg_is_decoded_at_reduced_size_but_stored_capped(self):
        buf = io.BytesIO()
        Image.new("RGB", (4000, 3000), (9, 9, 9)).save(buf, format="JPEG")
        p = ps.prepare_photo(buf.getvalue())
        assert max(decode(p.full).size) <= ps.MAX_SIDE and max(decode(p.full).size) >= ps.MAX_SIDE * 0.9


class TestOversizedImages:
    def test_a_pixel_bomb_warning_is_a_413_not_a_crash(self, client_no_raise, alice, monkeypatch):
        import warnings

        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            resp = upload(client_no_raise, alice, png(size=(60, 60)))                # 3,600 px: past 1,000, short of 2,000x2
        assert resp.status_code == 413 and "too high" in resp.json()["detail"]

    def test_a_real_bomb_error_is_also_a_413(self, client_no_raise, alice, monkeypatch):
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
        assert upload(client_no_raise, alice, png(size=(60, 60))).status_code == 413


class TestDecodeConcurrencyIsBounded:
    def test_at_most_two_photos_are_decoded_at_once(self, client, alice, monkeypatch):
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor

        import routers.photos as photos_router

        lock, state = threading.Lock(), {"now": 0, "max": 0}
        real = photos_router.prepare_photo

        def slow(body):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            time.sleep(0.15)
            try:
                return real(body)
            finally:
                with lock:
                    state["now"] -= 1

        monkeypatch.setattr(photos_router, "prepare_photo", slow)
        with ThreadPoolExecutor(6) as pool:
            codes = list(pool.map(lambda _: upload(client, alice, png(size=(8, 8))).status_code, range(6)))
        assert codes == [201] * 6 and 1 <= state["max"] <= 2


class TestStorageBudget:
    def test_the_byte_cap_stops_further_photos(self, client, alice, set_env, sql):
        first = upload(client, alice)
        assert first.status_code == 201
        set_env(MAX_PHOTO_BYTES_PER_USER=first.json()["bytes"] + 10)                 # room for the first, not a second
        again = upload(client, alice)
        assert again.status_code == 403 and again.json()["detail"]["code"] == "photos_full"
        assert len(rows(sql, alice.user_id)) == 1

    def test_a_single_photo_bigger_than_the_cap_is_refused(self, client, alice, set_env):
        set_env(MAX_PHOTO_BYTES_PER_USER=10)
        assert upload(client, alice).status_code == 403

    def test_the_cap_is_per_user(self, client, two_users, set_env):
        alice, bob = two_users
        first = upload(client, alice)
        set_env(MAX_PHOTO_BYTES_PER_USER=first.json()["bytes"] + 10)
        assert upload(client, alice).status_code == 403
        assert upload(client, bob).status_code == 201

    def test_a_default_closet_fits(self, clean_settings=None):
        from settings import get_settings

        assert get_settings().max_photo_bytes_per_user >= 500 * 100 * 1024         # 500 pieces at 100 KB


class TestOnePhotoOneItem:
    def test_the_database_itself_refuses_two_items_on_one_photo(self, client, alice, sql):
        from sqlalchemy.exc import IntegrityError

        key = upload(client, alice).json()["image_path"]
        add(client, alice, key)
        with pytest.raises(IntegrityError):
            sql("INSERT INTO wardrobe_items (item_id, user_id, image_path, created_at) VALUES ('dup', :u, :k, '2026-10-01T00:00:00+00:00')",
                u=alice.user_id, k=key)

    def test_legacy_paths_are_not_affected_by_the_index(self, client, alice):
        assert add(client, alice, "uploads/processed/same.jpg").status_code == 201
        assert add(client, alice, "uploads/processed/same.jpg").status_code == 201

    def test_a_photo_an_item_still_shows_is_never_deleted(self, client, alice, sql):
        from database import db_session

        body = upload(client, alice).json()
        add(client, alice, body["image_path"])
        with db_session() as db:
            ps.delete_photo(db, alice.user_id, body["image_path"])
        assert ps.get_store().get(body["image_path"]) and len(rows(sql)) == 1


class TestStudioShotChecksTheCapBeforeTheExpensiveWork:
    @pytest.mark.parametrize("path", ["/studio-shot", "/images/studio-shot"])
    def test_a_full_store_never_runs_the_model(self, client, alice, model, set_env, usage_count, path):
        set_env(MAX_PHOTOS_PER_USER=0)
        resp = shot(client, alice, "?store=1", path)
        assert resp.status_code == 403 and resp.json()["detail"]["code"] == "photos_full"
        assert model.calls == [] and usage_count(alice.user_id, "bgremove") == 0


# ---------------------------------------------------------------------------
# scripts/cleanup_photos.py
# ---------------------------------------------------------------------------

def _cleanup_module():
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "cleanup_photos.py"
    spec = importlib.util.spec_from_file_location("cleanup_photos", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _age(sql, photo_id, hours):
    from datetime import datetime, timedelta, timezone

    sql("UPDATE photos SET created_at = :t WHERE photo_id = :p", p=photo_id,
        t=(datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat())


class TestCleanupScript:
    def test_it_finds_only_what_nothing_uses(self, client, two_users, sql):
        from database import db_session

        alice, bob = two_users
        used = upload(client, alice).json()
        add(client, alice, used["image_path"])
        old_unused = upload(client, alice).json()
        young_unused = upload(client, alice).json()
        bobs_used = upload(client, bob).json()
        add(client, bob, bobs_used["image_path"])
        for p in (used, old_unused, bobs_used):
            _age(sql, p["photo_id"], 72)
        ghost_key = f"photos/ghost-user/{'e' * 32}.jpg"
        ps.get_store().put(ghost_key, b"x", "image/jpeg")
        sql("INSERT INTO photos (photo_id, user_id, key, thumb_key, size_bytes, created_at) "
            "VALUES (:p, 'ghost-user', :k, :k, 1, '2020-01-01T00:00:00+00:00')", p="e" * 32, k=ghost_key)

        with db_session() as db:
            found = _cleanup_module().find_leftovers(db, older_than_hours=24)
        assert [r["photo_id"] for r in found["never_attached"]] == [old_unused["photo_id"]]
        assert [r["photo_id"] for r in found["accounts_gone"]] == ["e" * 32]
        assert young_unused["photo_id"] not in str(found) and used["photo_id"] not in str(found)

    def test_applying_deletes_the_objects_and_records_of_exactly_those(self, client, alice, sql):
        from database import db_session

        keep = upload(client, alice).json()
        add(client, alice, keep["image_path"])
        junk = upload(client, alice).json()
        for p in (keep, junk):
            _age(sql, p["photo_id"], 72)
        mod = _cleanup_module()
        with db_session() as db:
            found = mod.find_leftovers(db, 24)
            assert mod.remove(db, found["never_attached"]) == 1
        store = ps.get_store()
        assert store.get(junk["image_path"]) is None and store.get(f"photos/{alice.user_id}/{junk['photo_id']}_t.jpg") is None
        assert store.get(keep["image_path"]) and [r["photo_id"] for r in rows(sql)] == [keep["photo_id"]]

    def test_a_storage_failure_keeps_the_record_for_the_next_run(self, client, alice, sql, monkeypatch):
        from database import db_session

        junk = upload(client, alice).json()
        _age(sql, junk["photo_id"], 72)
        mod = _cleanup_module()
        monkeypatch.setattr(ps.get_store(), "delete", lambda key: (_ for _ in ()).throw(OSError("down")))
        with db_session() as db:
            assert mod.remove(db, mod.find_leftovers(db, 24)["never_attached"]) == 0
        assert len(rows(sql)) == 1

    def test_the_age_threshold_is_respected(self, client, alice, sql):
        from database import db_session

        fresh = upload(client, alice).json()
        _age(sql, fresh["photo_id"], 2)
        with db_session() as db:
            mod = _cleanup_module()
            assert mod.find_leftovers(db, 24)["never_attached"] == []
            assert len(mod.find_leftovers(db, 1)["never_attached"]) == 1

    def test_without_apply_nothing_is_deleted(self, client, alice, sql, monkeypatch, capsys):
        junk = upload(client, alice).json()
        _age(sql, junk["photo_id"], 72)
        mod = _cleanup_module()
        monkeypatch.setattr("sys.argv", ["cleanup_photos.py"])
        assert mod.main() == 0
        assert "report only" in capsys.readouterr().out
        assert ps.get_store().get(junk["image_path"]) and len(rows(sql)) == 1
