#!/usr/bin/env python3

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
DEFAULT_SOURCE = REPO / "src" / "services" / "web-client" / "public" / "logo.png"
DEFAULT_OUT = REPO / "desktop" / "icon-source.png"

PLATE = 1024
INNER_FRACTION = 0.78
INK_ALPHA_FLOOR = 8
CORNER_RADIUS = 200
SUPERSAMPLE = 4

PLATE_RGB = (255, 255, 255)

class PngError(RuntimeError):
    pass

class Image:

    __slots__ = ("width", "height", "data")

    def __init__(self, width: int, height: int, data: bytearray | None = None):
        self.width = width
        self.height = height
        self.data = data if data is not None else bytearray(width * height * 4)

    def pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        i = (y * self.width + x) * 4
        return (self.data[i], self.data[i + 1], self.data[i + 2], self.data[i + 3])

    def set(self, x: int, y: int, rgba: tuple[int, int, int, int]) -> None:
        i = (y * self.width + x) * 4
        self.data[i:i + 4] = bytes(rgba)

def _unfilter(raw: bytes, width: int, height: int, bpp: int) -> list[bytearray]:
    stride = width * bpp
    expected = (stride + 1) * height
    if len(raw) < expected:
        raise PngError(f"truncated image data: {len(raw)} bytes, expected {expected}")

    rows: list[bytearray] = []
    prev = bytearray(stride)
    pos = 0
    for y in range(height):
        ftype = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride

        if ftype == 0:
            pass
        elif ftype == 1:
            for x in range(bpp, stride):
                line[x] = (line[x] + line[x - bpp]) & 0xFF
        elif ftype == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 0xFF
        elif ftype == 3:
            for x in range(stride):
                left = line[x - bpp] if x >= bpp else 0
                line[x] = (line[x] + ((left + prev[x]) >> 1)) & 0xFF
        elif ftype == 4:
            for x in range(stride):
                a = line[x - bpp] if x >= bpp else 0
                b = prev[x]
                c = prev[x - bpp] if x >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pred) & 0xFF
        else:
            raise PngError(f"unknown scanline filter {ftype} on row {y}")

        rows.append(line)
        prev = line
    return rows

def read_png(path: Path) -> Image:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PngError(f"{path} is not a PNG (its extension may be lying)")

    width = height = 0
    idat = bytearray()
    colour_type = bit_depth = 0
    pos = 8
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bit_depth, colour_type, comp, filt, interlace = \
                struct.unpack(">IIBBBBB", body)
            if bit_depth != 8:
                raise PngError(f"{path}: bit depth {bit_depth}, only 8 is supported")
            if colour_type not in (2, 6):
                raise PngError(f"{path}: colour type {colour_type}, "
                               "only 2 (RGB) and 6 (RGBA) are supported")
            if interlace:
                raise PngError(f"{path}: interlaced PNGs are not supported")
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos += 12 + length

    if not width or not height:
        raise PngError(f"{path}: no IHDR chunk")
    if not idat:
        raise PngError(f"{path}: no image data")

    bpp = 4 if colour_type == 6 else 3
    rows = _unfilter(zlib.decompress(bytes(idat)), width, height, bpp)

    img = Image(width, height)
    for y, row in enumerate(rows):
        base = y * width * 4
        if bpp == 4:
            img.data[base:base + width * 4] = row
        else:
            for x in range(width):
                r, g, b = row[x * 3:x * 3 + 3]
                i = base + x * 4
                img.data[i:i + 4] = bytes((r, g, b, 255))
    return img

def write_png(img: Image, path: Path) -> None:
    raw = bytearray()
    stride = img.width * 4
    for y in range(img.height):
        raw.append(0)
        raw += img.data[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", img.width, img.height, 8, 6, 0, 0, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )

def ink_bbox(img: Image) -> tuple[int, int, int, int]:
    left, top, right, bottom = img.width, img.height, -1, -1
    for y in range(img.height):
        base = y * img.width * 4
        for x in range(img.width):
            if img.data[base + x * 4 + 3] > INK_ALPHA_FLOOR:
                if x < left:
                    left = x
                if x > right:
                    right = x
                if y < top:
                    top = y
                if y > bottom:
                    bottom = y
    if right < 0:
        raise PngError("the source image is entirely transparent")
    return (left, top, right, bottom)

def crop(img: Image, box: tuple[int, int, int, int]) -> Image:
    left, top, right, bottom = box
    out = Image(right - left + 1, bottom - top + 1)
    for y in range(out.height):
        src = ((top + y) * img.width + left) * 4
        dst = y * out.width * 4
        out.data[dst:dst + out.width * 4] = img.data[src:src + out.width * 4]
    return out

def upscale_nearest(img: Image, factor: int) -> Image:
    if factor < 1:
        raise ValueError("factor must be >= 1")
    out = Image(img.width * factor, img.height * factor)
    for y in range(img.height):
        row = img.data[y * img.width * 4:(y + 1) * img.width * 4]
        wide = bytearray()
        for x in range(img.width):
            wide += row[x * 4:x * 4 + 4] * factor
        for rep in range(factor):
            base = ((y * factor) + rep) * out.width * 4
            out.data[base:base + len(wide)] = wide
    return out

def _corner_coverage(size: int, radius: int) -> list[list[float]]:
    step = 1.0 / SUPERSAMPLE
    offset = step / 2.0
    grid: list[list[float]] = []
    for py in range(radius):
        row: list[float] = []
        for px in range(radius):
            hits = 0
            for sy in range(SUPERSAMPLE):
                dy = radius - (py + offset + sy * step)
                for sx in range(SUPERSAMPLE):
                    dx = radius - (px + offset + sx * step)
                    if dx <= 0 or dy <= 0 or (dx * dx + dy * dy) <= radius * radius:
                        hits += 1
            row.append(hits / float(SUPERSAMPLE * SUPERSAMPLE))
        grid.append(row)
    return grid

def rounded_plate(size: int, radius: int, rgb: tuple[int, int, int]) -> Image:
    plate = Image(size, size)
    r, g, b = rgb
    opaque = bytes((r, g, b, 255))
    for y in range(size):
        base = y * size * 4
        plate.data[base:base + size * 4] = opaque * size

    corner = _corner_coverage(size, radius)
    for py in range(radius):
        for px in range(radius):
            cov = corner[py][px]
            if cov >= 1.0:
                continue
            alpha = int(round(cov * 255))
            for (x, y) in (
                (px, py),
                (size - 1 - px, py),
                (px, size - 1 - py),
                (size - 1 - px, size - 1 - py),
            ):
                plate.set(x, y, (r, g, b, alpha))
    return plate

def composite(plate: Image, mark: Image) -> Image:
    if mark.width > plate.width or mark.height > plate.height:
        raise ValueError("mark is larger than the plate")
    ox = (plate.width - mark.width) // 2
    oy = (plate.height - mark.height) // 2

    for y in range(mark.height):
        for x in range(mark.width):
            sr, sg, sb, sa = mark.pixel(x, y)
            if sa == 0:
                continue
            if sa == 255:
                plate.set(ox + x, oy + y, (sr, sg, sb, 255))
                continue
            dr, dg, db, da = plate.pixel(ox + x, oy + y)
            a = sa / 255.0
            out_a = sa + int(round(da * (1.0 - a)))
            if out_a == 0:
                plate.set(ox + x, oy + y, (0, 0, 0, 0))
                continue
            def mix(s: int, d: int) -> int:
                num = s * sa + d * da * (1.0 - a)
                return max(0, min(255, int(round(num / out_a))))
            plate.set(ox + x, oy + y,
                      (mix(sr, dr), mix(sg, dg), mix(sb, db), min(255, out_a)))
    return plate

def build(source: Path, out: Path) -> dict:
    mark = read_png(source)
    box = ink_bbox(mark)
    inked = crop(mark, box)

    inner = int(PLATE * INNER_FRACTION)
    factor = inner // max(inked.width, inked.height)
    if factor < 1:
        raise PngError(
            f"the mark's ink is {inked.width}x{inked.height}, larger than the "
            f"{inner}px inner box; it would have to be shrunk, which this tool "
            "deliberately does not do (it would blur a hard-edged glyph)."
        )

    scaled = upscale_nearest(inked, factor)
    image = composite(rounded_plate(PLATE, CORNER_RADIUS, PLATE_RGB), scaled)
    write_png(image, out)
    return {
        "ink_box": box,
        "ink_size": (inked.width, inked.height),
        "factor": factor,
        "scaled": (scaled.width, scaled.height),
        "margin_x": (PLATE - scaled.width) // 2,
        "margin_y": (PLATE - scaled.height) // 2,
    }

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--source", default=str(DEFAULT_SOURCE),
                    help="the mark to composite (default: the web client's logo.png)")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="where to write the 1024x1024 master")
    args = ap.parse_args(argv)

    source = Path(args.source).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    try:
        info = build(source, out)
    except (PngError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    left, top, right, bottom = info["ink_box"]
    print(f"  source : {source}")
    print(f"  ink    : {info['ink_size'][0]}x{info['ink_size'][1]} "
          f"at ({left},{top})-({right},{bottom})")
    print(f"  mark   : x{info['factor']} nearest -> "
          f"{info['scaled'][0]}x{info['scaled'][1]}, centred with "
          f"{info['margin_x']}px / {info['margin_y']}px margins")
    print(f"  plate  : {PLATE}x{PLATE}, {CORNER_RADIUS}px radius, "
          f"opaque rgb{PLATE_RGB}")
    print(f"  master : {out}  ({out.stat().st_size / 1024:.0f} KB)")
    print()
    print("  Next, regenerate the icon set (needs Node, not Rust):")
    print("    npx @tauri-apps/cli icon desktop/icon-source.png "
          "-o desktop/src-tauri/icons")
    return 0

if __name__ == "__main__":
    sys.exit(main())
