"""Shared laws for the FM+DYNAMIC and FM+PARALLELL engines.

Original work (MIT, see LICENSE). The curves below are written from the
Monomachine manual's descriptions and the FM+ envelope figure. They are not
copied from Elektron firmware. Where the manual does not print a number
(decay times, the 128 listed ratios, how steep "high" feedback is), the
constant is named here so it can be tuned by ear against a real Monomachine.

Manual: Elektron Monomachine User's Manual, OS 1.32
https://www.elektron.se/wp-content/uploads/2024/09/monomachine_manual_OS1.32.pdf
  Appendix A p. A-6  FM+ family, FM+ ENVELOPE PARAMETER VALUE figure
  Appendix A p. A-7  FM+PARALLELL, FM+DYNAMIC, TONE, TUNE
  Parameter editing p. 1-25  TUNE is ±100 cents

Sine samples and the listed-frequency ratios can be replaced at build time
with a local file (JSON or raw float32). See engines/INTERFACE.md. This
module never reads a Monomachine OS image.
"""
from __future__ import annotations

import json
import math
import os
import struct

SR = 48000
BLOCK = 32
N_PARAMS = 8
N_RATIOS = 128
N_SINE_DEFAULT = 2048
N_SINE_MIN = 64
N_SINE_MAX = 4096

# Stock Digitone II machine ids (firmware.md). Never render these.
STOCK_MACHINES = {
    0: 'FM TONE',
    1: 'WAVETONE',
    2: 'FM DRUM',
    3: 'SWARMER',
    4: 'MIDI',
}
MACHINE_FM_DYNAMIC = 5
MACHINE_FM_PARALLEL = 6
MACHINE_FM_STATIC = 7       # reserved for the FM+STATIC engine built elsewhere
MACHINE_SUPERWAVE = 8       # reserved

# DSP "skip the stock oscillator loops" sentinel. This is the same numeric
# value as the MIDI machine, but it is NOT a claim on the MIDI machine: we
# write it only into the engine-word of a voice whose machine id is already
# 5 or 6, after our own render. Stock voices are not touched. See INTERFACE.md.
ENGINE_WORD_SKIP_STOCK = 4

ENV_TABLE = 'DN2_FM_TABLES'
MAGIC = b'FM2T'
TABLE_VERSION = 1
MAX_TABLE_BYTES = 1_000_000

# --- ear-tune constants (one place) -----------------------------------------
# FM+ envelope figure (manual A-6): at or below 64 the level holds; above 64
# it starts at full and dies faster as the knob rises. Times are not printed
# in the manual. TAU_FAST is the 127 decay; the 65 end is almost a hold.
ENV_TAU_FAST = 0.004          # seconds at knob 127
ENV_TAU_SHAPE = 6.0           # larger = slower near 65, same fast end

# 1FEN / 1VEN: one knob is both depth and speed (manual A-7).
FEN_DEPTH_MAX = 4.0           # added to the linear ratio at knob 127
FEN_HZ_MAX = 4000.0           # used only when LINEAR_TRACKS_NOTE is False
VEN_DEPTH_MAX = 1.0
FEN_TAU_FAST = 0.006
FEN_TAU_SHAPE = 5.5

# 1FRQ linear law. True: ratio = knob/64, tracks the note (the manual's
# example screen shows "1.0" next to an exponential "1.33", i.e. ratios).
# False: 1FRQ is Hz from 0..LINEAR_HZ_MAX and does not track the keyboard.
LINEAR_TRACKS_NOTE = True
LINEAR_HZ_MAX = 8000.0

# 2FRQ exponential: equal knob steps are equal musical intervals.
# knob 64 = ratio 1. One octave per EXP_STEPS knobs.
EXP_STEPS = 16.0

# Listed ratios sit under knobs 0..127, four knobs per fraction, so the
# parameter feels stepped the way a "list" does. The manual's screens show
# 1/2, 1 and 2; those three are in this list. The rest is an original set of
# FM-useful fractions. Swap the whole list via DN2_FM_TABLES.
RATIO_FRACTIONS = (
    (1, 8), (1, 6), (1, 5), (1, 4), (1, 3), (2, 5), (1, 2), (3, 5),
    (2, 3), (3, 4), (4, 5), (1, 1), (5, 4), (4, 3), (3, 2), (5, 3),
    (7, 4), (2, 1), (5, 2), (3, 1), (7, 2), (4, 1), (5, 1), (6, 1),
    (7, 1), (8, 1), (9, 1), (10, 1), (12, 1), (16, 1), (20, 1), (24, 1),
)

# "High" 1VOL / the point where amplitude feedback starts. The manual says
# "high" and does not give the number.
VOL_FB_KNEE = 80
VOL_FB_MAX = 0.85
FB_MAX = 0.90                 # 2FB at knob 127

# TONE sits between the summed modulators and the carrier (diagram, A-7).
TONE_G0 = 0.15                # knob 0, dark
TONE_G1 = 1.85                # added by knob 127
TONE_H = 0.35                 # cubic harmonic amount at knob 127
TONE_CLIP = 2.5

# Radians-ish, stored as cycles of phase deviation per unit of modulator.
BETA = 0.20
DEV_CLIP = 2.0                # cycles; saturate, do not wrap a runaway
PHASE_BIAS = 4.0              # keeps the sine argument positive for TRUNC

IDLE_FLOOR = 1.0e-4
OUT_GAIN_DEFAULT = 1.0

# L2 homes for the slot-in (sharc.md: 0x20098000..0x200B0000 is free data).
L2_STATE = 0x20098000
STATE_WORDS = 128
STATE_BYTES = STATE_WORDS * 4
N_VOICES = 16
L2_TABLES = L2_STATE + N_VOICES * STATE_BYTES
ENGINE_WORD_BASE = 0x2554B8
ENGINE_WORD_STRIDE = 564
ENGINE_WORD_OFFSET = 436
VOICE_BUF_BASE = 0x804ACF90
VOICE_BUF_STRIDE = 128        # bytes, 32 floats

# Common voice-state word offsets. Engines use a subset. 32..127 is scratch.
W_ACTIVE = 0
W_TRIG = 1
W_P0 = 2                      # eight knobs, integers 0..127
W_NOTE_HZ = 10
W_OUT_GAIN = 11
W_TAB = 12                    # byte address of the packed table blob
W_PH_C = 13
W_PH_1 = 14
W_PH_2 = 15
W_PH_3 = 16
W_ENV_1 = 17
W_ENV_2 = 18
W_ENV_3 = 19
W_FEN = 20
W_VEN = 21
W_Z1 = 22
W_Z2 = 23
W_Z3 = 24
W_SCRATCH = 32                # 32 floats
W_INCBUF = 64                 # 32 floats, dynamic modulator 1
W_LEVBUF = 96                 # 32 floats, dynamic modulator 1


def f32(x):
    """IEEE float32 round-trip. Denormals flushed, matching SHARC sim.u_of."""
    try:
        u = struct.unpack('<I', struct.pack('<f', float(x)))[0]
    except OverflowError:
        u = 0x7F800000 if float(x) > 0 else 0xFF800000
    if (u & 0x7F800000) == 0:
        u &= 0x80000000
    return struct.unpack('<f', struct.pack('<I', u))[0]


def f32_bits(x):
    return struct.unpack('<I', struct.pack('<f', f32(x)))[0]


SR_INV = f32(1.0 / SR)
VOL_SCALE = f32(1.0 / 127.0)
FB_SCALE = f32(FB_MAX / 127.0)


def bits_f32(u):
    return struct.unpack('<f', struct.pack('<I', u & 0xFFFFFFFF))[0]


def knob(p):
    p = int(p)
    if p < 0:
        return 0
    if p > 127:
        return 127
    return p


def is_power_of_two(n):
    return n >= 2 and (n & (n - 1)) == 0


def default_sine(n=N_SINE_DEFAULT):
    return [f32(math.sin(2.0 * math.pi * i / n)) for i in range(n)]


def ratio_label(numer, denom):
    if denom == 1:
        return str(numer)
    return f'{numer}/{denom}'


def default_ratio_entries():
    """(label, float) per knob, 4 knobs per listed fraction."""
    if len(RATIO_FRACTIONS) * 4 != N_RATIOS:
        raise RuntimeError('RATIO_FRACTIONS must cover 128 knob steps')
    out = []
    for numer, denom in RATIO_FRACTIONS:
        label = ratio_label(numer, denom)
        value = f32(numer / denom)
        for _ in range(4):
            out.append((label, value))
    return out


def default_ratios():
    return [v for _, v in default_ratio_entries()]


def exp_ratio(p):
    return f32(2.0 ** ((knob(p) - 64) / EXP_STEPS))


def linear_ratio(p):
    return f32(knob(p) / 64.0)


def tune_cents(p):
    """Bipolar knob: displayed (p-64) is -64..+63. Span is 100 cents down
    and just under 100 cents up (63 steps). Manual p. 1-25."""
    return (knob(p) - 64) * (100.0 / 64.0)


def tune_ratio(p):
    return f32(2.0 ** (tune_cents(p) / 1200.0))


def _tau(u, fast, shape):
    # u = 0 → slow, u = 1 → fast
    return fast * math.exp(shape * (1.0 - u))


def _coeff(tau):
    if tau <= 0:
        return f32(0.0)
    return f32(math.exp(-1.0 / (tau * SR)))


def compute_curves():
    """Per-knob tables. Formulas live only here; the DSP loads the floats."""
    decay, start = [], []
    for p in range(128):
        if p <= 64:
            start.append(f32(p / 64.0))
            decay.append(f32(1.0))
        else:
            u = (p - 64) / 63.0
            start.append(f32(1.0))
            decay.append(_coeff(_tau(u, ENV_TAU_FAST, ENV_TAU_SHAPE)))
    fen_d, fen_c, ven_d, ven_c = [], [], [], []
    for p in range(128):
        u = p / 127.0
        if LINEAR_TRACKS_NOTE:
            fen_d.append(f32(u * FEN_DEPTH_MAX))
        else:
            fen_d.append(f32(u * FEN_HZ_MAX))
        ven_d.append(f32(u * VEN_DEPTH_MAX))
        if p == 0:
            fen_c.append(f32(1.0))
            ven_c.append(f32(1.0))
        else:
            tau = _tau(u, FEN_TAU_FAST, FEN_TAU_SHAPE)
            fen_c.append(_coeff(tau))
            ven_c.append(_coeff(tau))
    vol_fb = []
    span = 127 - VOL_FB_KNEE
    for p in range(128):
        if p < VOL_FB_KNEE:
            vol_fb.append(f32(0.0))
        else:
            t = (p - VOL_FB_KNEE) / span
            vol_fb.append(f32((t * t) * VOL_FB_MAX))
    tone_g, tone_h = [], []
    for p in range(128):
        u = p / 127.0
        tone_g.append(f32(TONE_G0 + u * TONE_G1))
        tone_h.append(f32(u * u * TONE_H))
    return {
        'decay': decay,
        'start': start,
        'fen_d': fen_d,
        'fen_c': fen_c,
        'ven_d': ven_d,
        'ven_c': ven_c,
        'vol_fb': vol_fb,
        'tone_g': tone_g,
        'tone_h': tone_h,
        'exp_ratio': [exp_ratio(p) for p in range(128)],
        'tune': [tune_ratio(p) for p in range(128)],
    }


def layout(n_sine):
    """Word offsets into the packed blob. sine, then ratios, then curves."""
    order = (
        'ratios', 'decay', 'start', 'fen_d', 'fen_c', 'ven_d', 'ven_c',
        'vol_fb', 'tone_g', 'tone_h', 'exp_ratio', 'tune',
    )
    off = {'sine': 0}
    at = n_sine
    for name in order:
        off[name] = at
        at += N_RATIOS
    off['words'] = at
    return off


def make_tables(sine=None, ratios=None):
    curves = compute_curves()
    sine = default_sine() if sine is None else [f32(x) for x in sine]
    ratios = default_ratios() if ratios is None else [f32(x) for x in ratios]
    _check_sine(sine)
    _check_ratios(ratios)
    tables = {'sine': sine, 'ratios': ratios}
    tables.update(curves)
    tables['_layout'] = layout(len(sine))
    return tables


def _check_sine(sine):
    n = len(sine)
    if n < N_SINE_MIN or n > N_SINE_MAX or not is_power_of_two(n):
        raise ValueError(
            f'sine table length must be a power of two from {N_SINE_MIN} to '
            f'{N_SINE_MAX} (got {n})')
    for i, x in enumerate(sine):
        if not math.isfinite(x) or abs(x) > 1.25:
            raise ValueError(f'sine[{i}] is {x!r}; need a finite sample in ±1.25')


def _check_ratios(ratios):
    if len(ratios) != N_RATIOS:
        raise ValueError(f'ratio list must be {N_RATIOS} floats (one per knob), got {len(ratios)}')
    for i, x in enumerate(ratios):
        if not math.isfinite(x) or x < 0.0 or x > 64.0:
            raise ValueError(f'ratios[{i}] is {x!r}; need a finite ratio from 0 to 64')


def _load_json(raw):
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError) as e:
        raise ValueError(f'FM table JSON could not be read: {e}') from e
    if not isinstance(data, dict):
        raise ValueError('FM table JSON must be an object with "sine" and/or "ratios"')
    sine = data.get('sine')
    ratios = data.get('ratios', data.get('ratio'))
    if sine is None and ratios is None:
        raise ValueError('FM table JSON needs a "sine" array, a "ratios" array, or both')
    if sine is not None:
        if not isinstance(sine, list):
            raise ValueError('"sine" must be an array of numbers')
        sine = [float(x) for x in sine]
    if ratios is not None:
        if not isinstance(ratios, list):
            raise ValueError('"ratios" must be an array of numbers')
        ratios = [float(x) for x in ratios]
    return sine, ratios


def _load_raw(raw):
    if len(raw) < 16 or raw[:4] != MAGIC:
        raise ValueError('not an FM table (JSON object or FM2T raw float32)')
    version, n_sine, n_ratio = struct.unpack_from('<III', raw, 4)
    if version != TABLE_VERSION:
        raise ValueError(f'FM2T version {version} is not supported (want {TABLE_VERSION})')
    need = 16 + 4 * (n_sine + n_ratio)
    if len(raw) < need:
        raise ValueError(f'FM2T file is short ({len(raw)} bytes, need {need})')
    sine = list(struct.unpack_from('<' + 'f' * n_sine, raw, 16))
    ratios = list(struct.unpack_from('<' + 'f' * n_ratio, raw, 16 + 4 * n_sine))
    return sine, ratios


def load_table_file(path):
    """Load a local sine and/or ratio override. Does not touch any OS image."""
    with open(path, 'rb') as f:
        raw = f.read(MAX_TABLE_BYTES + 1)
    if len(raw) > MAX_TABLE_BYTES:
        raise ValueError(f'{path} is larger than {MAX_TABLE_BYTES} bytes')
    if raw[:4] == MAGIC:
        sine, ratios = _load_raw(raw)          # a bad version must not be reread as JSON
    elif raw[:1] in (b'{', b' ', b'\n', b'\t', b'['):
        sine, ratios = _load_json(raw)
    else:
        try:
            sine, ratios = _load_json(raw)
        except ValueError:
            sine, ratios = _load_raw(raw)
    return make_tables(sine=sine, ratios=ratios)


def active_tables(path=None):
    """Built-in defaults, unless path or DN2_FM_TABLES names a local file."""
    path = path if path else os.environ.get(ENV_TABLE)
    if not path:
        return make_tables()
    return load_table_file(path)


def pack_tables(tables):
    lay = tables['_layout']
    words = [0.0] * lay['words']
    for name, off in lay.items():
        if name in ('words',):
            continue
        src = tables[name]
        words[off:off + len(src)] = src
    return struct.pack('<' + 'f' * len(words), *[f32(w) for w in words])


def dump_raw(path, tables):
    sine, ratios = tables['sine'], tables['ratios']
    blob = struct.pack('<4sIII', MAGIC, TABLE_VERSION, len(sine), len(ratios))
    blob += struct.pack('<' + 'f' * len(sine), *sine)
    blob += struct.pack('<' + 'f' * len(ratios), *ratios)
    with open(path, 'wb') as f:
        f.write(blob)


def midi_hz(note):
    return 440.0 * (2.0 ** ((float(note) - 69.0) / 12.0))


def engine_word_addr(voice):
    voice = int(voice)
    if not 0 <= voice < N_VOICES:
        raise ValueError(f'voice {voice} is outside 0..{N_VOICES - 1}')
    return ENGINE_WORD_BASE + ENGINE_WORD_STRIDE * voice + ENGINE_WORD_OFFSET


def state_addr(voice):
    voice = int(voice)
    if not 0 <= voice < N_VOICES:
        raise ValueError(f'voice {voice} is outside 0..{N_VOICES - 1}')
    return L2_STATE + voice * STATE_BYTES


def voice_buf_addr(voice):
    voice = int(voice)
    if not 0 <= voice < N_VOICES:
        raise ValueError(f'voice {voice} is outside 0..{N_VOICES - 1}')
    return VOICE_BUF_BASE + voice * VOICE_BUF_STRIDE


def decide(machine, engine_word):
    """Pure policy the SHARC hook implements.

    Stock ids 0..4, and any id we do not own (7 and 8 until those engines
    exist), pass through with the engine word unchanged. Ids 5 and 6 are
    ours: the hook will render them and then store ENGINE_WORD_SKIP_STOCK
    so the stock oscillator loops do not also render that voice.
    Returns (which, engine_word) where which is 0 passthrough, 5, or 6.
    """
    machine = int(machine)
    if machine == MACHINE_FM_DYNAMIC or machine == MACHINE_FM_PARALLEL:
        return machine, ENGINE_WORD_SKIP_STOCK
    return 0, int(engine_word)


def clamp_params(params):
    if len(params) != N_PARAMS:
        raise ValueError(f'need {N_PARAMS} parameters, got {len(params)}')
    return [knob(p) for p in params]


def step_hold_env(env, param, trig, tables):
    """FM+ envelope figure. Returns (env, per-sample coeff)."""
    param = knob(param)
    if param <= 64:
        env = tables['start'][param]
    elif trig:
        env = tables['start'][param]
    return env, tables['decay'][param]


def samples_to_half(coeff, start=1.0, limit=2_000_000):
    if coeff >= 1.0:
        return None
    x, n = start, 0
    while x > 0.5 and n < limit:
        x *= coeff
        n += 1
    return n


def clip(x, lim):
    lim = abs(float(lim))
    if x > lim:
        return lim
    if x < -lim:
        return -lim
    return x


def tone_shape(m, g, h):
    """TONE block: gain, then a cubic, then saturate. Diagram on manual p. A-7."""
    y = clip(m * g, TONE_CLIP)
    y = y + h * y * y * y
    return clip(y, TONE_CLIP)


def advance_osc(ph, inc, fb, z, sine):
    """One oscillator sample. The SHARC loop in sharc_osc.emit_osc matches this.

    Phase stays non-negative. The sine argument is biased by PHASE_BIAS so
    TRUNC (toward zero) still wraps a small negative feedback offset.
    """
    n = len(sine)
    nxt = ph + inc
    if nxt < 0.0:
        nxt = 0.0
    ph = nxt - math.trunc(nxt)
    arg = ph + fb * z + PHASE_BIAS
    if arg < 0.0:
        arg = 0.0
    frac = arg - math.trunc(arg)
    idx = int(math.trunc(frac * n)) & (n - 1)
    return ph, float(sine[idx])


def note_inc(hz, tune):
    return float(hz) * float(SR_INV) * float(tune)


def silent_block():
    return [0.0] * BLOCK


def write_wav(path, samples, peak=0.5):
    """16-bit mono WAV at 48 kHz. Scaled for listening; the DSP gain is separate."""
    import wave
    m = max((abs(x) for x in samples), default=0.0)
    scale = 0.0 if m < 1e-8 else peak / m
    frames = b''.join(
        struct.pack('<h', max(-32767, min(32767, int(x * scale * 32767.0))))
        for x in samples)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(frames)
    return m


def new_words():
    """128 zero words plus a sane tune knob and output gain."""
    w = [0] * STATE_WORDS
    w[W_P0 + 7] = 64
    w[W_NOTE_HZ] = f32_bits(440.0)
    w[W_OUT_GAIN] = f32_bits(OUT_GAIN_DEFAULT)
    w[W_TAB] = L2_TABLES
    return w


def put_params(words, params):
    for i, p in enumerate(clamp_params(params)):
        words[W_P0 + i] = p


def get_params(words):
    return [words[W_P0 + i] & 0x7F for i in range(N_PARAMS)]
