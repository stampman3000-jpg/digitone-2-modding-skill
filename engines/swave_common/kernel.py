"""SHARC kernels for the three SuperWave machines.

One fxdsl source is both the program the assembler emits and the float32
interpreter tests run. Calling convention, matching the stock engine render:

    render(R4 = state, R12 = voice buffer, 32 samples)

The waveform block's byte address is state word W_TAB (the hook writes it).
The kernel clobbers R0–R15, I0–I4 and M4, which is all fxdsl is allowed to
touch. The hook saves whatever the stock caller still needs.

Build-time waveform swap: build_*() reads a WaveSet. The default set is the
Fourier cycles in tables.py. Pass load_waves(path) to bake an external table
into the duty-select constants. The cycles themselves are not immediates;
they live in the data block the hook points W_TAB at.
"""

from __future__ import annotations

import os
import sys

_SCRIPTS = os.path.normpath(os.path.join(
    os.path.dirname(__file__), '..', '..', 'skills', 'digitone-2-modding-skill', 'scripts'))
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

import fxdsl  # noqa: E402
from fxdsl import Kernel  # noqa: E402

from law import (  # noqa: E402
    CHRW_MAX_CENTS, EXP_TERMS, FLAG_NOTE_ON, INV_SR, LN2, MIX_CLIP, OUT_CLIP,
    PWAD_MAX_HZ, PW_EPS, SINE_C, UNIW_MAX_CENTS, W_FLAGS, W_FREQ, W_GAIN,
    W_P0, W_PHASE, W_PWM, W_TAB,
)
from tables import MIPS, N, PULSE, SAW, SINE, SQUARE, STRIDE  # noqa: E402

# L2 code short-word address. Same window dspblocks.L2_CODE_SW uses.
L2_CODE_SW = 0xBC8000


def _neg(k, v):
    # fxdsl's unary minus passes its arguments swapped, so subtract from zero.
    return k.f(0.0) - v


def _exp2_cents(k, cents):
    """2^(cents/1200), EXP_TERMS of e^(cents * ln2 / 1200). Prologue only."""
    x = k.var('f', cents * k.f(LN2 / 1200.0), 'ex')
    term = k.var('f', 1.0, 'et')
    acc = k.var('f', 1.0, 'ea')
    for n in range(1, EXP_TERMS + 1):
        term = k.var('f', (term * x) * k.f(1.0 / n), 'et')
        acc = k.var('f', acc + term, 'ea')
    return acc


def _tune_ratio(k, raw_i):
    d = k.var('f', k.float(raw_i - 64), 'td')
    cents = k.var('f', 0.0, 'tc')
    with k.if_(raw_i <= 64) as br:
        k.set(cents, d * k.f(100.0 / 64.0))
    with br.else_():
        k.set(cents, d * k.f(100.0 / 63.0))
    return _exp2_cents(k, cents)


def _width_cents(k, raw_i, max_cents):
    x = k.float(raw_i) * k.f(1.0 / 127.0)
    return k.var('f', (x * x) * k.f(max_cents), 'wc')


def _level(k, raw_i):
    return k.var('f', k.float(raw_i) * k.f(1.0 / 127.0), 'lv')


def _clamp_inc(k, inc):
    return k.var('f', k.min(k.max(inc, 0.0), 0.45), 'inc')


def _hz_inc(k, freq, ratio):
    return _clamp_inc(k, (freq * ratio) * k.f(INV_SR))


def _pick_mip(k, inc):
    """Brightest mip whose top harmonic is still under Nyquist."""
    from tables import HARM
    half = k.f(0.5)
    mip = k.var('i', MIPS - 1, 'mip')
    chosen = k.var('i', 0, 'mch')
    for i, H in enumerate(HARM):
        with k.if_((inc * k.f(float(H))) < half):
            with k.if_(chosen == 0):
                k.set(mip, i)
                k.set(chosen, 1)
    return mip


def _addr(k, tab_base, word0, slot_i, slot_bytes, mip_i):
    """Byte address of mip `mip_i` in the slot that starts at word0."""
    off_s = k.trunc(k.float(slot_i) * k.f(float(slot_bytes)))
    off_m = k.trunc(k.float(mip_i) * k.f(float(STRIDE * 4)))
    return (tab_base + k.i(word0 * 4)) + off_s + off_m


def _mix(k, buf_base, tab_addr, phase, inc, amp, bias=None):
    nf = k.f(float(N))
    p = k.ptr(buf_base)
    q = k.ptr(buf_base)
    tp = k.ptr(tab_addr)
    with k.loop(32):
        if bias is None:
            ph = phase
        else:
            summed = phase + bias
            ph = k.var('f', summed - k.float(k.trunc(summed)), 'rdb')
        x = k.var('f', ph * nf, 'x')
        idx = k.var('i', k.trunc(x), 'idx')
        frac = x - k.float(idx)
        s0 = k.ldx(tp, idx)
        s1 = k.ldx(tp, idx + 1)
        samp = (s0 + (s1 - s0) * frac) * amp
        acc = k.ld_post(p)
        k.st_post(q, acc + samp)
        nxt = phase + inc
        k.set(phase, nxt - k.float(k.trunc(nxt)))


def _zero(k, buf_base):
    z = k.ptr(buf_base)
    with k.loop(32):
        k.st_post(z, 0.0)


def _scale(k, buf_base, gain):
    p = k.ptr(buf_base)
    q = k.ptr(buf_base)
    lim = k.f(MIX_CLIP)
    huge = k.f(OUT_CLIP)
    with k.loop(32):
        y = k.var('f', k.clip(k.ld_post(p), lim), 'y')
        k.st_post(q, k.clip(y * gain, huge))


def _raw(k, st, i):
    return k.var('i', k.ld(st, W_P0 + i, 'i'), f'p{i}')


def _prologue(k):
    """Idle early-out, then a silent buffer.

    Gain is left in memory and reloaded at the end so it does not occupy a
    register through every oscillator. Knobs are loaded at the point of use
    for the same reason: the sample loop only has 16 data registers.
    """
    st, buf = k['st'], k['buf']
    buf_base = k.var('i', k.int_of(buf), 'bb')
    flags = k.ld(st, W_FLAGS, 'i')
    with k.if_((flags & 1) == 0):
        _zero(k, buf_base)
        k.ret()
    _zero(k, buf_base)
    freq = k.var('f', k.ld(st, W_FREQ), 'freq')
    tab = k.var('i', k.ld(st, W_TAB, 'i'), 'tab')
    return st, buf_base, tab, freq, flags


def _osc(k, st, buf_base, tab, phase_i, word0, slot_i, slot_bytes, inc, amp, bias=None):
    phase = k.var('f', k.ld(st, W_PHASE + phase_i), 'ph')
    mip = _pick_mip(k, inc)
    addr = _addr(k, tab, word0, slot_i, slot_bytes, mip)
    _mix(k, buf_base, addr, phase, inc, amp, bias)
    k.st(st, W_PHASE + phase_i, phase)


def build_saw(waves):
    k = Kernel('swave_saw', inputs={'st': 'I0', 'buf': 'I1'})
    st, buf_base, tab, freq, _flags = _prologue(k)
    base = _hz_inc(k, freq, _tune_ratio(k, _raw(k, st, 6)))
    zero = k.i(0)
    saw_w = waves.shape_word(SAW)
    # Base saw, then each detuned pair. Ratios are computed immediately
    # before the oscillators that use them so the sample loop can allocate.
    _osc(k, st, buf_base, tab, 0, saw_w, zero, 0, base, k.f(1.0))
    cents = _width_cents(k, _raw(k, st, 1), UNIW_MAX_CENTS)
    g_uni = _level(k, _raw(k, st, 0))
    _osc(k, st, buf_base, tab, 1, saw_w, zero, 0, _clamp_inc(k, base * _exp2_cents(k, cents)), g_uni)
    _osc(k, st, buf_base, tab, 2, saw_w, zero, 0, _clamp_inc(k, base * _exp2_cents(k, _neg(k, cents))), g_uni)
    g_ext = k.var('f', k.min(_level(k, _raw(k, st, 2)), g_uni), 'gext')
    two_c = k.var('f', cents * k.f(2.0), 'c2')
    _osc(k, st, buf_base, tab, 3, saw_w, zero, 0, _clamp_inc(k, base * _exp2_cents(k, two_c)), g_ext)
    _osc(k, st, buf_base, tab, 4, saw_w, zero, 0, _clamp_inc(k, base * _exp2_cents(k, _neg(k, two_c))), g_ext)
    _osc(k, st, buf_base, tab, 5, waves.shape_word(SQUARE), zero, 0,
         _clamp_inc(k, base * k.f(0.5)), _level(k, _raw(k, st, 3)))
    _osc(k, st, buf_base, tab, 6, waves.shape_word(SINE), zero, 0,
         _clamp_inc(k, base * k.f(0.5)), _level(k, _raw(k, st, 4)))
    _osc(k, st, buf_base, tab, 7, waves.shape_word(SINE), zero, 0,
         _clamp_inc(k, base * k.f(0.25)), _level(k, _raw(k, st, 5)))
    _scale(k, buf_base, k.ld(st, W_GAIN))
    return k


def _pw_duty(k, raw_i):
    d = k.f(0.5) + k.float(raw_i - 64) * k.f(1.0 / 128.0)
    return k.var('f', k.min(k.max(d, PW_EPS), 1.0 - PW_EPS), 'duty')


def _lfo_sine(k, phase):
    u = phase - k.float(k.trunc(phase + k.f(0.5)))
    x = k.var('f', u * k.f(2.0), 'sx')
    x2 = k.var('f', x * x, 'sx2')
    c1, c3, c5, c7, c9 = SINE_C
    return x * (k.f(c1) + x2 * (k.f(c3) + x2 * (k.f(c5) + x2 * (k.f(c7) + x2 * k.f(c9)))))


def _nearest_duty(k, duty, duties):
    idx = k.var('i', 0, 'di')
    for i in range(len(duties) - 1):
        mid = 0.5 * (duties[i] + duties[i + 1])
        with k.if_(duty >= k.f(mid)):
            k.set(idx, i + 1)
    return idx


def build_pulse(waves):
    k = Kernel('swave_pulse', inputs={'st': 'I0', 'buf': 'I1'})
    st, buf_base, tab, freq, flags = _prologue(k)
    pwm = k.var('f', k.ld(st, W_PWM), 'pwm')
    note = flags & FLAG_NOTE_ON
    pwrs = _raw(k, st, 6)
    with k.if_(note != 0):
        with k.if_(pwrs != 0):
            k.set(pwm, 0.0)
    duty = _pw_duty(k, _raw(k, st, 4))
    pwad = _raw(k, st, 5)
    with k.if_(pwad != 0):
        sweep = _lfo_sine(k, pwm) * k.f(0.5)
        moved = duty + sweep
        k.set(duty, k.min(k.max(moved, PW_EPS), 1.0 - PW_EPS))
        x = k.float(pwad) * k.f(1.0 / 127.0)
        hz = k.var('f', (x * x) * k.f(PWAD_MAX_HZ), 'hz')
        step = k.var('f', pwm + hz * k.f(INV_SR * 32.0), 'st')
        k.set(pwm, step - k.float(k.trunc(step)))
    k.st(st, W_PWM, pwm)
    slot = _nearest_duty(k, duty, waves.duties)
    base = _hz_inc(k, freq, _tune_ratio(k, _raw(k, st, 7)))
    word0 = waves.shape_word(PULSE, 0)
    slot_bytes = MIPS * STRIDE * 4
    zero = k.i(0)
    _osc(k, st, buf_base, tab, 0, word0, slot, slot_bytes, base, k.f(1.0))
    cents = _width_cents(k, _raw(k, st, 1), UNIW_MAX_CENTS)
    g_uni = _level(k, _raw(k, st, 0))
    _osc(k, st, buf_base, tab, 1, word0, slot, slot_bytes,
         _clamp_inc(k, base * _exp2_cents(k, cents)), g_uni)
    _osc(k, st, buf_base, tab, 2, word0, slot, slot_bytes,
         _clamp_inc(k, base * _exp2_cents(k, _neg(k, cents))), g_uni)
    sine_w = waves.shape_word(SINE)
    _osc(k, st, buf_base, tab, 3, sine_w, zero, 0,
         _clamp_inc(k, base * k.f(0.5)), _level(k, _raw(k, st, 2)))
    _osc(k, st, buf_base, tab, 4, sine_w, zero, 0,
         _clamp_inc(k, base * k.f(0.25)), _level(k, _raw(k, st, 3)))
    _scale(k, buf_base, k.ld(st, W_GAIN))
    return k


def _morph(k, wave_i, pw_i):
    w = k.float(wave_i) * k.f(1.0 / 127.0)
    p = k.float(pw_i - 64) * k.f(1.0 / 64.0)
    m = k.var('f', k.min(k.max(w * k.f(0.5) + p * k.f(0.5), 0.0), 1.0), 'morph')
    g = k.var('f', 0.0, 'mg')
    off = k.var('f', 0.5, 'off')
    with k.if_(m <= 0.5) as br:
        k.set(g, m * k.f(2.0))
    with br.else_():
        t = (m - k.f(0.5)) * k.f(2.0)
        k.set(g, 1.0)
        k.set(off, k.f(0.5) + (k.f(PW_EPS) - k.f(0.5)) * t)
    return g, off


def _pch(k, tab, raw_i):
    """Frequency ratio, or 0 when the pitch is OFF (raw 0)."""
    ratio = k.var('f', 0.0, 'pch')
    with k.if_(raw_i == 0) as off:
        k.set(ratio, 0.0)
    with off.else_():
        with k.if_(raw_i >= 124) as just:
            k.set(ratio, k.ldx(k.ptr(tab), (raw_i - 124) + 64))
        with just.else_():
            with k.if_(raw_i <= 63) as up:
                k.set(ratio, k.ldx(k.ptr(tab), raw_i))
            with up.else_():
                k.set(ratio, k.ldx(k.ptr(tab), (raw_i - 63) + 68))
    return ratio


def build_ens(waves):
    k = Kernel('swave_ens', inputs={'st': 'I0', 'buf': 'I1'})
    st, buf_base, tab, freq, _flags = _prologue(k)
    base = _hz_inc(k, freq, _tune_ratio(k, _raw(k, st, 7)))
    g_wave, offset = _morph(k, _raw(k, st, 3), _raw(k, st, 4))
    chrl = _raw(k, st, 5)
    g_b = k.var('f', k.max(g_wave, _level(k, chrl)), 'gb')
    det_c = k.var('f', 0.0, 'detc')
    with k.if_(chrl != 0):
        k.set(det_c, _width_cents(k, _raw(k, st, 6), CHRW_MAX_CENTS))
    det = _exp2_cents(k, det_c)
    neg_b = k.var('f', _neg(k, g_b), 'negb')
    word0 = waves.shape_word(SAW)
    for n in range(4):
        ratio = k.f(1.0) if n == 0 else _pch(k, tab, _raw(k, st, n - 1))
        inc = _clamp_inc(k, base * ratio)
        amp_a = k.var('f', 1.0, 'aa')
        with k.if_(ratio == 0.0):
            k.set(amp_a, 0.0)
            k.set(inc, 0.0)
        _osc(k, st, buf_base, tab, n * 2, word0, k.i(0), 0, inc, amp_a)
        inc_b = _clamp_inc(k, inc * det)
        amp_b = k.var('f', neg_b, 'ab')
        with k.if_(ratio == 0.0):
            k.set(amp_b, 0.0)
            k.set(inc_b, 0.0)
        _osc(k, st, buf_base, tab, n * 2 + 1, word0, k.i(0), 0, inc_b, amp_b, bias=offset)
    _scale(k, buf_base, k.ld(st, W_GAIN))
    return k


def assemble(k, entry_name: str):
    """Entry that turns the C ABI (R4 state, R12 buffer) into the kernel's I0/I1."""
    import sasm
    from sasm import NOP48, c2, mv_i_from_r2
    a = sasm.Asm(L2_CODE_SW)
    a.label(entry_name)
    a(c2('PASS', 2, 4))
    a(mv_i_from_r2(0))
    a(c2('PASS', 2, 12))
    a(mv_i_from_r2(1))
    k.emit(a)
    for _ in range(12):
        a((NOP48, 'NOP'))
    code, texts = a.assemble()
    return code, texts


def executed_cost(code: bytes):
    """Instructions a sounding voice runs, loops counted 32 (or whatever) times.

    The idle early-out is not on this path: the first conditional branch is
    taken (voice is active) and the zero-and-return loop is skipped. Later
    loops all run. Trailing NOP padding after the final RTS does not run.
    """
    import struct
    import visa
    words = struct.unpack('<' + 'H' * (len(code) // 2), code)
    pc = 0
    ins = []
    while pc < len(words):
        d = visa.decode(words[pc:pc + 3], L2_CODE_SW + pc)
        ins.append(d)
        pc += d.size
    # Address of the first branch target: the active path.
    import re
    first_br = next(i for i in ins if 'JUMP' in i.text and i.kind in ('jump', 'cjump'))
    m = re.search(r'JUMP (0x[0-9a-f]+)', first_br.text)
    land = int(m.group(1), 16)
    by = {i.sw: n for n, i in enumerate(ins)}
    n = by[land]
    cost = 0
    # Count the branch itself and the straight-line ops before it too
    # (they execute whether or not the voice is idle).
    head = ins.index(first_br) + 1
    cost += head
    while n < len(ins):
        i = ins[n]
        if i.kind == 'ret' or i.text.startswith('RTS'):
            cost += 1
            break
        m = re.match(r'LCNTR = (\d+), DO (0x[0-9a-f]+)', i.text)
        if m:
            cnt = int(m.group(1))
            end = int(m.group(2), 16)
            j = n + 1
            body = 0
            while j < len(ins) and ins[j].sw <= end:
                body += 1
                j += 1
            cost += 1 + cnt * body
            n = j
            continue
        cost += 1
        n += 1
    bodies = []
    for i in ins:
        m = re.match(r'LCNTR = (\d+), DO (0x[0-9a-f]+)', i.text)
        if m:
            bodies.append(int(m.group(1)))
    return {'executed': cost, 'static': len(ins), 'loops': len(bodies), 'ins': ins}


def run_voice(k, voice, waves):
    """Run one block. Updates voice.phase and voice.pwm. Returns 32 floats."""
    from fxdsl import DictMem, u_of
    mem = DictMem()
    st = 0x20098000
    buf = 0x2009C000
    tab = 0x20100000
    for i, w in enumerate(waves.flat_words()):
        mem.w(tab + 4 * i, u_of(float(w)))
    flags = (1 if voice.active else 0) | (2 if voice.note_on else 0)
    mem.w(st + 4 * W_FLAGS, flags)
    mem.w(st + 4 * W_FREQ, u_of(float(voice.freq)))
    mem.w(st + 4 * W_GAIN, u_of(float(voice.gain)))
    for i, raw in enumerate(voice.p):
        mem.w(st + 4 * (W_P0 + i), int(raw) & 0xFFFFFFFF)
    mem.w(st + 4 * W_TAB, tab & 0xFFFFFFFF)
    mem.w(st + 4 * W_PWM, u_of(float(voice.pwm)))
    for i, ph in enumerate(voice.phase):
        mem.w(st + 4 * (W_PHASE + i), u_of(float(ph)))
    k.run(mem, {'st': st, 'buf': buf})
    out = [mem.rf(buf + 4 * i) for i in range(32)]
    for i in range(len(voice.phase)):
        voice.phase[i] = mem.rf(st + 4 * (W_PHASE + i))
    voice.pwm = mem.rf(st + 4 * W_PWM)
    return out
