"""SWAVE-SAW: reference behaviour, and the SHARC kernel against that reference.

The kernel runs in fxdsl's float32 interpreter. That does not need a Digitone
OS image. If the DSP tools are not installed, that part is skipped.

    python3 engines/swave_saw/test_swave_saw.py
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


def test_base_saw_and_unix_limit():
    w = tables.default_waves()
    bare = Voice(model.N_PHASE)
    bare.freq = 110
    bare.params(0, 0, 0, 0, 0, 0, 64)
    a = model.render(bare, w)
    # UNIX with UNIL at 0 must not add the outer pair (manual: UNIX is limited by UNIL).
    blocked = Voice(model.N_PHASE)
    blocked.freq = 110
    blocked.phase = [0.0] * model.N_PHASE
    blocked.params(0, 80, 127, 0, 0, 0, 64)
    b = model.render(blocked, w)
    assert max(abs(x - y) for x, y in zip(a, b)) < 1e-6
    # Unison at full level is a different, louder waveform.
    wide = Voice(model.N_PHASE)
    wide.freq = 110
    wide.params(127, 64, 127, 0, 0, 0, 64)
    c = model.render(wide, w)
    assert max(abs(x) for x in c) > max(abs(x) for x in a) * 1.5
    # Subs add energy below the saw.
    assert max(abs(x) for x in a) > 0.2
    assert all(math.isfinite(x) for x in c)
    print('saw laws ok')


def test_tune_moves_pitch():
    w = tables.default_waves()

    def freq_of(tune):
        v = Voice(model.N_PHASE)
        v.freq = 220
        v.params(0, 0, 0, 0, 0, 0, tune)
        buf = []
        for _ in range(40):
            buf.extend(model.render(v, w))
        crosses = [i for i in range(1, len(buf)) if buf[i - 1] <= 0 < buf[i]]
        gaps = [b - a for a, b in zip(crosses, crosses[1:])]
        return law.SR / (sum(gaps) / len(gaps))

    lo, mid, hi = freq_of(0), freq_of(64), freq_of(127)
    assert abs(mid - 220) / 220 < 0.02, mid
    assert abs(hi / lo - law.exp2_cents(200)) / law.exp2_cents(200) < 0.02, (lo, hi)
    print(f'tune ok  {lo:.2f}  {mid:.2f}  {hi:.2f} Hz')


def test_kernel():
    try:
        import sharc
    except Exception as exc:
        print(f'SKIP sharc kernel ({exc})')
        return
    w = tables.default_waves()
    kern, _code, _texts, info, _waves = sharc.build(w)
    cases = [
        (110, (0, 0, 0, 0, 0, 0, 64), 1.0),
        (80, (100, 40, 70, 50, 40, 30, 90), 1.0),
        (440, (127, 127, 127, 127, 127, 127, 0), 0.25),
        (55, (10, 10, 0, 0, 0, 127, 127), 2.0),
    ]
    worst = 0.0
    for freq, params, gain in cases:
        ref_v = Voice(model.N_PHASE)
        dsp_v = Voice(model.N_PHASE)
        for v in (ref_v, dsp_v):
            v.freq, v.gain = freq, gain
            v.params(*params)
        for _ in range(4):
            ref = model.render(ref_v, w)
            got = sharc.run_voice(kern, dsp_v, w)
            worst = max(worst, max(abs(a - b) for a, b in zip(ref, got)))
            assert all(math.isfinite(x) for x in got)
            assert max(abs(x) for x in got) <= law.OUT_CLIP + 1e-3
    assert worst < 2e-3, worst
    print(f'kernel ok  max abs {worst:.3e}  {info["executed"]} instr/voice')
    # Idle voice writes silence and does not burn the oscillator loops.
    idle = Voice(model.N_PHASE)
    idle.active = 0
    idle.freq = 110
    idle.params(127, 127, 127, 127, 127, 127, 64)
    idle.phase = [0.2] * model.N_PHASE
    z = sharc.run_voice(kern, idle, w)
    assert max(abs(x) for x in z) == 0.0
    assert abs(idle.phase[0] - 0.2) < 1e-6


def test_stock_sim():
    snap = os.path.expanduser('~/dn2-workspace/snap/boot_stock.snap.gz')
    if not os.path.exists(snap):
        print('SKIP whole-DSP sim (no stock OS snapshot; the kernel test above does not need one)')
        return
    print('SKIP whole-DSP sim (stock snapshot exists, but this engine is not hooked into a section 7 yet)')


if __name__ == '__main__':
    test_base_saw_and_unix_limit()
    test_tune_moves_pitch()
    test_kernel()
    test_stock_sim()
    print('OK')
