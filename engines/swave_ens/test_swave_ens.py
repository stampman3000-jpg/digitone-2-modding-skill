"""SWAVE-ENS tests.

    python3 engines/swave_ens/test_swave_ens.py
"""

from __future__ import annotations

import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'swave_common'))
sys.path.insert(0, HERE)

import law
import model
import tables
from osc import Voice


def _goertzel(samples, freq):
    w = 2 * math.pi * freq / law.SR
    c = 2 * math.cos(w)
    s1 = s2 = 0.0
    for x in samples:
        s0 = x + c * s1 - s2
        s2, s1 = s1, s0
    return max(0.0, s1 * s1 + s2 * s2 - c * s1 * s2)


def _blocks(voice, waves, n=40):
    buf = []
    for i in range(n):
        if i:
            voice.note_on = 0
        buf.extend(model.render(voice, waves))
    return buf


def test_defaults_and_chord():
    w = tables.default_waves()
    root = 130.8128                          # C3
    single = Voice(model.N_PHASE)
    single.freq = root
    single.params(0, 0, 0, 0, 64, 0, 0, 64)  # PCH off, PW center, no chorus
    alone = _blocks(single, w)
    # Manual example: PCH2 = 4, PCH3 = 7, PCH4 = OFF → C, E, G.
    chord = Voice(model.N_PHASE)
    chord.freq = root
    chord.params(4, 7, 0, 0, 64, 0, 0, 64)
    many = _blocks(chord, w)
    fifth = root * law.pch_ratio(7)
    third = root * law.pch_ratio(4)
    # The fifth is not a harmonic of the root, so a single saw is quiet there.
    assert _goertzel(many, fifth) > _goertzel(alone, fifth) * 5
    assert _goertzel(many, third) > _goertzel(alone, third) * 5
    # Just 3/2 is raw 127. It is not the tempered fifth (raw 7); the manual
    # lists both. Two cents is too close for a short FFT, so compare ratios
    # and that the renders actually diverge.
    assert abs(law.pch_ratio(127) - 1.5) < 1e-6
    assert law.pch_ratio(7) != law.pch_ratio(127)
    just = Voice(model.N_PHASE)
    just.freq = root
    just.params(127, 0, 0, 0, 64, 0, 0, 64)
    tempered = Voice(model.N_PHASE)
    tempered.freq = root
    tempered.params(7, 0, 0, 0, 64, 0, 0, 64)
    assert max(abs(x - y) for x, y in zip(_blocks(just, w, 80), _blocks(tempered, w, 80))) > 1e-3
    # Chorus on a saw adds a second, moving voice: not a copy of the dry saw.
    dry = Voice(model.N_PHASE)
    dry.freq = root
    dry.params(0, 0, 0, 0, 64, 0, 0, 64)
    wet = Voice(model.N_PHASE)
    wet.freq = root
    wet.params(0, 0, 0, 0, 64, 100, 127, 64)
    d, c = _blocks(dry, w, 20), _blocks(wet, w, 20)
    assert max(abs(x - y) for x, y in zip(d, c)) > 0.05
    print('ensemble laws ok')


def test_kernel():
    try:
        import sharc
    except Exception as exc:
        print(f'SKIP sharc kernel ({exc})')
        return
    w = tables.default_waves()
    kern, _code, _texts, info, _waves = sharc.build(w)
    worst = 0.0
    presets = [
        (130.8, (0, 0, 0, 0, 64, 0, 0, 64)),
        (130.8, (4, 7, 0, 0, 64, 0, 0, 64)),
        (110.0, (127, 125, 126, 90, 100, 80, 60, 64)),
        (80.0, (12, 64, 0, 127, 0, 0, 0, 40)),   # includes a downward semitone
    ]
    for freq, params in presets:
        ref_v, dsp_v = Voice(model.N_PHASE), Voice(model.N_PHASE)
        for v in (ref_v, dsp_v):
            v.freq = freq
            v.params(*params)
        for _ in range(3):
            ref = model.render(ref_v, w)
            got = sharc.run_voice(kern, dsp_v, w)
            worst = max(worst, max(abs(a - b) for a, b in zip(ref, got)))
            assert all(math.isfinite(x) for x in got)
    assert worst < 2e-3, worst
    print(f'kernel ok  max abs {worst:.3e}  {info["executed"]} instr/voice')


def test_stock_sim():
    snap = os.path.expanduser('~/dn2-workspace/snap/boot_stock.snap.gz')
    if not os.path.exists(snap):
        print('SKIP whole-DSP sim (no stock OS snapshot)')
        return
    print('SKIP whole-DSP sim (not hooked into section 7 yet)')


if __name__ == '__main__':
    test_defaults_and_chord()
    test_kernel()
    test_stock_sim()
    print('OK')
