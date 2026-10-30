"""FM+PARALLELL SHARC kernel, in three calls so each one fits in 16 registers.

prep bakes the ratios and envelopes, osc fills the modulator sum, carrier
applies TONE and writes the voice buffer. render calls them in that order.
A sleeping voice is zeroed in prep; osc and carrier then return immediately.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import fm_common as C
import sharc_osc as O

_DEC = (25, 26, 27)
_INC = (28, 29, 30)
_NINC, _G, _H = 31, C.W_FEN, C.W_VEN
_MOD = (
    (0, 1, C.W_PH_1, C.W_ENV_1, 0),
    (2, 3, C.W_PH_2, C.W_ENV_2, 1),
    (4, 5, C.W_PH_3, C.W_ENV_3, 2),
)


def _fx():
    return __import__('fxdsl')


def _bake_env(k, st, tab, lay, env_word, knob_i, was, dec_word):
    p = O.load_knob(k, st, knob_i)
    with k.if_(p <= 64):
        k.st(st, env_word, O.take(k, tab, lay['start'], p))
    with k.if_(p > 64):
        with k.if_(was != 0):
            k.st(st, env_word, k.f(1.0))
    k.st(st, dec_word, O.take(k, tab, lay['decay'], p))


def _asleep(k, st):
    active = k.var('i', k.ld(st, C.W_ACTIVE, 'i'))
    with k.if_(active == 0):
        k.ret()


def build(tables=None):
    tables = tables or C.make_tables()
    n = len(tables['sine'])
    lay = tables['_layout']
    F = _fx()
    prep = F.Kernel('fm_par_prep', inputs={'state': 'I4', 'buf': 'I5'})
    osc = F.Kernel('fm_par_osc', inputs={'state': 'I4', 'buf': 'I5'})
    car = F.Kernel('fm_par_car', inputs={'state': 'I4', 'buf': 'I5'})
    _prep(prep, lay)
    _osc(osc, n)
    _car(car, n)
    return [prep, osc, car]


def _prep(k, lay):
    st = k['state']
    was = k.var('i', k.ld(st, C.W_TRIG, 'i'))
    with k.if_(was != 0):
        z = k.f(0.0)
        for off in (C.W_PH_C, C.W_PH_1, C.W_PH_2, C.W_PH_3):
            k.st(st, off, z)
        k.st(st, C.W_ACTIVE, k.i(1), t='i')
        k.st(st, C.W_TRIG, k.i(0), t='i')
    active = k.var('i', k.ld(st, C.W_ACTIVE, 'i'))
    with k.if_(active == 0):
        O.zero_buf(k, k['buf'])
        k.ret()
    tab = k.var('i', k.ld(st, C.W_TAB, 'i'))
    hz = O.load_f(k, st, C.W_NOTE_HZ)
    ninc = k.var('f')
    k.set(ninc, (hz * k.f(C.SR_INV)) * O.take(k, tab, lay['tune'], O.load_knob(k, st, 7)))
    k.st(st, _NINC, ninc)
    for fi, ei, _ph, env_w, slot in _MOD:
        _bake_env(k, st, tab, lay, env_w, ei, was, _DEC[slot])
        p = O.load_knob(k, st, fi)
        k.st(st, _INC[slot], ninc * O.take(k, tab, lay['ratios'], p))
    k.st(st, _G, O.take(k, tab, lay['tone_g'], O.load_knob(k, st, 6)))
    k.st(st, _H, O.take(k, tab, lay['tone_h'], O.load_knob(k, st, 6)))


def _osc(k, n):
    st = k['state']
    _asleep(k, st)
    tab = k.var('i', k.ld(st, C.W_TAB, 'i'))
    sine = k.ptr(tab)
    st_i = k.var('i', k.int_of(st))
    zero = k.f(0.0)
    first = True
    for _fi, _ei, ph_w, env_w, slot in _MOD:
        ph = O.load_f(k, st, ph_w)
        env = O.load_f(k, st, env_w)
        z = k.var('f', 0.0)
        dst = O.buf_ptr(k, st_i, C.W_SCRATCH)
        src = None if first else O.buf_ptr(k, st_i, C.W_SCRATCH)
        O.emit_osc(
            k, sine, n, ph, O.load_f(k, st, _INC[slot]), zero, z, env,
            O.load_f(k, st, _DEC[slot]), dst, src=src)
        k.st(st, ph_w, ph)
        k.st(st, env_w, env)
        first = False


def _car(k, n):
    st = k['state']
    _asleep(k, st)
    tab = k.var('i', k.ld(st, C.W_TAB, 'i'))
    sine = k.ptr(tab)
    st_i = k.var('i', k.int_of(st))
    ph = O.load_f(k, st, C.W_PH_C)
    O.emit_carrier(
        k, sine, n, ph, O.load_f(k, st, _NINC), O.load_f(k, st, C.W_OUT_GAIN),
        O.buf_ptr(k, st_i, C.W_SCRATCH), k.ptr(k.int_of(k['buf'])),
        O.load_f(k, st, _G), O.load_f(k, st, _H))
    k.st(st, C.W_PH_C, ph)


def initial_words(params, hz, trig=1):
    w = C.new_words()
    C.put_params(w, params)
    w[C.W_TRIG] = 1 if trig else 0
    w[C.W_NOTE_HZ] = C.f32_bits(hz)
    w[C.W_OUT_GAIN] = C.f32_bits(C.OUT_GAIN_DEFAULT)
    w[C.W_TAB] = C.L2_TABLES
    return w
