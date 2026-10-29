"""Reference renderer. Same laws as the SHARC kernel, in ordinary Python.

The kernel is float32 and this file is float64, both reading the same
float32 cycles. Tests allow a small gap between the two.
"""

from __future__ import annotations

from law import (
    CHRW_MAX_CENTS, INV_SR, MIX_CLIP, UNIW_MAX_CENTS, W_PHASE, clamp_out,
    clamp_raw, ens_morph, exp2_cents, inc_from_hz, level, lfo_sine,
    morph_gain_offset, pch_ratio, pw_duty, pwad_hz, pwrs_on, tune_cents,
    width_cents, wrap01,
)
from tables import N, SINE, SAW, SQUARE, WaveSet


class Voice:
    def __init__(self, nphase: int):
        self.active = 1
        self.note_on = 0
        self.freq = 110.0
        self.gain = 1.0
        self.p = [0] * 8
        self.pwm = 0.0
        self.phase = [0.0] * nphase

    def params(self, *raw):
        for i, v in enumerate(raw):
            self.p[i] = clamp_raw(v)
        return self


def read_cycle(mip, phase: float) -> float:
    x = phase * N
    if x < 0.0:
        x = 0.0
    idx = int(x)                        # toward zero; phase is in [0, 1)
    if idx >= N:
        idx = N - 1
    frac = x - idx
    return mip[idx] + (mip[idx + 1] - mip[idx]) * frac


def _mix(buf, waves: WaveSet, shape: int, pulse_index: int, phase: float,
         inc: float, amp: float, bias: float = 0.0, n: int = 32):
    mips = waves.shape_mips(shape, pulse_index)
    mip = mips[waves.mip_index(inc if inc > 0.0 else 0.0)]
    for i in range(n):
        buf[i] += read_cycle(mip, wrap01(phase + bias)) * amp
        phase = wrap01(phase + inc)
    return phase


def _finish(buf, gain: float):
    out = []
    for s in buf:
        if s > MIX_CLIP:
            s = MIX_CLIP
        elif s < -MIX_CLIP:
            s = -MIX_CLIP
        s *= gain
        out.append(clamp_out(s))
    return out


def _tuned_inc(freq: float, tune_raw: int) -> float:
    return inc_from_hz(freq * exp2_cents(tune_cents(tune_raw)))


def render_saw(voice: Voice, waves: WaveSet):
    """SWAVE-SAW. Eight oscillators: base, unison pair, extended pair, square sub, two sines.

    Appendix A, pp. A-1–A-2. UNIX is limited by UNIL (the extended pair stays
    at or under the unison pair’s level). Extended detune is twice the unison
    distance. Setting every knob to its bottom value leaves the base saw.
    """
    if not voice.active:
        return [0.0] * 32
    p = voice.p
    unil, uniw, unix, subx, sub1, sub2, tune = (p[i] for i in range(7))
    base = _tuned_inc(voice.freq, tune)
    cents = width_cents(uniw, UNIW_MAX_CENTS)
    # "double the UNIW distance" is twice the cents (Appendix A, p. A-1).
    up = exp2_cents(cents)
    down = exp2_cents(-cents)
    up2 = exp2_cents(2.0 * cents)
    down2 = exp2_cents(-2.0 * cents)
    g_uni = level(unil)
    g_ext = min(level(unix), g_uni)
    ph = voice.phase
    buf = [0.0] * 32
    specs = (
        (0, SAW, 0, base, 1.0),
        (1, SAW, 0, base * up, g_uni),
        (2, SAW, 0, base * down, g_uni),
        (3, SAW, 0, base * up2, g_ext),
        (4, SAW, 0, base * down2, g_ext),
        (5, SQUARE, 0, base * 0.5, level(subx)),
        (6, SINE, 0, base * 0.5, level(sub1)),
        (7, SINE, 0, base * 0.25, level(sub2)),
    )
    for i, shape, pidx, inc, amp in specs:
        ph[i] = _mix(buf, waves, shape, pidx, ph[i], inc, amp)
    return _finish(buf, voice.gain)


def render_pulse(voice: Voice, waves: WaveSet):
    """SWAVE-PULSE. Base pulse, unison pair, two sine subs.

    Appendix A, p. A-2. The three pulses share PW. PWAD is the sweep speed
    and PWRS restarts that sweep from PW on a note-on. Duty is chosen once
    per 32-sample block (the table pointer cannot change inside the loop).
    """
    if not voice.active:
        return [0.0] * 32
    p = voice.p
    unil, uniw, sub1, sub2, pw, pwad, pwrs, tune = p
    if voice.note_on and pwrs_on(pwrs):
        voice.pwm = 0.0
    duty = pw_duty(pw)
    hz = pwad_hz(pwad)
    if hz > 0.0:
        duty = duty + 0.5 * lfo_sine(voice.pwm)
        if duty < 1.0 / 32.0:
            duty = 1.0 / 32.0
        elif duty > 1.0 - 1.0 / 32.0:
            duty = 1.0 - 1.0 / 32.0
        voice.pwm = wrap01(voice.pwm + hz * INV_SR * 32.0)
    pidx = waves.nearest_pulse(duty)
    base = _tuned_inc(voice.freq, tune)
    cents = width_cents(uniw, UNIW_MAX_CENTS)
    up = exp2_cents(cents)
    down = exp2_cents(-cents)
    g_uni = level(unil)
    ph = voice.phase
    buf = [0.0] * 32
    specs = (
        (0, 3, pidx, base, 1.0),                 # pulse bank
        (1, 3, pidx, base * up, g_uni),
        (2, 3, pidx, base * down, g_uni),
        (3, SINE, 0, base * 0.5, level(sub1)),
        (4, SINE, 0, base * 0.25, level(sub2)),
    )
    for i, shape, ip, inc, amp in specs:
        ph[i] = _mix(buf, waves, shape, ip, ph[i], inc, amp)
    return _finish(buf, voice.gain)


def render_ens(voice: Voice, waves: WaveSet):
    """SWAVE-ENS. Up to four notes, each a pair of saws.

    Appendix A, p. A-2. Defaults (every PCH off, WAVE at the bottom, PW at
    center, chorus off) are one saw. PCH2..4 add notes. The second saw of
    each pair is what WAVE/PW morph, and what CHRL/CHRW chorus: level is the
    louder of the morph and the chorus, and the pitch drifts only while
    CHRL is up. While CHRL is 0 the second saw stays locked to the phase
    offset that makes the square / spike.
    """
    if not voice.active:
        return [0.0] * 32
    p = voice.p
    ratios = [1.0]
    for raw in (p[0], p[1], p[2]):
        r = pch_ratio(raw)
        ratios.append(0.0 if r is None else r)
    morph = ens_morph(p[3], p[4])
    g_wave, offset = morph_gain_offset(morph)
    g_chr = level(p[5])
    g_b = g_wave if g_wave > g_chr else g_chr
    det_c = width_cents(p[6], CHRW_MAX_CENTS) if p[5] else 0.0
    det = exp2_cents(det_c)
    base = _tuned_inc(voice.freq, p[7])
    ph = voice.phase
    buf = [0.0] * 32
    for n, ratio in enumerate(ratios):
        ia, ib = n * 2, n * 2 + 1
        if ratio == 0.0:
            # Keep the phases put. The kernel takes the same path with a
            # zero increment, which does not move a phase already in [0, 1).
            continue
        inc = base * ratio
        if inc < 0.0:
            inc = 0.0
        elif inc > 0.45:
            inc = 0.45
        inc_b = inc * det
        if inc_b > 0.45:
            inc_b = 0.45
        ph[ia] = _mix(buf, waves, SAW, 0, ph[ia], inc, 1.0)
        ph[ib] = _mix(buf, waves, SAW, 0, ph[ib], inc_b, -g_b, bias=offset)
    return _finish(buf, voice.gain)


# phase-word count, so the hook can size the state block
NPHASE = {'saw': 8, 'pulse': 5, 'ens': 8}


def state_words(nphase: int) -> int:
    return W_PHASE + nphase
