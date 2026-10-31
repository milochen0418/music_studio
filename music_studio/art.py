"""A cover for a piece: its own waveform in the style's colours, as a PNG. No image library: a PNG is
a few lines of zlib."""

from __future__ import annotations

import struct
import zlib

import numpy as np

SIZE = 256
COLOURS = {
    "synthwave": ("#2b0a4d", "#ff3e9a"), "dnb": ("#04232e", "#29d3c8"), "chiptune": ("#10133a", "#7cf56b"), "rock": ("#2a0808", "#ff5a2c"),
    "house": ("#0c1740", "#4da3ff"), "techno": ("#101014", "#c8c8d6"), "orchestral": ("#2a1a06", "#f0b84a"), "lofi": ("#2c1b12", "#e7b98e"),
    "ambient": ("#0d2333", "#a8e0f0"), "tropical": ("#06332c", "#ffb347"), "desert": ("#3a1e08", "#f2c572"), "victory": ("#2e2204", "#ffe066"),
}
REMAKE = ("#17132e", "#b18cff")


def _rgb(colour: str) -> np.ndarray:
    return np.array([int(colour[k : k + 2], 16) for k in (1, 3, 5)], dtype=float)


def _png(pixels: np.ndarray) -> bytes:
    h, w, _ = pixels.shape
    rows = b"".join(b"\x00" + pixels[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def peaks(audio: np.ndarray, count: int) -> np.ndarray:
    """The loudest moment of each of ``count`` slices of the piece, 0 to 1."""
    mono = np.abs(audio).max(axis=1)
    cuts = np.linspace(0, mono.size, count + 1).astype(int)
    out = np.array([mono[a:b].max() if b > a else 0.0 for a, b in zip(cuts[:-1], cuts[1:])])
    return out / (out.max() or 1.0)


def cover(audio: np.ndarray, style: str) -> bytes:
    back, ink = (_rgb(c) for c in COLOURS.get(style, REMAKE))
    y = np.linspace(0, 1, SIZE)[:, None]
    x = np.linspace(0, 1, SIZE)[None, :]
    glow = np.exp(-(((x - 0.5) ** 2 + (y - 0.5) ** 2) / 0.12))
    image = back + (ink - back)[None, None, :] * (glow * 0.28)[:, :, None]
    bars = peaks(audio, 48)
    width = SIZE // 48
    for k, level in enumerate(bars):
        half = int(level * SIZE * 0.34) + 1
        left = k * width + (SIZE - 48 * width) // 2
        image[SIZE // 2 - half : SIZE // 2 + half, left : left + max(1, width - 2)] = ink
    return _png(np.clip(image, 0, 255).astype(np.uint8))


def wave_path(audio: np.ndarray, count: int = 120) -> str:
    """The piece's outline as an SVG path, 0 to ``count`` wide and -1 to 1 tall."""
    bars = peaks(audio, count)
    return "".join(f"M{k} {-v:.2f}V{v:.2f}" for k, v in enumerate(bars))
