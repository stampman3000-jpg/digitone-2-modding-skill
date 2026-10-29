"""Band-limited single-cycle waveforms.

The cycles in the repo are Fourier partial sums written here. Nothing is
taken from an Elektron file. A build may replace them with a table the user
generated on their own machine (see load_waves). Those files are gitignored
and must not be committed.

Kernel layout (fixed, so the SHARC loop can stay simple):

    word 0..63     2^(n/12) for n = 0..63
    word 64..67    just ratios 6/5, 5/4, 4/3, 3/2
    word 68..131   2^(-n/12) for n = 0..63
    word 132..     waveforms

Each waveform is MIPS cycles of N+1 float32 samples. The extra sample
repeats sample 0 so the interpolator can read index and index+1 without
a wrap branch. Every mip is the same length; only the harmonic count
changes. The oscillator picks a mip from the phase increment so the top
harmonic stays under Nyquist.

Env:  SWAVE_WAVE_TABLE=/path/to/file.swave.json
      SWAVE_WAVE_TABLE=/path/to/file.swave.f32
CLI:  --wave-table PATH   (render_wav.py and `python3 tables.py`)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import struct
import sys

from law import JUST_RATIO, SEMI_DOWN, SEMI_RATIO, WAVE_WORD, f32

N = 128
MIPS = 6
# Highest harmonic kept in each mip. Playback of mip i is safe while
# increment * HARM[i] < 0.5 (the partial’s top sine stays below Nyquist).
HARM = (64, 32, 16, 8, 4, 1)
STRIDE = N + 1                       # samples per mip, including the guard

# Duties the pulse bank actually stores. PW snaps to the nearest one once
# per audio block. 0.5 is the square.
PULSE_DUTIES = (1.0 / 32.0, 0.125, 0.25, 0.375, 0.5, 0.625, 0.75, 0.875, 31.0 / 32.0)

SAW, SINE, SQUARE, PULSE = 0, 1, 2, 3
_SHAPES = 3                          # saw, sine, square, then the pulse bank


def _sigma(k: int, H: int) -> float:
    """Lanczos sigma. Softens the Gibbs ring on a truncated series."""
    if k <= 0 or H <= 0:
        return 1.0
    x = math.pi * k / (H + 1.0)
    return math.sin(x) / x


def _cycle(samples):
    """Quantize to float32 and append the guard copy of sample 0."""
    out = [f32(s) for s in samples]
    if len(out) != N:
        raise ValueError(f'cycle length {len(out)} != {N}')
    out.append(out[0])
    return out


def fourier_saw(H: int):
    """Rising saw, 0 at the start of the jump, no DC.

    saw(t) = -(2/π) Σ_{k=1..H} σ_k sin(2π k t) / k
    which is the series for 2t−1 on [0, 1).
    """
    ys = []
    for i in range(N):
        t = i / N
        s = 0.0
        for k in range(1, H + 1):
            s += _sigma(k, H) * math.sin(2.0 * math.pi * k * t) / k
        ys.append(-2.0 / math.pi * s)
    return _cycle(ys)


def fourier_sine(H: int):
    """One sine. Extra harmonics are already zero, so every mip matches."""
    del H
    return _cycle([math.sin(2.0 * math.pi * i / N) for i in range(N)])


def fourier_pulse(duty: float, H: int):
    """Bipolar pulse, +1 for `duty` of the cycle, −1 after that.

    Coefficients (duty = d):
        a0 = 2d − 1
        a_k = (2/(π k)) sin(2π k d) σ_k
        b_k = (2/(π k)) (1 − cos(2π k d)) σ_k
    At d = 1/2 this is the square series (4/π)(sin t + sin 3t / 3 + …).
    """
    d = float(duty)
    dc = 2.0 * d - 1.0
    ys = []
    for i in range(N):
        t = i / N
        s = dc
        for k in range(1, H + 1):
            sig = _sigma(k, H)
            ang = 2.0 * math.pi * k * t
            ak = (2.0 / (math.pi * k)) * math.sin(2.0 * math.pi * k * d) * sig
            bk = (2.0 / (math.pi * k)) * (1.0 - math.cos(2.0 * math.pi * k * d)) * sig
            s += ak * math.cos(ang) + bk * math.sin(ang)
        ys.append(s)
    return _cycle(ys)


def _dft_mips(samples):
    """Turn one arbitrary cycle into our mip stack.

    Bins above each mip’s harmonic limit are dropped, then the cycle is
    resynthesized at length N. This is how a user-supplied single cycle
    becomes something the oscillator can play without aliasing.
    """
    L = len(samples)
    if L < 2:
        raise ValueError('a cycle needs at least 2 samples')
    dc = sum(samples) / L
    # bins[k] = (cos coeff, sin coeff) of the real DFT, k = 1..max H
    max_h = min(HARM[0], L // 2)
    bins = []
    for k in range(1, max_h + 1):
        ar = ai = 0.0
        for n, v in enumerate(samples):
            ang = 2.0 * math.pi * k * n / L
            ar += v * math.cos(ang)
            ai += -v * math.sin(ang)          # e^{-j ω n}
        bins.append((ar / L, ai / L))
    mips = []
    for H in HARM:
        h = min(H, max_h)
        ys = []
        for i in range(N):
            s = dc
            for k in range(1, h + 1):
                ar, ai = bins[k - 1]
                ang = 2.0 * math.pi * k * i / N
                # 2 Re{(ar + j ai) e^{j ω i}}
                s += 2.0 * (ar * math.cos(ang) - ai * math.sin(ang))
            ys.append(s)
        mips.append(_cycle(ys))
    return mips


def _direct_mips(kind: str, duty: float | None = None):
    out = []
    for H in HARM:
        if kind == 'saw':
            out.append(fourier_saw(H))
        elif kind == 'sine':
            out.append(fourier_sine(H))
        elif kind == 'square':
            out.append(fourier_pulse(0.5, H))
        elif kind == 'pulse':
            out.append(fourier_pulse(duty, H))
        else:
            raise ValueError(kind)
    return out


class WaveSet:
    """Float32 cycles the oscillator actually reads."""

    def __init__(self, saw, sine, square, pulse, duties=PULSE_DUTIES, source='default'):
        self.saw = saw
        self.sine = sine
        self.square = square
        self.pulse = pulse
        self.duties = tuple(duties)
        self.source = source
        self._check()

    def _check(self):
        for name, mips in (('saw', self.saw), ('sine', self.sine), ('square', self.square)):
            if len(mips) != MIPS:
                raise ValueError(f'{name}: expected {MIPS} mips, got {len(mips)}')
            for m in mips:
                if len(m) != STRIDE:
                    raise ValueError(f'{name}: mip length {len(m)} != {STRIDE}')
                if any(s != s or abs(s) > 1.0e4 for s in m):
                    raise ValueError(f'{name}: non-finite or huge sample')
        if len(self.pulse) != len(self.duties):
            raise ValueError('pulse bank does not match its duty list')
        for mips in self.pulse:
            if len(mips) != MIPS or any(len(m) != STRIDE for m in mips):
                raise ValueError('bad pulse mip')

    def mip_index(self, inc: float) -> int:
        for i, H in enumerate(HARM):
            if inc * H < 0.5:
                return i
        return MIPS - 1

    def nearest_pulse(self, duty: float) -> int:
        """Same staircase the DSP bakes in: step up at each midpoint, ties go up."""
        idx = 0
        for i in range(len(self.duties) - 1):
            mid = 0.5 * (self.duties[i] + self.duties[i + 1])
            if duty >= mid:
                idx = i + 1
        return idx

    def shape_mips(self, shape: int, pulse_index: int = 0):
        if shape == SAW:
            return self.saw
        if shape == SINE:
            return self.sine
        if shape == SQUARE:
            return self.square
        return self.pulse[pulse_index]

    def flat_words(self):
        """The DSP data block: tuning ratios, then cycles, as Python floats."""
        words = [0.0] * WAVE_WORD
        for i, r in enumerate(SEMI_RATIO):
            words[i] = r
        for i, raw in enumerate((124, 125, 126, 127)):
            words[64 + i] = JUST_RATIO[raw]
        for i, r in enumerate(SEMI_DOWN):
            words[68 + i] = r
        for mips in (self.saw, self.sine, self.square):
            for mip in mips:
                words.extend(mip)
        for bank in self.pulse:
            for mip in bank:
                words.extend(mip)
        return words

    def shape_word(self, shape: int, pulse_index: int = 0) -> int:
        """Word offset of mip 0 for this shape inside flat_words()."""
        base = WAVE_WORD
        if shape == SAW:
            return base
        base += MIPS * STRIDE
        if shape == SINE:
            return base
        base += MIPS * STRIDE
        if shape == SQUARE:
            return base
        base += MIPS * STRIDE
        return base + pulse_index * MIPS * STRIDE


def default_waves() -> WaveSet:
    return WaveSet(
        _direct_mips('saw'),
        _direct_mips('sine'),
        _direct_mips('square'),
        [_direct_mips('pulse', d) for d in PULSE_DUTIES],
        source='default-fourier',
    )


def _as_mip_stack(value, label: str):
    """Accept either one cycle (any length) or a finished mip stack."""
    if not isinstance(value, list) or not value:
        raise ValueError(f'{label}: expected a list')
    if isinstance(value[0], list):
        if len(value) != MIPS:
            raise ValueError(f'{label}: a mip stack needs {MIPS} cycles')
        out = []
        for mip in value:
            if len(mip) == STRIDE:
                cyc = [f32(x) for x in mip]
            elif len(mip) == N:
                cyc = _cycle(mip)
            else:
                raise ValueError(f'{label}: mip length {len(mip)} is not {N} or {STRIDE}')
            out.append(cyc)
        return out
    # one cycle
    samples = [float(x) for x in value]
    return _dft_mips(samples)


def load_json(path: str) -> WaveSet:
    with open(path, 'r', encoding='utf-8') as f:
        doc = json.load(f)
    if int(doc.get('version', 0)) != 1:
        raise ValueError('wave table JSON version must be 1')
    waves = doc.get('waves') or doc.get('waveforms')
    if not isinstance(waves, dict):
        raise ValueError('JSON needs a "waves" object')
    for key in ('saw', 'sine', 'square'):
        if key not in waves:
            raise ValueError(f'JSON waves.{key} is required')
    pulse = waves.get('pulse')
    if not isinstance(pulse, dict) or 'duties' not in pulse:
        raise ValueError('JSON waves.pulse.duties and waves.pulse.cycles are required')
    duties = [float(d) for d in pulse['duties']]
    cycles = pulse.get('cycles') or pulse.get('waves')
    if len(cycles) != len(duties):
        raise ValueError('pulse cycles and duties differ in length')
    return WaveSet(
        _as_mip_stack(waves['saw'], 'saw'),
        _as_mip_stack(waves['sine'], 'sine'),
        _as_mip_stack(waves['square'], 'square'),
        [_as_mip_stack(c, f'pulse[{i}]') for i, c in enumerate(cycles)],
        duties=duties,
        source=path,
    )


def load_f32(path: str) -> WaveSet:
    """Raw little-endian image. See the module docstring and INTERFACE_swave.md."""
    data = open(path, 'rb').read()
    magic, version, length, n_mips, n_pulse, flags = struct.unpack_from('<4sIIIII', data, 0)
    if magic != b'SWV1' or version != 1:
        raise ValueError('not an SWV1 wave table')
    if length != N or n_mips != MIPS:
        raise ValueError(f'raw table is {length}x{n_mips}; this build wants {N}x{MIPS}')
    off = 24
    harms = struct.unpack_from('<' + 'I' * n_mips, data, off)
    off += 4 * n_mips
    if tuple(int(h) for h in harms) != tuple(HARM):
        raise ValueError(f'harmonic_limits {harms} != {HARM}')
    duties = struct.unpack_from('<' + 'f' * n_pulse, data, off)
    off += 4 * n_pulse
    guard = flags & 1
    span = (length + (1 if guard else 0))
    need = (3 + n_pulse) * n_mips * span
    floats = struct.unpack_from('<' + 'f' * need, data, off)

    def take(i):
        mips = []
        for m in range(n_mips):
            sl = floats[(i * n_mips + m) * span:(i * n_mips + m) * span + span]
            if not guard:
                sl = list(sl) + [sl[0]]
            else:
                sl = list(sl)
            mips.append([f32(x) for x in sl])
        return mips

    return WaveSet(take(0), take(1), take(2), [take(3 + i) for i in range(n_pulse)],
                    duties=duties, source=path)


def dump_f32(waves: WaveSet, path: str):
    hdr = struct.pack('<4sIIIII', b'SWV1', 1, N, MIPS, len(waves.duties), 1)
    hdr += struct.pack('<' + 'I' * MIPS, *HARM)
    hdr += struct.pack('<' + 'f' * len(waves.duties), *waves.duties)
    body = []
    for mips in (waves.saw, waves.sine, waves.square, *waves.pulse):
        for mip in mips:
            body.extend(mip)
    blob = hdr + struct.pack('<' + 'f' * len(body), *body)
    with open(path, 'wb') as f:
        f.write(blob)


def dump_json(waves: WaveSet, path: str):
    def mips(stack):
        return [[float(x) for x in mip] for mip in stack]
    doc = {
        'version': 1,
        'length': N,
        'mips': MIPS,
        'guard': True,
        'harmonic_limits': list(HARM),
        'note': 'From-scratch Fourier defaults, or a file you built locally. Do not commit Monomachine-derived tables.',
        'waves': {
            'saw': mips(waves.saw),
            'sine': mips(waves.sine),
            'square': mips(waves.square),
            'pulse': {
                'duties': list(waves.duties),
                'cycles': [mips(p) for p in waves.pulse],
            },
        },
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(doc, f)


def load_waves(path: str | None = None) -> WaveSet:
    """Default cycles, or the file at `path` / $SWAVE_WAVE_TABLE.

    `.json` / `.swave.json` is JSON. Anything else is read as SWV1 raw
    float32 if it starts with that magic; a leading '{' is JSON too.
    """
    if path is None:
        path = os.environ.get('SWAVE_WAVE_TABLE', '').strip() or None
    if not path:
        return default_waves()
    with open(path, 'rb') as f:
        head = f.read(8)
    if head.startswith(b'{') or path.endswith('.json'):
        return load_json(path)
    if head.startswith(b'SWV1') or path.endswith('.f32') or path.endswith('.swave.f32'):
        return load_f32(path)
    raise ValueError(f'unrecognised wave table {path}')


def _main(argv):
    ap = argparse.ArgumentParser(description='Inspect or write a SuperWave waveform table.')
    ap.add_argument('--wave-table', default=os.environ.get('SWAVE_WAVE_TABLE') or None,
                    help='external table to load instead of the built-in Fourier cycles')
    ap.add_argument('--dump-json', metavar='PATH')
    ap.add_argument('--dump-f32', metavar='PATH')
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args(argv)
    waves = load_waves(args.wave_table)
    print(f'source {waves.source}')
    print(f'N {N}  mips {MIPS}  harmonics {HARM}')
    print(f'pulse duties {waves.duties}')
    print(f'data block {len(waves.flat_words())} words  ({len(waves.flat_words()) * 4} bytes)')
    if args.dump_json:
        dump_json(waves, args.dump_json)
        print('wrote', args.dump_json)
    if args.dump_f32:
        dump_f32(waves, args.dump_f32)
        print('wrote', args.dump_f32)
    if args.check or args.wave_table:
        # touching every sample forces the finite-value check in WaveSet
        waves._check()
        print('ok')
    return 0


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
