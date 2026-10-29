"""Example WAVs. The fade and the peak normalize are only for the file.

The engine itself has no envelope and no output trim beyond out_gain.
"""

from __future__ import annotations

import os
import struct
import wave

from law import SR


def render_seconds(voice, fn, waves, seconds=1.0):
    n = int(seconds * SR)
    out = []
    first = True
    while len(out) < n:
        if not first:
            voice.note_on = 0
        first = False
        out.extend(fn(voice, waves))
    return out[:n]


def write_wav(path, samples, sr=SR):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    peak = max((abs(s) for s in samples), default=1.0) or 1.0
    scale = 0.89 / peak
    fade_in = int(0.008 * sr)
    fade_out = int(0.04 * sr)
    n = len(samples)
    frames = bytearray()
    for i, s in enumerate(samples):
        g = 1.0
        if i < fade_in:
            g = i / fade_in
        tail = n - 1 - i
        if tail < fade_out:
            g = min(g, tail / fade_out)
        v = s * scale * g
        if v > 1.0:
            v = 1.0
        elif v < -1.0:
            v = -1.0
        frames += struct.pack('<h', int(v * 32767.0))
    with wave.open(path, 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(frames)
    return path
