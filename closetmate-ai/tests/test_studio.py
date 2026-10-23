"""services/studio.py — photo in, 4:5 transparent "studio shot" out (the rembg cutout is always stubbed)."""
from __future__ import annotations

import dataclasses
import io

import numpy as np
import pytest
from PIL import Image

import services.studio as studio
from conftest import make_photo
from services.studio import StudioShot, StudioShotError, make_studio_shot

CANVAS_W, CANVAS_H = 640, 800
MAX_W, MAX_H = int(CANVAS_W * 0.88), int(CANVAS_H * 0.88)        # 563 x 704: the 88% box

RED = (200, 30, 30)
BOX = (100, 100, 300, 400)                                       # a 200 x 300 subject


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def decode(data: bytes) -> Image.Image:
    img = Image.open(io.BytesIO(data))
    img.load()
    return img


def alpha_of(img: Image.Image) -> np.ndarray:
    return np.array(img.convert("RGBA"))[:, :, 3]


def subject_bbox(img: Image.Image, threshold: int = 24):
    """(x0, y0, x1, y1), x1/y1 exclusive, of the pixels with alpha > threshold."""
    ys, xs = np.where(alpha_of(img) > threshold)
    assert len(xs), "the studio shot is empty"
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def size_of(bbox):
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def shot_for(fake_cutout, boxes, *, size=(400, 500), colour=RED, background=(235, 235, 235)) -> StudioShot:
    """Run the real pipeline on a photo whose stubbed 'model' keeps exactly ``boxes``."""
    fake_cutout.boxes = list(boxes)
    photo = make_photo(size=size, background=background, subjects=[(box, colour) for box in boxes])
    return make_studio_shot(photo)


def render(fake_cutout, boxes, **kwargs):
    return decode(shot_for(fake_cutout, boxes, **kwargs).full)


def column_runs(img: Image.Image, threshold: int = 128) -> int:
    """How many separate horizontal runs of 'solid' columns the image has."""
    solid = (alpha_of(img) > threshold).any(axis=0).astype(int)
    return int(((solid[1:] == 1) & (solid[:-1] == 0)).sum() + solid[0])


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

class TestOutputContract:
    def test_full_is_a_640x800_rgba_webp(self, fake_cutout):
        shot = shot_for(fake_cutout, [BOX])
        img = decode(shot.full)
        assert img.format == "WEBP" and img.mode == "RGBA"
        assert img.size == (CANVAS_W, CANVAS_H)

    def test_thumb_is_a_320x400_rgba_webp(self, fake_cutout):
        img = decode(shot_for(fake_cutout, [BOX]).thumb)
        assert img.format == "WEBP" and img.mode == "RGBA"
        assert img.size == (320, 400)

    def test_reported_dimensions_are_those_of_the_full_image(self, fake_cutout):
        shot = shot_for(fake_cutout, [BOX])
        assert (shot.width, shot.height) == (CANVAS_W, CANVAS_H) == decode(shot.full).size

    def test_module_constants_describe_a_4_to_5_canvas(self):
        assert studio.CANVAS == (640, 800) and studio.THUMB == (320, 400)
        assert studio.CANVAS[0] / studio.CANVAS[1] == studio.THUMB[0] / studio.THUMB[1] == 0.8

    def test_result_is_an_immutable_dataclass(self, fake_cutout):
        shot = shot_for(fake_cutout, [BOX])
        assert isinstance(shot, StudioShot)
        with pytest.raises(dataclasses.FrozenInstanceError):
            shot.width = 1                                        # type: ignore[misc]

    @pytest.mark.parametrize("which", ["full", "thumb"])
    def test_background_corners_are_fully_transparent(self, fake_cutout, which):
        alpha = alpha_of(decode(getattr(shot_for(fake_cutout, [BOX]), which)))
        assert [int(alpha[0, 0]), int(alpha[0, -1]), int(alpha[-1, 0]), int(alpha[-1, -1])] == [0, 0, 0, 0]

    def test_everything_outside_the_item_is_transparent(self, fake_cutout):
        img = render(fake_cutout, [BOX])
        x0, y0, x1, y1 = subject_bbox(img)
        alpha = alpha_of(img).copy()
        alpha[max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] = 0          # blank the item (plus a 3px margin)
        assert int(alpha.max()) == 0

    def test_the_item_itself_is_opaque(self, fake_cutout):
        img = render(fake_cutout, [BOX])
        x0, y0, x1, y1 = subject_bbox(img)
        assert int(alpha_of(img)[(y0 + y1) // 2, (x0 + x1) // 2]) == 255

    def test_thumb_is_the_full_image_at_half_size(self, fake_cutout):
        shot = shot_for(fake_cutout, [BOX])
        full_w, full_h = size_of(subject_bbox(decode(shot.full)))
        thumb_w, thumb_h = size_of(subject_bbox(decode(shot.thumb)))
        assert abs(thumb_w - full_w / 2) <= 2 and abs(thumb_h - full_h / 2) <= 2

    def test_a_simple_subject_encodes_small(self, fake_cutout):
        shot = shot_for(fake_cutout, [BOX])
        assert 0 < len(shot.thumb) < len(shot.full) < 150 * 1024

    def test_output_is_deterministic(self, fake_cutout):
        photo = make_photo(subjects=[(BOX, RED)])
        fake_cutout.boxes = [BOX]
        first, second = make_studio_shot(photo), make_studio_shot(photo)
        assert first == second

    def test_the_cutout_is_called_exactly_once_with_the_photo(self, fake_cutout):
        shot_for(fake_cutout, [BOX], size=(400, 500))
        assert len(fake_cutout.calls) == 1
        assert fake_cutout.calls[0].size == (400, 500) and fake_cutout.calls[0].mode == "RGBA"


# ---------------------------------------------------------------------------
# Framing: centred, inside the 88% box, never over-enlarged
# ---------------------------------------------------------------------------

class TestFraming:
    @pytest.mark.parametrize("box", [
        (20, 100, 160, 300),          # hugging the left edge of the photo
        (240, 100, 380, 300),         # hugging the right edge
        (100, 20, 300, 120),          # near the top
        (130, 300, 270, 480),         # near the bottom
    ], ids=["left", "right", "top", "bottom"])
    def test_the_item_is_centred_horizontally_wherever_it_sat_in_the_photo(self, fake_cutout, box):
        x0, _, x1, _ = subject_bbox(render(fake_cutout, [box]))
        assert abs((x0 + x1) / 2 - CANVAS_W / 2) <= 3

    @pytest.mark.parametrize("size,box", [
        ((400, 500), (100, 100, 300, 400)),            # portrait garment
        ((600, 400), (100, 150, 500, 190)),            # wide and thin: 400 x 40
        ((300, 600), (130, 100, 170, 500)),            # tall and thin: 40 x 400
        ((500, 500), (50, 50, 450, 450)),              # big square
        ((1200, 1200), (100, 100, 1100, 1100)),        # larger than the canvas itself
    ], ids=["portrait", "wide-thin", "tall-thin", "square", "huge"])
    def test_the_item_fits_inside_the_88_percent_box(self, fake_cutout, size, box):
        w, h = size_of(subject_bbox(render(fake_cutout, [box], size=size)))
        assert w <= 0.88 * CANVAS_W and h <= 0.88 * CANVAS_H

    def test_wide_thin_subject_is_limited_by_width_and_keeps_its_proportions(self, fake_cutout):
        w, h = size_of(subject_bbox(render(fake_cutout, [(100, 150, 500, 190)], size=(600, 400))))
        assert w == MAX_W
        assert abs(w / h - 400 / 40) / (400 / 40) < 0.08               # 10:1 survives the resize

    def test_tall_thin_subject_is_limited_by_height_and_keeps_its_proportions(self, fake_cutout):
        w, h = size_of(subject_bbox(render(fake_cutout, [(130, 100, 170, 500)], size=(300, 600))))
        assert h == MAX_H
        assert abs(h / w - 400 / 40) / (400 / 40) < 0.08

    def test_a_mid_size_item_is_scaled_to_fill_the_limiting_axis(self, fake_cutout):
        w, h = size_of(subject_bbox(render(fake_cutout, [BOX])))       # 200 x 300 -> height-limited
        assert h == MAX_H and w < MAX_W

    @pytest.mark.parametrize("w,h", [(20, 30), (10, 10), (40, 20)])
    def test_a_small_crop_is_never_enlarged_more_than_3x(self, fake_cutout, w, h):
        box = (40, 40, 40 + w, 40 + h)
        rendered_w, rendered_h = size_of(subject_bbox(render(fake_cutout, [box], size=(100, 100))))
        # +2 px: the matte is softened by a pixel or two before the crop is measured.
        assert rendered_w <= 3 * w + 2 and rendered_h <= 3 * h + 2
        assert rendered_w >= 2.5 * w and rendered_h >= 2.5 * h        # ...and the 3x cap, not the canvas, binds

    def test_the_item_sits_slightly_above_the_vertical_centre(self, fake_cutout):
        _, y0, _, y1 = subject_bbox(render(fake_cutout, [(100, 150, 500, 190)], size=(600, 400)))
        top, bottom = y0, CANVAS_H - y1
        assert top < bottom
        assert top / (top + bottom) > 0.45                            # optically balanced, not pinned to the top

    def test_an_item_touching_every_edge_of_its_photo_still_gets_a_margin(self, fake_cutout):
        x0, y0, x1, y1 = subject_bbox(render(fake_cutout, [(0, 0, 120, 400)], size=(120, 400)))
        assert x0 >= 20 and CANVAS_W - x1 >= 20
        assert y0 >= 40 and CANVAS_H - y1 >= 40                          # at least 5% above and below


# ---------------------------------------------------------------------------
# Matte clean-up: specks go, a second real item stays
# ---------------------------------------------------------------------------

MAIN = (100, 100, 200, 250)                                          # 100 x 150 = 15,000 px


class TestSubjectSelection:
    def baseline(self, fake_cutout, boxes, **kwargs):
        return subject_bbox(render(fake_cutout, boxes, **kwargs))

    @pytest.mark.parametrize("speck", [
        (370, 20, 374, 24),           # 16 px, top right
        (10, 380, 12, 382),           # 4 px, bottom left
        (300, 300, 301, 301),         # a single pixel
        (350, 150, 357, 157),         # 49 px: just under the 50 px floor
    ])
    def test_tiny_specks_far_from_the_subject_are_removed(self, fake_cutout, speck):
        alone = self.baseline(fake_cutout, [MAIN], size=(400, 400))
        with_speck = self.baseline(fake_cutout, [MAIN, speck], size=(400, 400))
        assert with_speck == alone
        assert size_of(with_speck)[0] / size_of(with_speck)[1] == pytest.approx(100 / 150, abs=0.03)

    def test_several_specks_at_once_are_all_removed(self, fake_cutout):
        specks = [(5, 5, 9, 9), (380, 5, 384, 9), (5, 380, 9, 384), (380, 380, 384, 384)]
        assert self.baseline(fake_cutout, [MAIN, *specks], size=(400, 400)) == \
            self.baseline(fake_cutout, [MAIN], size=(400, 400))

    def test_a_second_item_of_similar_size_is_kept(self, fake_cutout):
        shoes = [(50, 100, 150, 160), (210, 100, 310, 160)]           # a pair: two 100 x 60 blobs
        img = render(fake_cutout, shoes, size=(400, 300))
        assert column_runs(img) == 2
        alone = size_of(subject_bbox(render(fake_cutout, [shoes[0]], size=(400, 300))))
        assert size_of(subject_bbox(img))[0] / size_of(subject_bbox(img))[1] > 1.5 * alone[0] / alone[1]

    def test_the_pair_is_framed_as_one_group_inside_the_box(self, fake_cutout):
        img = render(fake_cutout, [(50, 100, 150, 160), (210, 100, 310, 160)], size=(400, 300))
        x0, _, x1, _ = subject_bbox(img)
        assert x1 - x0 == MAX_W and abs((x0 + x1) / 2 - CANVAS_W / 2) <= 3

    @pytest.mark.parametrize("largest,blob_w,blob_h,kept", [
        ((20, 20, 120, 120), 20, 20, True),       # 400 px == 4% of 10,000: exactly at the floor => kept
        ((20, 20, 120, 120), 21, 19, False),      # 399 px: one under the floor => removed
        ((20, 20, 120, 120), 25, 20, True),       # 500 px
        ((20, 20, 120, 120), 15, 20, False),      # 300 px
    ])
    def test_a_blob_survives_only_from_4_percent_of_the_largest(self, fake_cutout, largest, blob_w, blob_h, kept):
        blob = (300, 300, 300 + blob_w, 300 + blob_h)
        alone = self.baseline(fake_cutout, [largest], size=(400, 400))
        both = self.baseline(fake_cutout, [largest, blob], size=(400, 400))
        assert (both != alone) is kept

    @pytest.mark.parametrize("blob_side,kept", [(8, True), (7, False), (6, False)])
    def test_the_minimum_floor_is_50_pixels_when_the_largest_item_is_small(self, fake_cutout, blob_side, kept):
        # 4% of a 20x20 item is 16 px, so the absolute 50 px floor applies: 8x8=64 is kept, 7x7=49 is not.
        largest = (10, 10, 30, 30)
        blob = (70, 70, 70 + blob_side, 70 + blob_side)
        alone = self.baseline(fake_cutout, [largest], size=(100, 100))
        both = self.baseline(fake_cutout, [largest, blob], size=(100, 100))
        assert (both != alone) is kept

    def test_faint_haze_inside_the_crop_is_wiped(self, fake_cutout):
        # An L-shaped garment leaves an empty corner inside its bounding box; the model's
        # alpha-10 haze there must come out fully transparent, not as a grey veil.
        fake_cutout.haze = 10
        boxes = [(100, 100, 160, 300), (100, 240, 300, 300)]
        img = render(fake_cutout, boxes)
        x0, y0, x1, y1 = subject_bbox(img)
        corner = alpha_of(img)[y0 + 5:y0 + (y1 - y0) // 3, x1 - (x1 - x0) // 3:x1 - 5]
        assert corner.size and int(corner.max()) == 0

    def test_haze_alone_is_not_an_item(self, fake_cutout):
        fake_cutout.haze = 11
        fake_cutout.boxes = []
        with pytest.raises(StudioShotError):
            make_studio_shot(make_photo())


# ---------------------------------------------------------------------------
# Colour fidelity
# ---------------------------------------------------------------------------

class TestColourIsPreserved:
    @pytest.mark.parametrize("colour", [
        (200, 30, 30), (30, 90, 200), (255, 255, 255), (20, 20, 20), (10, 120, 10),
        (250, 200, 20), (120, 118, 115), (128, 0, 128),
    ])
    def test_centre_pixel_matches_the_source_colour(self, fake_cutout, colour):
        img = render(fake_cutout, [BOX], colour=colour)
        x0, y0, x1, y1 = subject_bbox(img)
        r, g, b, a = img.getpixel(((x0 + x1) // 2, (y0 + y1) // 2))
        assert a == 255
        assert max(abs(r - colour[0]), abs(g - colour[1]), abs(b - colour[2])) <= 12

    def test_a_dull_photo_is_not_contrast_stretched(self, fake_cutout):
        # Colour IS the product: a muted grey stays muted (no auto-contrast / white balance).
        img = render(fake_cutout, [BOX], colour=(128, 128, 128), background=(150, 150, 150))
        x0, y0, x1, y1 = subject_bbox(img)
        r, g, b, _ = img.getpixel(((x0 + x1) // 2, (y0 + y1) // 2))
        assert all(abs(c - 128) <= 12 for c in (r, g, b))

    def test_the_background_colour_does_not_bleed_into_the_item(self, fake_cutout):
        img = render(fake_cutout, [BOX], colour=(30, 90, 200), background=(255, 255, 255))
        x0, y0, x1, y1 = subject_bbox(img)
        arr = np.array(img)[y0 + 20:y1 - 20, x0 + 20:x1 - 20]           # well inside the garment
        assert int(arr[:, :, 0].max()) <= 30 + 12                        # never a white-ish red channel


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------

class TestStudioShotErrors:
    def test_error_type_is_a_value_error(self):
        assert issubclass(StudioShotError, ValueError)

    def test_a_fully_transparent_cutout_has_nothing_to_show(self, fake_cutout):
        fake_cutout.boxes = []
        with pytest.raises(StudioShotError) as err:
            make_studio_shot(make_photo())
        assert str(err.value) == "We couldn't find the item in this photo. Try a plainer background."

    def test_a_subject_under_0_4_percent_of_the_photo_is_too_small(self, fake_cutout):
        fake_cutout.boxes = [(100, 100, 120, 120)]                       # 400 px of 160,000 = 0.25%
        with pytest.raises(StudioShotError) as err:
            make_studio_shot(make_photo(size=(400, 400)))
        assert str(err.value) == "The item is too small in this photo. Move closer and try again."

    def test_a_subject_of_1_percent_is_accepted(self, fake_cutout):
        shot = shot_for(fake_cutout, [(100, 100, 140, 140)], size=(400, 400))      # 1,600 of 160,000
        assert decode(shot.full).size == (CANVAS_W, CANVAS_H)

    @pytest.mark.parametrize("payload", [
        b"", b"not an image", b"%PDF-1.4 fake", b"<html><script>alert(1)</script></html>",
        bytes(range(256)) * 8, b"\x89PNG\r\n\x1a\n" + b"\x00" * 16,
    ], ids=["empty", "text", "pdf", "html", "binary", "png-magic-only"])
    def test_bytes_that_are_not_an_image_raise_with_a_message(self, payload, fake_cutout):
        with pytest.raises(StudioShotError) as err:
            make_studio_shot(payload)
        assert str(err.value).strip()
        assert fake_cutout.calls == []                                  # the model never saw it

    def test_a_truncated_image_is_reported_as_unreadable(self, fake_cutout):
        truncated = make_photo(size=(200, 200), subjects=[(BOX, RED)])[:80]      # valid header, no pixel data
        with pytest.raises(StudioShotError, match="readable image"):
            make_studio_shot(truncated)

    def test_the_decoder_error_is_chained_for_debugging(self):
        with pytest.raises(StudioShotError) as err:
            make_studio_shot(b"garbage")
        assert err.value.__cause__ is not None

    def test_a_decompression_bomb_is_an_unreadable_image(self, monkeypatch):
        monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 10)
        with pytest.raises(StudioShotError):
            make_studio_shot(make_photo(size=(100, 100)))

    def test_model_failures_are_not_disguised_as_bad_photos(self, fake_cutout):
        fake_cutout.error = RuntimeError("onnx runtime exploded")
        with pytest.raises(RuntimeError, match="exploded"):
            make_studio_shot(make_photo(subjects=[(BOX, RED)]))


# ---------------------------------------------------------------------------
# cutout_ok: did the background really come off?
# ---------------------------------------------------------------------------

class TestCutoutOk:
    def test_a_normal_subject_is_ok(self, fake_cutout):
        assert shot_for(fake_cutout, [BOX]).cutout_ok is True

    def test_a_big_but_legitimate_item_is_ok(self, fake_cutout):
        # A long dress can fill most of the frame: ~80% opaque is still a real cutout.
        assert shot_for(fake_cutout, [(10, 10, 190, 190)], size=(200, 200)).cutout_ok is True

    def test_a_model_that_kept_the_whole_photo_is_flagged(self, fake_cutout):
        fake_cutout.opaque = True
        shot = make_studio_shot(make_photo(size=(200, 200), subjects=[((50, 50, 150, 150), RED)]))
        assert shot.cutout_ok is False
        assert decode(shot.full).size == (CANVAS_W, CANVAS_H)            # still a usable image

    def test_more_than_92_percent_opaque_is_flagged(self, fake_cutout):
        assert shot_for(fake_cutout, [(2, 2, 198, 198)], size=(200, 200)).cutout_ok is False   # ~94% after the matte

    def test_a_cutout_without_any_alpha_channel_is_flagged(self, fake_cutout):
        fake_cutout.rgb_only = True
        assert make_studio_shot(make_photo(size=(200, 200), subjects=[((50, 50, 150, 150), RED)])).cutout_ok is False

    @pytest.mark.parametrize("opaque_pixels,ok", [(9199, True), (9200, False)])
    def test_the_threshold_is_exactly_92_percent_of_the_photo(self, opaque_pixels, ok):
        alpha = np.zeros((100, 100), dtype=np.uint8)
        alpha.flat[:opaque_pixels] = 255
        _, cutout_ok = studio._crop_to_subject(Image.fromarray(np.dstack([np.zeros((100, 100, 3), np.uint8), alpha]), "RGBA"))
        assert cutout_ok is ok


# ---------------------------------------------------------------------------
# EXIF orientation
# ---------------------------------------------------------------------------

class TestExifOrientation:
    LANDSCAPE = (200, 100)

    def test_without_an_orientation_tag_a_landscape_photo_stays_landscape(self, fake_cutout):
        shot = make_studio_shot(make_photo(size=self.LANDSCAPE, fmt="JPEG"))
        assert fake_cutout.calls[0].size == (200, 100)
        w, h = size_of(subject_bbox(decode(shot.full)))
        assert w > h

    @pytest.mark.parametrize("orientation", [6, 8])
    def test_a_rotated_photo_is_turned_upright_before_the_cutout(self, fake_cutout, orientation):
        shot = make_studio_shot(make_photo(size=self.LANDSCAPE, fmt="JPEG", exif_orientation=orientation))
        assert fake_cutout.calls[0].size == (100, 200)                  # the model sees the corrected photo
        w, h = size_of(subject_bbox(decode(shot.full)))
        assert h > w                                                     # output aspect follows the corrected orientation

    def test_a_180_degree_orientation_keeps_the_size(self, fake_cutout):
        make_studio_shot(make_photo(size=self.LANDSCAPE, fmt="JPEG", exif_orientation=3))
        assert fake_cutout.calls[0].size == (200, 100)

    @pytest.mark.parametrize("orientation,point", [(6, (16, 4)), (8, (3, 35))])
    def test_pixels_end_up_where_the_tag_says(self, fake_cutout, orientation, point):
        # A red patch in the stored top-left corner of a 40x20 photo (lossless PNG carrying the EXIF tag).
        photo = make_photo(size=(40, 20), background=(255, 255, 255), subjects=[((0, 0, 8, 8), (255, 0, 0))],
                           fmt="PNG", exif_orientation=orientation)
        make_studio_shot(photo)
        seen = fake_cutout.calls[0]
        assert seen.size == (20, 40)
        # EXIF 6 = rotate 90 CW (patch -> top-right); EXIF 8 = rotate 90 CCW (patch -> bottom-left).
        assert seen.getpixel(point)[:3] == (255, 0, 0)
        assert seen.getpixel((20 - 1 - point[0], 40 - 1 - point[1]))[:3] == (255, 255, 255)


# ---------------------------------------------------------------------------
# Input handling: size caps and formats
# ---------------------------------------------------------------------------

class TestInputHandling:
    def test_a_huge_photo_is_capped_to_1280_on_its_longest_side(self, fake_cutout):
        make_studio_shot(make_photo(size=(3000, 1500), subjects=[((1000, 500, 2000, 1000), RED)]))
        assert fake_cutout.calls[0].size == (1280, 640)

    def test_a_photo_of_exactly_1280_is_not_resized(self, fake_cutout):
        make_studio_shot(make_photo(size=(1280, 960), subjects=[((300, 300, 900, 700), RED)]))
        assert fake_cutout.calls[0].size == (1280, 960)

    def test_a_small_photo_is_not_enlarged_before_the_cutout(self, fake_cutout):
        make_studio_shot(make_photo(size=(100, 80), subjects=[((20, 20, 80, 60), RED)]))
        assert fake_cutout.calls[0].size == (100, 80)

    @pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP", "BMP", "GIF"])
    def test_common_photo_formats_are_accepted(self, fake_cutout, fmt):
        shot = make_studio_shot(make_photo(size=(120, 160), subjects=[((30, 30, 90, 130), RED)], fmt=fmt))
        assert decode(shot.full).size == (CANVAS_W, CANVAS_H)

    @pytest.mark.parametrize("mode", ["L", "P", "LA", "RGBA", "CMYK"])
    def test_unusual_colour_modes_are_converted(self, fake_cutout, mode):
        src = Image.new("RGB", (120, 160), (240, 240, 240))
        src.paste((200, 30, 30), (30, 30, 90, 130))
        buf = io.BytesIO()
        src.convert(mode).save(buf, format="TIFF" if mode == "CMYK" else "PNG")
        shot = make_studio_shot(buf.getvalue())
        assert decode(shot.full).mode == "RGBA"
        assert fake_cutout.calls[0].mode == "RGBA"


# ---------------------------------------------------------------------------
# Pipeline steps in isolation
# ---------------------------------------------------------------------------

def rgba(alpha: np.ndarray, colour=(10, 20, 30)) -> Image.Image:
    arr = np.zeros(alpha.shape + (4,), dtype=np.uint8)
    arr[:, :, :3] = colour
    arr[:, :, 3] = alpha
    return Image.fromarray(arr, "RGBA")


class TestCleanMatte:
    def test_alpha_below_12_is_zeroed_and_12_is_kept(self):
        # Uniform alpha: no solid component exists, so only the haze rule applies.
        assert int(alpha_of(studio._clean_matte(rgba(np.full((30, 30), 11, np.uint8)))).max()) == 0
        assert int(alpha_of(studio._clean_matte(rgba(np.full((30, 30), 12, np.uint8)))).min()) == 12

    def test_the_edge_is_eroded_by_a_pixel_and_softened(self):
        alpha = np.zeros((60, 60), np.uint8)
        alpha[20:40, 20:40] = 255
        out = alpha_of(studio._clean_matte(rgba(alpha)))
        assert out[30, 30] == 255                                # interior untouched
        assert out[30, 20] < 200                                 # the outermost ring of the mask is pulled in
        assert 0 < out[30, 21] < 255 or out[30, 22] == 255       # ...and the new edge is anti-aliased
        assert out[30, 5] == 0                                   # background stays empty

    def test_a_soft_rim_next_to_the_item_survives_but_distant_haze_does_not(self):
        alpha = np.zeros((90, 90), np.uint8)
        alpha[30:60, 30:60] = 255                                # solid garment
        alpha[26:64, 26:64] = np.where(alpha[26:64, 26:64] == 255, 255, 100)    # 4 px soft rim around it
        alpha[75:85, 75:85] = 100                                # a distant, non-solid smudge
        out = alpha_of(studio._clean_matte(rgba(alpha)))
        assert out[45, 28] > 0                                   # inside the rim
        assert out[80, 80] == 0                                  # smudge is not part of the main subject

    def test_a_distant_speck_is_dropped_and_the_main_item_kept(self):
        alpha = np.zeros((100, 100), np.uint8)
        alpha[30:80, 30:80] = 255
        alpha[2:5, 90:93] = 255                                  # 9 px speck
        out = alpha_of(studio._clean_matte(rgba(alpha)))
        assert out[55, 55] == 255 and int(out[0:10, 85:100].max()) == 0

    def test_colour_channels_are_untouched(self):
        alpha = np.zeros((40, 40), np.uint8)
        alpha[10:30, 10:30] = 255
        out = studio._clean_matte(rgba(alpha, colour=(7, 77, 177)))
        assert out.mode == "RGBA" and out.size == (40, 40)
        assert (np.array(out)[:, :, :3] == np.array([7, 77, 177], np.uint8)).all()

    def test_an_empty_matte_stays_empty(self):
        assert int(alpha_of(studio._clean_matte(rgba(np.zeros((20, 20), np.uint8)))).max()) == 0


class TestCropToSubject:
    def test_crop_hugs_the_pixels_above_alpha_24(self):
        alpha = np.zeros((50, 80), np.uint8)
        alpha[10:30, 20:50] = 200
        alpha[5, 5] = 24                                         # exactly 24: not part of the subject
        crop, _ = studio._crop_to_subject(rgba(alpha))
        assert crop.size == (30, 20)

    def test_nothing_above_alpha_24_is_the_no_item_error(self):
        with pytest.raises(StudioShotError, match="find the item"):
            studio._crop_to_subject(rgba(np.full((20, 20), 24, np.uint8)))

    def test_something_faint_but_nothing_solid_is_the_too_small_error(self):
        with pytest.raises(StudioShotError, match="too small"):
            studio._crop_to_subject(rgba(np.full((20, 20), 100, np.uint8)))

    @pytest.mark.parametrize("pixels,fails", [(39, True), (40, False)])
    def test_the_minimum_subject_is_0_4_percent_of_the_photo(self, pixels, fails):
        alpha = np.zeros((100, 100), np.uint8)
        alpha.flat[:pixels] = 255
        if fails:
            with pytest.raises(StudioShotError, match="too small"):
                studio._crop_to_subject(rgba(alpha))
        else:
            crop, ok = studio._crop_to_subject(rgba(alpha))
            assert crop.size == (40, 1) and ok is True


class TestFitToCanvas:
    def test_an_item_exactly_the_size_of_the_box_is_placed_without_scaling(self):
        canvas = studio._fit_to_canvas(Image.new("RGBA", (MAX_W, MAX_H), (1, 2, 3, 255)))
        assert canvas.size == (CANVAS_W, CANVAS_H) and canvas.mode == "RGBA"
        assert subject_bbox(canvas) == (38, 46, 38 + MAX_W, 46 + MAX_H)

    def test_a_one_pixel_item_is_enlarged_at_most_3x(self):
        canvas = studio._fit_to_canvas(Image.new("RGBA", (1, 1), (1, 2, 3, 255)))
        assert size_of(subject_bbox(canvas)) == (3, 3)

    def test_the_canvas_background_is_transparent(self):
        canvas = studio._fit_to_canvas(Image.new("RGBA", (50, 50), (1, 2, 3, 255)))
        assert canvas.getpixel((0, 0)) == (0, 0, 0, 0)


class TestEncode:
    def test_produces_webp_bytes_that_keep_the_alpha(self):
        data = studio._encode(Image.new("RGBA", (16, 16), (10, 20, 30, 0)), 80)
        assert data[:4] == b"RIFF" and data[8:12] == b"WEBP"
        assert decode(data).mode == "RGBA" and int(alpha_of(decode(data)).max()) == 0

    def test_higher_quality_is_a_bigger_file(self):
        noise = Image.fromarray(np.random.default_rng(0).integers(0, 255, (64, 64, 4), dtype=np.uint8), "RGBA")
        assert len(studio._encode(noise, 95)) > len(studio._encode(noise, 20))


class TestOpen:
    def test_returns_an_rgba_image(self):
        assert studio._open(make_photo(size=(30, 20), fmt="JPEG")).mode == "RGBA"

    def test_unreadable_bytes_raise_the_friendly_error(self):
        with pytest.raises(StudioShotError, match="isn't a readable image"):
            studio._open(b"nope")


class TestCutoutWrapper:
    def test_asks_the_configured_studio_model(self, monkeypatch):
        seen = {}

        def fake_model(image, model_name):
            seen["call"] = (image, model_name)
            return image

        monkeypatch.setattr(studio, "remove_background_with_model", fake_model)
        photo = Image.new("RGBA", (4, 4))
        assert studio._cutout(photo) is photo
        assert seen["call"] == (photo, "u2netp")                    # default STUDIO_RMBG_MODEL

    def test_model_name_follows_the_environment(self, monkeypatch, set_env):
        seen = []
        monkeypatch.setattr(studio, "remove_background_with_model", lambda image, name: seen.append(name) or image)
        set_env(STUDIO_RMBG_MODEL="isnet-general-use")
        studio._cutout(Image.new("RGBA", (2, 2)))
        assert seen == ["isnet-general-use"]


class TestHermeticGuard:
    def test_the_real_model_cannot_be_loaded_by_the_suite(self):
        """If a studio test forgets ``fake_cutout`` it fails fast instead of downloading ONNX weights."""
        with pytest.raises(RuntimeError, match="rembg model load attempted"):
            make_studio_shot(make_photo(subjects=[(BOX, RED)]))
