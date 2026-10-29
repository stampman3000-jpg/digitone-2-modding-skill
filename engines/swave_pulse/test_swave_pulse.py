"""SWAVE-PULSE tests. Same skip rules as the saw test.

    python3 engines/swave_pulse/test_swave_pulse.py
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
    return s1 * s1 + s2 * s2 - c * s1 * s2


def test_square_and_spike():
    w = tables.default_waves()
    v = Voice(model.N_PHASE)
    v.freq = 110
    v.params(0, 0, 0, 0, 64, 0, 0, 64)          # PW center = square
    buf = []
    for _ in range(30):
        buf.extend(model.render(v, w))
    fund = _goertzel(buf, 110)
    second = _goertzel(buf, 220)
    third = _goertzel(buf, 330)
    assert fund > second * 8, (fund, second)
    assert third > second, (third, second)
    spike = Voice(model.N_PHASE)
    spike.freq = 110
    spike.params(0, 0, 0, 0, 0, 0, 0, 64)       # PW hard down = spike
    s = []
    for _ in range(10):
        s.extend(model.render(spike, w))
    # A spike is not the same waveform as the square.
    assert max(abs(a - b) for a, b in zip(buf, s)) > 0.2
    # PWAD 0 does not move the sweep. PWRS restarts it.
    assert law.pwad_hz(0) == 0
    moving = Voice(model.N_PHASE)
    moving.freq = 55
    moving.note_on = 1
    moving.pwm = 0.25
    moving.params(0, 0, 0, 0, 64, 127, 127, 64)
    model.render(moving, w)
    assert moving.pwm < 0.25 or moving.note_on          # reset to 0, then advanced one block
    assert moving.pwm != 0.25
    print('pulse shape ok')


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
        (110, (0, 0, 0, 0, 64, 0, 0, 64), 0, 0.0),
        (80, (90, 30, 40, 20, 20, 80, 1, 70), 1, 0.3),
        (200, (0, 0, 0, 0, 127, 40, 0, 64), 0, 0.1),
        (65, (127, 10, 0, 127, 0, 0, 0, 0), 0, 0.0),
    ]
    for freq, params, note, pwm in presets:
        ref_v, dsp_v = Voice(model.N_PHASE), Voice(model.N_PHASE)
        for v in (ref_v, dsp_v):
            v.freq = freq
            v.note_on = note
            v.pwm = pwm
            v.params(*params)
        for block in range(4):
            if block:
                ref_v.note_on = dsp_v.note_on = 0
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
    test_square_and_spike()
    test_kernel()
    test_stock_sim()
    print('OK')
