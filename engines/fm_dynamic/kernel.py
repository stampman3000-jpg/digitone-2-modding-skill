"""FM+DYNAMIC SHARC kernel. Same sample math as reference.py.

render(I4 = voice state, I5 = 32-float buffer). The slot-in copies R4/R12
into those registers; see engines/INTERFACE.md. A sleeping voice (active = 0
and no note-on) writes zeros and returns.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import fm_common as C
import sharc_osc as O

# Header scratch. Not part of the portable 0..24 words.
_DEC2, _FB2, _FB1, _INC2, _NINC = 25, 26, 27, 28, 29
_LIN = C.f32(1.0 / 64.0)


def build(tables=None):
    tables = tables or C.make_tables()
    n = len(tables['sine'])
    lay = tables['_layout']
    k = __import__('fxdsl').Kernel('fm_dyn', inputs={'state': 'I4', 'buf': 'I5'})
    st = k['state']
    was = k.var('i', k.ld(st, C.W_TRIG, 'i'))
    tab = k.var('i', k.ld(st, C.W_TAB, 'i'))

    with k.if_(was != 0):
        z = k.f(0.0)
        for off in (C.W_PH_C, C.W_PH_1, C.W_PH_2, C.W_Z1, C.W_Z2):
            k.st(st, off, z)
        k.st(st, C.W_FEN, O.take(k, tab, lay['fen_d'], O.load_knob(k, st, 1)))
        k.st(st, C.W_VEN, O.take(k, tab, lay['ven_d'], O.load_knob(k, st, 3)))
        k.st(st, C.W_ACTIVE, k.i(1), t='i')
        k.st(st, C.W_TRIG, k.i(0), t='i')

    active = k.var('i', k.ld(st, C.W_ACTIVE, 'i'))
    with k.if_(active == 0):
        O.zero_buf(k, k['buf'])
        k.ret()

    st_i = k.var('i', k.int_of(st))
    hz = O.load_f(k, st, C.W_NOTE_HZ)
    ninc = k.var('f')
    k.set(ninc, (hz * k.f(C.SR_INV)) * O.take(k, tab, lay['tune'], O.load_knob(k, st, 7)))

    p0 = O.load_knob(k, st, 0)
    base = k.var('f')
    if C.LINEAR_TRACKS_NOTE:
        k.set(base, k.float(p0) * k.f(_LIN))
    else:
        k.set(base, (k.float(p0) * k.f(C.VOL_SCALE)) * k.f(C.LINEAR_HZ_MAX))

    fen = O.load_f(k, st, C.W_FEN)
    ven = O.load_f(k, st, C.W_VEN)
    fen_c = k.var('f')
    k.set(fen_c, O.take(k, tab, lay['fen_c'], O.load_knob(k, st, 1)))
    ven_c = k.var('f')
    k.set(ven_c, O.take(k, tab, lay['ven_c'], O.load_knob(k, st, 3)))

    p2 = O.load_knob(k, st, 2)
    k.st(st, _FB1, O.take(k, tab, lay['vol_fb'], p2))
    base_vol = k.var('f')
    k.set(base_vol, k.float(p2) * k.f(C.VOL_SCALE))

    p5 = O.load_knob(k, st, 5)
    with k.if_(p5 <= 64):
        k.st(st, C.W_ENV_2, O.take(k, tab, lay['start'], p5))
    with k.if_(p5 > 64):
        with k.if_(was != 0):
            k.st(st, C.W_ENV_2, k.f(1.0))
    k.st(st, _DEC2, O.take(k, tab, lay['decay'], p5))
    k.st(st, _FB2, k.float(O.load_knob(k, st, 6)) * k.f(C.FB_SCALE))
    k.st(st, _INC2, ninc * O.take(k, tab, lay['exp_ratio'], O.load_knob(k, st, 4)))

    O.emit_levels(
        k, fen, ven, base, base_vol, ninc, fen_c, ven_c,
        O.buf_ptr(k, st_i, C.W_INCBUF), O.buf_ptr(k, st_i, C.W_LEVBUF),
        C.LINEAR_TRACKS_NOTE, k.f(C.SR_INV))
    k.st(st, C.W_FEN, fen)
    k.st(st, C.W_VEN, ven)
    k.st(st, _NINC, ninc)

    sine = k.ptr(tab)
    ph = O.load_f(k, st, C.W_PH_1)
    z = O.load_f(k, st, C.W_Z1)
    fb = O.load_f(k, st, _FB1)
    O.emit_osc_lev(
        k, sine, n, ph, fb, z, O.buf_ptr(k, st_i, C.W_SCRATCH),
        O.buf_ptr(k, st_i, C.W_INCBUF), O.buf_ptr(k, st_i, C.W_LEVBUF))
    k.st(st, C.W_PH_1, ph)
    k.st(st, C.W_Z1, z)

    ph = O.load_f(k, st, C.W_PH_2)
    z = O.load_f(k, st, C.W_Z2)
    env = O.load_f(k, st, C.W_ENV_2)
    O.emit_osc(
        k, sine, n, ph, O.load_f(k, st, _INC2), O.load_f(k, st, _FB2), z, env,
        O.load_f(k, st, _DEC2), O.buf_ptr(k, st_i, C.W_SCRATCH),
        src=O.buf_ptr(k, st_i, C.W_SCRATCH))
    k.st(st, C.W_PH_2, ph)
    k.st(st, C.W_Z2, z)
    k.st(st, C.W_ENV_2, env)

    ph = O.load_f(k, st, C.W_PH_C)
    O.emit_carrier(
        k, sine, n, ph, O.load_f(k, st, _NINC), O.load_f(k, st, C.W_OUT_GAIN),
        O.buf_ptr(k, st_i, C.W_SCRATCH), k.ptr(k.int_of(k['buf'])))
    k.st(st, C.W_PH_C, ph)
    return k


def initial_words(params, hz, trig=1):
    w = C.new_words()
    C.put_params(w, params)
    w[C.W_TRIG] = 1 if trig else 0
    w[C.W_NOTE_HZ] = C.f32_bits(hz)
    w[C.W_OUT_GAIN] = C.f32_bits(C.OUT_GAIN_DEFAULT)
    w[C.W_TAB] = C.L2_TABLES
    return w
