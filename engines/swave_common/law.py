"""SuperWave parameter laws.

Numbers and behaviour follow Elektron’s Monomachine User’s Manual, OS 1.32
(https://www.elektron.se/wp-content/uploads/2024/09/monomachine_manual_OS1.32.pdf).

The manual’s SYNTHESIS page shows up to eight parameters, one per DATA ENTRY
knob (p. 10, “THE LCD USER INTERFACE”; p. 25, “PARAMETER EDITING”). Appendix A
lists each machine’s parameters in that knob order. Where a machine has fewer
than eight, the leftover knob does nothing (p. 10).

Every DATA ENTRY value is the MIDI 0..127 control (Appendix B, p. B-2: synth
parameters 1..8 are CC 48..55). Bipolar knobs use the same encoding the manual
prints for PAN: raw 0 is −64, raw 64 is 0, raw 127 is +63 (p. 29).
"""

from __future__ import annotations

import struct

SR = 48000.0
INV_SR = 1.0 / SR
N_PARAMS = 8

# A full stack of band-limited cycles can peak a little over ±1 each.
# Clip the mix here, then apply out_gain, then clip again so a huge gain
# cannot run off to infinity. Floats saturate; they are not allowed to wrap.
MIX_CLIP = 12.0
OUT_CLIP = 1.0e5

# Unison distance at UNIW = 127, in cents. The manual describes the distance
# but not the cents (Appendix A, p. A-1). Squared so the lower half of the
# knob stays a chorus. Double this distance for the extended pair (“2×UNIW”).
UNIW_MAX_CENTS = 700.0

# Ensemble chorus distance at CHRW = 127. Tighter than unison: this is a
# chorus, not a second chord. Same squared law.
CHRW_MAX_CENTS = 40.0

# PWAD = 127 sweeps this many cycles per second. 0 stops the sweep
# (Appendix A, p. A-2). The sweep is a sine and is updated once per
# 32-sample block.
PWAD_MAX_HZ = 20.0

# Narrowest pulse the PW knob reaches. Raw 0 and raw 127 land on this,
# which is “spike”, not digital silence (Appendix A, p. A-2).
PW_EPS = 1.0 / 32.0

# Eight-term exp for 2^(cents/1200). Accurate to well under 0.01 cent
# across the detune range we use (±1400 cents). The SHARC prologue uses
# the same term count.
EXP_TERMS = 8
LN2 = 0.6931471805599453

# Equal temperament, float32 bits of 2^(n/12) for n = 0..63.
# Frozen so CPython and PyPy bake the same SHARC constants.
_SEMI_BITS = (
    0x3F800000, 0x3F879C7D, 0x3F8FACD6, 0x3F9837F0, 0x3FA14518, 0x3FAADC08, 0x3FB504F3, 0x3FBFC887,
    0x3FCB2FF5, 0x3FD744FD, 0x3FE411F0, 0x3FF1A1BF, 0x40000000, 0x40079C7D, 0x400FACD6, 0x401837F0,
    0x40214518, 0x402ADC08, 0x403504F3, 0x403FC887, 0x404B2FF5, 0x405744FD, 0x406411F0, 0x4071A1BF,
    0x40800000, 0x40879C7D, 0x408FACD6, 0x409837F0, 0x40A14518, 0x40AADC08, 0x40B504F3, 0x40BFC887,
    0x40CB2FF5, 0x40D744FD, 0x40E411F0, 0x40F1A1BF, 0x41000000, 0x41079C7D, 0x410FACD6, 0x411837F0,
    0x41214518, 0x412ADC08, 0x413504F3, 0x413FC887, 0x414B2FF5, 0x415744FD, 0x416411F0, 0x4171A1BF,
    0x41800000, 0x41879C7D, 0x418FACD6, 0x419837F0, 0x41A14518, 0x41AADC08, 0x41B504F3, 0x41BFC887,
    0x41CB2FF5, 0x41D744FD, 0x41E411F0, 0x41F1A1BF, 0x42000000, 0x42079C7D, 0x420FACD6, 0x421837F0,
)
SEMI_RATIO = [struct.unpack('<f', struct.pack('<I', b))[0] for b in _SEMI_BITS]
# float32 reciprocal, so a downward semitone is a table load on the DSP
# rather than a divide. SEMI_DOWN[n] = 1/2^(n/12).
SEMI_DOWN = [struct.unpack('<f', struct.pack('<f', 1.0 / r))[0] for r in SEMI_RATIO]

# Just-intonation ratios named in Appendix A, p. A-2. Knob positions are
# not printed in the manual; they sit at the top of the 0..127 range so
# the low integers stay equal-tempered semitones (the manual’s “PCH2 = 4”).
JUST_AT = {124: 6.0 / 5.0, 125: 5.0 / 4.0, 126: 4.0 / 3.0, 127: 3.0 / 2.0}
JUST_RATIO = {i: struct.unpack('<f', struct.pack('<f', v))[0] for i, v in JUST_AT.items()}

# Sine used only for the pulse-width LFO (not the audio oscillator).
# sin(pi*x) on x in [-1, 1], max error about 3e-5.
SINE_C = (3.14158412, -5.16724043, 2.5460302, -0.586655756, 0.066314934)

# New Digitone II machine ids. Stock ids 0..4 (FM TONE, WAVETONE, FM DRUM,
# SWARMER, MIDI) are never used.
MACHINE_SAW = 5
MACHINE_PULSE = 6
MACHINE_ENS = 7

# Voice state words. The hook fills these; the engine does not read a stock
# machine’s parameter block.
W_FLAGS, W_FREQ, W_GAIN = 0, 1, 2
W_P0 = 3                 # eight raw knobs, words 3..10
W_TAB = 11               # byte address of the waveform block (int)
W_PWM = 12               # pulse-sweep phase, 0..1
W_PHASE = 13             # first oscillator phase

FLAG_ACTIVE = 1
FLAG_NOTE_ON = 2

# Word where the waveform cycles start inside the table block:
#   0..63    2^(n/12)
#   64..67   just ratios 6/5, 5/4, 4/3, 3/2
#   68..131  2^(-n/12)
WAVE_WORD = 132


def f32(x: float) -> float:
    return struct.unpack('<f', struct.pack('<f', float(x)))[0]


def clamp_raw(v) -> int:
    v = int(v)
    if v < 0:
        return 0
    if v > 127:
        return 127
    return v


def tune_cents(raw) -> float:
    """±100 cents. Manual p. 25: “fine pitch tuning of 100 cents up or down.”

    Raw 0 → −100, raw 64 → 0, raw 127 → +100. The positive side has 63
    steps because the knob’s top value is +63 in the usual bipolar display.
    """
    raw = clamp_raw(raw)
    if raw <= 64:
        return (raw - 64) * (100.0 / 64.0)
    return (raw - 64) * (100.0 / 63.0)


def exp2_cents(cents: float) -> float:
    """2^(cents/1200) with EXP_TERMS. Same series the DSP prologue runs."""
    x = (cents / 1200.0) * LN2
    term = 1.0
    acc = 1.0
    for n in range(1, EXP_TERMS + 1):
        term *= x / n
        acc += term
    return acc


def level(raw) -> float:
    """Linear amplitude. 0 is silent, 127 is full. An A/B may want a curve."""
    return clamp_raw(raw) / 127.0


def width_cents(raw, max_cents: float) -> float:
    x = clamp_raw(raw) / 127.0
    return x * x * max_cents


def pw_duty(raw) -> float:
    """Pulse width. Center raw 64 (displayed 0) is a square.

    Appendix A, p. A-2: “The center value (0) … gives a square form, and the
    higher and lower settings turn the waveform towards a spike form.”
    """
    raw = clamp_raw(raw)
    d = 0.5 + (raw - 64) / 128.0
    if d < PW_EPS:
        return PW_EPS
    if d > 1.0 - PW_EPS:
        return 1.0 - PW_EPS
    return d


def pwad_hz(raw) -> float:
    """0 stops the sweep. Higher values speed it up (squared)."""
    if clamp_raw(raw) == 0:
        return 0.0
    x = clamp_raw(raw) / 127.0
    return x * x * PWAD_MAX_HZ


def pwrs_on(raw) -> bool:
    """0 is off. Any other value restarts the sweep on a note-on.

    The manual only says “when activated” (Appendix A, p. A-2).
    """
    return clamp_raw(raw) != 0


def pch_ratio(raw):
    """Frequency ratio for one Ensemble pitch, or None when the voice is off.

    Appendix A, p. A-2: PCH2 = 4 and PCH3 = 7 with C-4 sounding give E-4 and
    G-4, and PCH4 = OFF adds nothing. 6/5, 5/4, 4/3 and 3/2 are the named
    just intervals.

    Raw 0 is OFF. Raw 1..63 are +1..+63 equal-tempered semitones, so the
    number the manual writes is the knob value. Raw 64..123 are −1..−60
    semitones. Raw 124..127 are the four just ratios, in the manual’s order.
    """
    raw = clamp_raw(raw)
    if raw == 0:
        return None
    if raw in JUST_RATIO:
        return JUST_RATIO[raw]
    if raw <= 63:
        return SEMI_RATIO[raw]
    return SEMI_DOWN[raw - 63]          # 64 → −1 semitone, 123 → −60


def ens_morph(wave, pw) -> float:
    """0 = saw, 0.5 = square, 1 = spike.

    Appendix A, p. A-2: with PW at its center, WAVE runs from saw to square.
    Moving PW off center mutates that further, toward a spike or back to a saw.
    """
    w = clamp_raw(wave) / 127.0
    p = (clamp_raw(pw) - 64) / 64.0
    m = w * 0.5 + p * 0.5
    if m < 0.0:
        return 0.0
    if m > 1.0:
        return 1.0
    return m


def morph_gain_offset(morph: float):
    """Second saw’s gain and phase offset.

    Two saws at the same pitch, the second subtracted and shifted, run from
    a single saw (gain 0) through a square (gain 1, offset 1/2) to a spike
    (gain 1, offset = PW_EPS). That is the manual’s “two saw tooth
    oscillators” (Appendix A, p. A-2).
    """
    if morph <= 0.5:
        return morph * 2.0, 0.5
    t = (morph - 0.5) * 2.0
    return 1.0, 0.5 + (PW_EPS - 0.5) * t


def lfo_sine(phase: float) -> float:
    """sin(2π phase), phase in [0, 1). Prologue only."""
    p = phase - math_trunc(phase)
    u = p - math_trunc(p + 0.5)          # [-0.5, 0.5]
    x = u * 2.0
    x2 = x * x
    c1, c3, c5, c7, c9 = SINE_C
    return x * (c1 + x2 * (c3 + x2 * (c5 + x2 * (c7 + x2 * c9))))


def math_trunc(x: float) -> float:
    """Toward zero, matching the SHARC TRUNC used in the phase wrap."""
    if x >= 0.0:
        return float(int(x))
    return -float(int(-x))


def wrap01(phase: float) -> float:
    return phase - math_trunc(phase)


def clamp_mix(x: float) -> float:
    if x > MIX_CLIP:
        return MIX_CLIP
    if x < -MIX_CLIP:
        return -MIX_CLIP
    return x


def clamp_out(x: float) -> float:
    if x > OUT_CLIP:
        return OUT_CLIP
    if x < -OUT_CLIP:
        return -OUT_CLIP
    return x


def inc_from_hz(hz: float) -> float:
    if hz != hz or hz <= 0.0:            # NaN or silent
        return 0.0
    inc = hz * INV_SR
    if inc > 0.45:
        return 0.45
    return inc
