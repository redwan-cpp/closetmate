#!/usr/bin/env python
"""
Eyeball studio-shot quality on YOUR photos.

    venv\\Scripts\\python.exe scripts\\studio_contact_sheet.py C:\\path\\to\\phone\\photos [out.png] [model]

Runs every .jpg/.jpeg/.png/.webp in the folder through the same pipeline the app uses
(services.studio.make_studio_shot) and writes one contact sheet: the original on the left, the
studio shot (on the pastel tile the closet shows) on the right, with the verdict underneath.
Nothing is uploaded and nothing in the folder is modified.

`model` defaults to STUDIO_RMBG_MODEL (u2netp). Try `isnet-general-use` or `u2net` to compare:
a bigger model usually cuts cleaner but is ~170 MB and slower on a cold Cloud Run instance.
"""
from __future__ import annotations

import io
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

CELL_W, CELL_H = 240, 300
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help"}:
        print(__doc__)
        return 2
    folder = pathlib.Path(argv[0])
    if not folder.is_dir():
        print(f"not a folder: {folder}")
        return 2
    out = pathlib.Path(argv[1]) if len(argv) > 1 else folder / "studio_contact_sheet.png"
    if len(argv) > 2:
        os.environ["STUDIO_RMBG_MODEL"] = argv[2]

    # Dev defaults so importing the app's modules doesn't need a configured environment.
    os.environ.setdefault("ENV", "dev")
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{(pathlib.Path(os.environ.get('TEMP', '.')) / 'studio_sheet.db').as_posix()}")

    from PIL import Image, ImageDraw, ImageOps

    from services import studio
    from settings import get_settings

    photos = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTENSIONS and p != out)
    if not photos:
        print(f"no photos (jpg/png/webp) in {folder}")
        return 2

    print(f"model: {get_settings().studio_model}  photos: {len(photos)}")
    sheet = Image.new("RGB", (CELL_W * 2, (CELL_H + 22) * len(photos)), "#F3EEFA")
    draw = ImageDraw.Draw(sheet)
    suspect = 0
    for row, path in enumerate(photos):
        top = row * (CELL_H + 22)
        original = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
        original.thumbnail((CELL_W, CELL_H))
        sheet.paste(original, ((CELL_W - original.width) // 2, top))
        started = time.time()
        try:
            shot = studio.make_studio_shot(path.read_bytes())
            tile = Image.new("RGBA", (CELL_W, CELL_H), "#F3EEFA")
            tile.alpha_composite(Image.open(io.BytesIO(shot.full)).convert("RGBA").resize((CELL_W, CELL_H)))
            sheet.paste(tile.convert("RGB"), (CELL_W, top))
            verdict = "ok" if shot.cutout_ok else "SUSPECT (kept the whole photo)"
            suspect += 0 if shot.cutout_ok else 1
        except studio.StudioShotError as exc:
            verdict = f"refused: {exc}"
            suspect += 1
        label = f"{path.name[:28]}  {verdict}  {time.time() - started:.1f}s"
        draw.text((6, top + CELL_H + 4), label, fill="#16141A")
        print(label)

    sheet.save(out)
    print(f"\nsaved {out}   ({suspect} of {len(photos)} need a look)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
