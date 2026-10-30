"""Python twin of fm_par.c.

Reads the placeholder curves from fm_par_curves.h, so that file is the
only place to retune. Generic libm sine. No wavetable and no sweep data.
"""
from __future__ import annotations

import ctypes
import math
import os
import re
import struct

HERE = os.path.dirname(os.path.abspath(__file__))

PARAMS = (
    ('1FRQ', '0–127', 'Modulator 1 listed frequency, 24 musical steps. Manual A-7.'),
    ('1ENV', '0–127', 'Modulator 1 amount. Peaks, then folds back. Manual A-7.'),
    ('2FRQ', '0–127', 'Modulator 2 listed frequency. Manual A-7.'),
    ('2ENV', '0–127', 'Modulator 2 amount. Manual A-7.'),
    ('3FRQ', '0–127', 'Modulator 3 listed frequency. This one dominates brightness. Manual A-7.'),
    ('3ENV', '0–127', 'Modulator 3 amount. Manual A-7.'),
    ('TONE', '0–127', 'Brightness of the modulators. Saturates toward the top. Manual A-7.'),
    ('TUNE', '−64–+63 (stored 0–127)', 'Output tune, symmetric about 64. Manual p. 1-25 and A-7.'),
)

_MUSICAL = (
    (1, 64), (1, 32), (1, 16), (3, 32), (1, 8), (5, 32), (3, 16), (1, 4),
    (5, 16), (3, 8), (7, 16), (1, 2), (5, 8), (3, 4), (7, 8), (1, 1),
    (5, 4), (3, 2), (7, 4), (2, 1), (5, 2), (3, 1), (7, 2), (4, 1),
)


def _texts():
    h = open(os.path.join(HERE, 'fm_par.h'), encoding='utf-8').read()
    c = open(os.path.join(HERE, 'fm_par_curves.h'), encoding='utf-8').read()
    return h, c


def _defines(text):
    out = {}
    for name, raw in re.findall(r'#define\s+(FM_PAR_[A-Z0-9_]+)\s+([0-9.eE+-]+)f?\b', text):
        out[name] = float(raw) if ('.' in raw or 'e' in raw.lower()) else int(raw)
    return out


def _u8_array(text, name):
    m = re.search(r'%s\[24\] = \{([^}]+)\}' % name, text)
    if not m:
        raise RuntimeError('missing %s' % name)
    vals = [int(x) for x in re.findall(r'\d+', m.group(1))]
    if len(vals) != 24:
        raise RuntimeError('%s should have 24 entries' % name)
    return vals


def _bps(text, name):
    m = re.search(r'%s\[\] = \{([^;]+)\};' % name, text)
    if not m:
        raise RuntimeError('missing %s' % name)
    pairs = re.findall(r'\{\s*(\d+)\s*,\s*([+-]?[0-9.]+)f?\s*\}', m.group(1))
    if not pairs:
        raise RuntimeError('%s has no breakpoints' % name)
    return [(int(k), float(y)) for k, y in pairs]


def _floats(text, name):
    m = re.search(r'%s\[3\] = \{([^}]+)\}' % name, text)
    if not m:
        raise RuntimeError('missing %s' % name)
    return [float(x) for x in re.findall(r'[+-]?[0-9.]+', m.group(1))]


_H, _C = _texts()
H = _defines(_H + '\n' + _C)
RATIOS = tuple(
    list(zip(_u8_array(_C, 'fm_par_frq%d_n' % i), _u8_array(_C, 'fm_par_frq%d_d' % i)))
    for i in (1, 2, 3)
)
ENVS = tuple(_bps(_C, 'fm_par_env%d' % i) for i in (1, 2, 3))
TONE = _bps(_C, 'fm_par_tone')
TUNE = _bps(_C, 'fm_par_tune')
MOD_W = _floats(_C, 'fm_par_mod_w')
MUSICAL = _MUSICAL

SR = int(H['FM_PAR_SR'])
STATE_BYTES = int(H['FM_PAR_STATE_BYTES'])
N_PARAMS = int(H['FM_PAR_N_PARAMS'])
N_FRQ = int(H['FM_PAR_N_FRQ'])
MACHINE_ID = int(H['FM_PAR_MACHINE_ID'])

_libm = ctypes.CDLL('libm.so.6')


def _unary(name):
    fn = getattr(_libm, name)
    fn.argtypes = [ctypes.c_float]
    fn.restype = ctypes.c_float
    return fn


_sinf = _unary('sinf')
_exp2f = _unary('exp2f')
_floorf = _unary('floorf')


def f32(x):
    u = struct.unpack('<I', struct.pack('<f', float(x)))[0]
    if (u & 0x7F800000) == 0:
        return 0.0
    return struct.unpack('<f', struct.pack('<I', u))[0]


for _name, _val in list(H.items()):
    if isinstance(_val, float):
        H[_name] = f32(_val)
MOD_W[:] = [f32(w) for w in MOD_W]


def _call(fn, x):
    return float(fn(ctypes.c_float(f32(x))))


def flush(x):
    if isinstance(x, float) and math.isnan(x):
        return 0.0
    return f32(x)


def wrap01(x):
    if math.isnan(float(x)):
        return 0.0
    w = f32(float(x) - _call(_floorf, x))
    if not (w >= 0.0 and w < 1.0):
        return 0.0
    return w


def clampf(x, lim):
    if math.isnan(float(x)):
        return 0.0
    lim = abs(float(lim))
    if x > lim:
        return f32(lim)
    if x < -lim:
        return f32(-lim)
    return f32(x)


def knob_of(p):
    p = int(p)
    if p < 0:
        return 0
    if p > 127:
        return 127
    return p


def sanitize_hz(hz):
    hz = float(hz)
    if not (hz > 0.0) or math.isnan(hz):
        return 0.0
    if hz > H['FM_PAR_HZ_MAX']:
        return f32(H['FM_PAR_HZ_MAX'])
    return flush(hz)


def sanitize_gain(g):
    g = float(g)
    if math.isnan(g):
        return 0.0
    if g < 0.0:
        g = -g
    if g > H['FM_PAR_OUT_GAIN_MAX']:
        g = H['FM_PAR_OUT_GAIN_MAX']
    g = flush(g)
    if g < H['FM_PAR_DENORM_FLOOR']:
        return 0.0
    return g


def bp_eval(bp, knob):
    # y is stored as float32, matching the C literal. Subtracting the
    # decimal doubles first would miss by an ulp.
    pts = [(k, f32(y)) for k, y in bp]
    knob = knob_of(knob) if knob <= 127 else knob
    if knob <= pts[0][0]:
        return pts[0][1]
    for i in range(1, len(pts)):
        if knob <= pts[i][0]:
            span = pts[i][0] - pts[i - 1][0]
            if span <= 0:
                return pts[i][1]
            t = f32(float(knob - pts[i - 1][0]) / float(span))
            dy = f32(pts[i][1] - pts[i - 1][1])
            return f32(pts[i - 1][1] + f32(t * dy))
    return pts[-1][1]


def frq_index(knob):
    i = knob_of(knob) * N_FRQ // 128
    if i < 0:
        return 0
    if i > N_FRQ - 1:
        return N_FRQ - 1
    return i


def frq_ratio(op, knob):
    numer, denom = RATIOS[op][frq_index(knob)]
    return f32(float(numer) / float(denom))


def env_amount(op, knob):
    return bp_eval(ENVS[op], knob_of(knob))


def tone_open(knob):
    return bp_eval(TONE, knob_of(knob))


def tune_cents(knob):
    return bp_eval(TUNE, knob_of(knob))


def sine_cycle(phase01):
    s = _call(_sinf, f32(phase01 * H['FM_PAR_TAU']))
    if s > 1.0:
        return 1.0
    if s < -1.0:
        return -1.0
    if math.isnan(s):
        return 0.0
    return f32(s)


class Voice:
    def __init__(self):
        self.phase_c = 0.0
        self.phase_m = [0.0, 0.0, 0.0]
        self.env = [0.0, 0.0, 0.0]
        self.note_hz = 0.0
        self.out_gain = f32(H['FM_PAR_OUT_GAIN_DEFAULT'])
        self.tone_z = 0.0
        self.param = [0, 0, 0, 0, 0, 0, 0, 64]
        self.active = 0
        self.trig = 0

    def set_params(self, params):
        if len(params) != N_PARAMS:
            raise ValueError('need %d parameters' % N_PARAMS)
        self.param = [knob_of(p) for p in params]

    def note_on(self, hz):
        self.note_hz = sanitize_hz(hz)
        self.trig = 1

    def render(self, n):
        n = int(n)
        if self.trig:
            self.phase_c = 0.0
            self.phase_m = [0.0, 0.0, 0.0]
            self.tone_z = 0.0
            self.active = 1
            self.trig = 0
        if not self.active:
            return [0.0] * n

        self.note_hz = sanitize_hz(self.note_hz)
        self.out_gain = sanitize_gain(self.out_gain)
        gain = self.out_gain
        self.phase_c = flush(wrap01(self.phase_c))
        for i in range(3):
            self.phase_m[i] = flush(wrap01(self.phase_m[i]))
            e = env_amount(i, self.param[i * 2 + 1])
            if not (e >= 0.0) or math.isnan(e):
                e = 0.0
            self.env[i] = flush(e)
        if math.isnan(self.tone_z) or self.tone_z > 1.0e20 or self.tone_z < -1.0e20:
            self.tone_z = 0.0
        else:
            self.tone_z = flush(self.tone_z)

        cents = tune_cents(self.param[7])
        tune = _call(_exp2f, f32(cents / 1200.0))
        if not (tune > 0.0):
            tune = 1.0
        ninc = f32(f32(self.note_hz * f32(1.0 / H['FM_PAR_SR'])) * tune)
        inc = [f32(ninc * frq_ratio(i, self.param[i * 2])) for i in range(3)]
        a = tone_open(self.param[6])
        if not (a >= 0.0) or math.isnan(a):
            a = 0.0
        if a > 1.0:
            a = 1.0
        a = f32(a)

        out = []
        for _ in range(n):
            m = 0.0
            for i in range(3):
                self.phase_m[i] = flush(wrap01(f32(self.phase_m[i] + inc[i])))
                ms = sine_cycle(self.phase_m[i])
                scaled = f32(ms * self.env[i])
                weighted = f32(MOD_W[i] * scaled)
                m = f32(m + weighted)
            z = self.tone_z
            z = f32(z + f32(a * f32(m - z)))
            z = flush(z)
            if z < H['FM_PAR_DENORM_FLOOR'] and z > -H['FM_PAR_DENORM_FLOOR']:
                z = 0.0
            self.tone_z = z
            dev = clampf(f32(z * H['FM_PAR_BETA']), H['FM_PAR_DEV_CLIP'])
            self.phase_c = flush(wrap01(f32(self.phase_c + ninc)))
            s = sine_cycle(wrap01(f32(self.phase_c + dev)))
            out.append(flush(clampf(f32(s * gain), gain)))
        return out
