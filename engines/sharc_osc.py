"""SHARC oscillator loops shared by the FM+ engines.

The sample math is the same as fm_common.advance_osc / tone_shape. One hardware
loop, no branches: phase wrap uses TRUNC, the table index is masked, feedback
and the output saturate in the caller.

Pointer budget inside a loop (I4 is the voice state and stays live): at most
four other pointers, I0–I3. Sine lookup is the one M4 use; unit-stride walks
use M6.
"""
from __future__ import annotations

import fm_common as C
import fxdsl


def emit_osc(k, sine, n, ph, inc, fb, z, env, decay, dst, src=None):
    """32 samples. Writes s*env, or prev+s*env when src is set. Updates ph, z, env."""
    mask = k.i(n - 1)
    nf = k.f(float(n))
    bias = k.f(C.PHASE_BIAS)
    nxt = k.var('f', 0.0)
    ph_w = k.var('f', 0.0)
    arg = k.var('f', 0.0)
    frac = k.var('f', 0.0)
    sv = k.var('f', 0.0)
    with k.loop(C.BLOCK):
        prev = k.ld_post(src) if src is not None else None
        k.set(nxt, ph + inc)
        k.set(ph_w, nxt - k.float(k.trunc(nxt)))
        k.set(arg, ph_w + fb * z + bias)
        k.set(frac, arg - k.float(k.trunc(arg)))
        k.set(sv, k.ldx(sine, k.trunc(frac * nf) & mask))
        y = sv * env
        if prev is not None:
            y = prev + y
        k.st_post(dst, y)
        k.set(z, sv)
        k.set(env, env * decay)
        k.set(ph, ph_w)


def emit_osc_lev(k, sine, n, ph, fb, z, dst, inc_p, lev_p):
    """32 samples with a per-sample increment and level (FM+DYNAMIC modulator 1)."""
    mask = k.i(n - 1)
    nf = k.f(float(n))
    bias = k.f(C.PHASE_BIAS)
    nxt = k.var('f', 0.0)
    ph_w = k.var('f', 0.0)
    arg = k.var('f', 0.0)
    frac = k.var('f', 0.0)
    sv = k.var('f', 0.0)
    with k.loop(C.BLOCK):
        inc = k.ld_post(inc_p)
        lev = k.ld_post(lev_p)
        k.set(nxt, ph + inc)
        k.set(ph_w, nxt - k.float(k.trunc(nxt)))
        k.set(arg, ph_w + fb * z + bias)
        k.set(frac, arg - k.float(k.trunc(arg)))
        k.set(sv, k.ldx(sine, k.trunc(frac * nf) & mask))
        k.st_post(dst, sv * lev)
        k.set(z, sv)
        k.set(ph, ph_w)


def emit_levels(k, fen, ven, base, base_vol, ninc, fen_c, ven_c, inc_p, lev_p, tracking, hz_scale):
    """Fill the 32 increments and levels for modulator 1. fen and ven decay here."""
    zero = k.f(0.0)
    one = k.f(1.0)
    with k.loop(C.BLOCK):
        if tracking:
            inc = ninc * k.max(base + fen, zero)
        else:
            inc = k.max(base + fen, zero) * hz_scale
        k.st_post(inc_p, inc)
        k.set(fen, fen * fen_c)
        lev = k.min(k.max(base_vol + ven, zero), one)
        k.st_post(lev_p, lev)
        k.set(ven, ven * ven_c)


def emit_carrier(k, sine, n, ph, inc, gain, src, dst, g=None, h=None):
    """Carrier. g and h apply the TONE block; leave them out on FM+DYNAMIC."""
    mask = k.i(n - 1)
    nf = k.f(float(n))
    bias = k.f(C.PHASE_BIAS)
    beta = k.f(C.BETA)
    dlim = k.f(C.DEV_CLIP)
    tlim = k.f(C.TONE_CLIP)
    nxt = k.var('f', 0.0)
    ph_w = k.var('f', 0.0)
    arg = k.var('f', 0.0)
    frac = k.var('f', 0.0)
    sv = k.var('f', 0.0)
    y = k.var('f', 0.0)
    with k.loop(C.BLOCK):
        m = k.ld_post(src)
        if g is None:
            dev = k.clip(m * beta, dlim)
        else:
            k.set(y, k.clip(m * g, tlim))
            y2 = y * y
            k.set(y, k.clip(y + (h * y2) * y, tlim))
            dev = k.clip(y * beta, dlim)
        k.set(nxt, ph + inc)
        k.set(ph_w, nxt - k.float(k.trunc(nxt)))
        k.set(arg, ph_w + dev + bias)
        k.set(frac, arg - k.float(k.trunc(arg)))
        k.set(sv, k.ldx(sine, k.trunc(frac * nf) & mask))
        k.st_post(dst, k.clip(sv * gain, gain))
        k.set(ph, ph_w)


def load_f(k, st, off, name=None):
    return k.var('f', k.ld(st, off, 'f'), name)


def load_knob(k, st, index):
    p = k.var('i', k.ld(st, C.W_P0 + index, 'i'))
    with k.if_(p < 0):
        k.set(p, 0)
    with k.if_(p > 127):
        k.set(p, 127)
    return p


def take(k, tab, word_off, index):
    """One table value. The pointer dies immediately so it does not crowd I0–I3."""
    return k.ldx(k.ptr(tab + (word_off * 4)), index)


def buf_ptr(k, st_i, word_off):
    return k.ptr(st_i + (word_off * 4))


def zero_buf(k, buf):
    z = k.f(0.0)
    p = k.ptr(k.int_of(buf))
    with k.loop(C.BLOCK):
        k.st_post(p, z)
