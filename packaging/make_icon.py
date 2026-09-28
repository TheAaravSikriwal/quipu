"""Draws packaging/quipu.ico: a quipu -- a primary cord with knotted
pendant cords -- in QUIPU's own ink on its own black. No image library:
the pixels are drawn here, written as PNG, and packed into an .ico.

  .venv/Scripts/python.exe packaging/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

BG = (18, 18, 20)
INK = (242, 242, 240)
GOLD = (199, 154, 82)
S = 256


def draw() -> list:
    px = [[None] * S for _ in range(S)]
    r = 44  # corner radius

    def inside_rounded(x, y):
        cx = min(max(x, r), S - 1 - r)
        cy = min(max(y, r), S - 1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    for y in range(S):
        for x in range(S):
            if inside_rounded(x, y):
                px[y][x] = BG

    def rect(x0, y0, x1, y1, c):
        for y in range(max(0, y0), min(S, y1)):
            for x in range(max(0, x0), min(S, x1)):
                if px[y][x] is not None:
                    px[y][x] = c

    def disc(cx, cy, rad, c):
        for y in range(cy - rad, cy + rad + 1):
            for x in range(cx - rad, cx + rad + 1):
                if 0 <= x < S and 0 <= y < S and (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad and px[y][x] is not None:
                    px[y][x] = c

    rect(40, 62, 216, 74, INK)                        # the primary cord
    cords = [(62, 176, [104, 140]), (98, 204, [118, 160, 190]), (134, 150, [110]),
             (170, 196, [96, 132, 176]), (206, 164, [124])]
    for i, (x, bottom, knots) in enumerate(cords):
        rect(x - 4, 70, x + 4, bottom, INK)             # a pendant cord
        for j, k in enumerate(knots):
            disc(x, k, 11, GOLD if (i == 1 and j == 1) else INK)
    return px


def png(px, size: int) -> bytes:
    step = S / size
    rows = []
    for y in range(size):
        row = bytearray([0])
        for x in range(size):
            # Box-average the source block, so small sizes stay legible.
            y0, y1 = int(y * step), max(int((y + 1) * step), int(y * step) + 1)
            x0, x1 = int(x * step), max(int((x + 1) * step), int(x * step) + 1)
            acc, n, a = [0, 0, 0], 0, 0
            for yy in range(y0, y1):
                for xx in range(x0, x1):
                    c = px[yy][xx]
                    n += 1
                    if c is not None:
                        a += 1
                        acc = [acc[0] + c[0], acc[1] + c[1], acc[2] + c[2]]
            if a:
                row += bytes([acc[0] // a, acc[1] // a, acc[2] // a, round(255 * a / n)])
            else:
                row += bytes([0, 0, 0, 0])
        rows.append(bytes(row))
    raw = zlib.compress(b"".join(rows), 9)

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def ico(images: list) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs, offset = b"", b"", 6 + 16 * len(images)
    for size, data in images:
        entries += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    return head + entries + blobs


if __name__ == "__main__":
    px = draw()
    out = Path(__file__).resolve().parent / "quipu.ico"
    out.write_bytes(ico([(s, png(px, s)) for s in (256, 64, 48, 32, 16)]))
    print(out, out.stat().st_size, "bytes")
