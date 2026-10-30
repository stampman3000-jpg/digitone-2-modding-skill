"""FM+PARALLELL: reference behaviour, and SHARC sim vs that reference.

    python3 engines/fm_parallel/test_engine.py

The sim half does not load a stock DSP snapshot. If dnfw is missing it skips
with a message; the reference checks still run.
"""
from __future__ import annotations

import math
import os
import sys
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..')))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'skills', 'digitone-2-modding-skill', 'scripts')))

import fm_common as C
from reference import PARAMS, PRESETS, Voice

FAILS = []


def check(cond, msg):
    if cond:
        print(f'  ok  {msg}')
    else:
        FAILS.append(msg)
        print(f'  FAIL  {msg}')


def ref_checks():
    t = C.make_tables()
    check(len(PARAMS) == 8, '8 SYN parameters')
    check([p[0] for p in PARAMS] == ['1FRQ', '1ENV', '2FRQ', '2ENV', '3FRQ', '3ENV', 'TONE', 'TUNE'],
          'knob order matches the A-7 screen')
    check(C.MACHINE_FM_PARALLEL == 7 and C.MACHINE_FM_PARALLEL not in C.STOCK_MACHINES, 'machine id 7 is new')
    check(C.decide(5, 3) == (0, 3), 'does not take the shipped FM+STATIC id')
    ratios = t['ratios']
    check(any(abs(r - 0.5) < 1e-6 for r in ratios), 'listed ratios include 1/2')
    check(any(abs(r - 1.0) < 1e-6 for r in ratios), 'listed ratios include 1')
    check(any(abs(r - 2.0) < 1e-6 for r in ratios), 'listed ratios include 2')
    check(t['tone_g'][127] > t['tone_g'][0], 'TONE raises the modulator gain')

    def run(params, blocks=4, tables=None, hz=440.0):
        v = Voice(tables or t)
        v.set_params(params)
        v.note_on(hz=hz)
        return v, v.render(blocks)

    v, bare = run([0, 0, 0, 0, 0, 0, 0, 64], 30)
    check(v.active == 1 and max(abs(x) for x in bare) > 0.5, 'no modulators still leaves the carrier')
    _, loud = run([44, 90, 68, 80, 76, 70, 40, 64], 4)
    _, bright = run([44, 90, 68, 80, 76, 70, 127, 64], 4)
    check(max(abs(a - b) for a, b in zip(loud, bright)) > 0.02, 'TONE changes the sound')
    swapped = C.make_tables(ratios=[3.0] * 128)
    _, a = run([10, 64, 20, 0, 30, 0, 64, 64], 2, t)
    _, b = run([10, 64, 20, 0, 30, 0, 64, 64], 2, swapped)
    check(max(abs(x - y) for x, y in zip(a, b)) > 0.05, 'an external ratio list changes the sound')
    z = C.make_tables(sine=[0.0] * 128)
    v = Voice(z)
    v.set_params([44, 64, 68, 64, 76, 64, 80, 64])
    v.note_on(hz=330)
    check(max(abs(x) for x in v.render_block()) == 0, 'a zero sine table silences the voice')
    for name, note, params in PRESETS:
        v = Voice(t)
        v.set_params(params)
        v.note_on(note)
        audio = v.render(20)
        check(max(abs(x) for x in audio) > 0.2 and all(math.isfinite(x) for x in audio), f'preset {name}')
        path = os.path.join(HERE, 'examples', f'{name}.wav')
        if not os.path.exists(path):
            check(False, f'missing {name}.wav')
            continue
        with wave.open(path) as w:
            ok = w.getframerate() == C.SR and w.getnchannels() == 1 and w.getnframes() > C.SR
        check(ok, f'{name}.wav is 48 kHz mono and at least a second')


def sim_checks():
    try:
        import sharc_run
        import hwrules
        import sasm
        from kernel import build, initial_words
    except Exception as e:
        print('SKIP sim: the SHARC assembler is not available (' + str(e).splitlines()[0] + ').')
        print('This comparison does not need a stock DSP boot snapshot.')
        print('It needs dnfw so the kernel can be assembled (scripts/dn2setup.py).')
        print('The reference checks above already ran.')
        return
    t = C.make_tables()
    kernels = build(t)
    runner = sharc_run.Runner(kernels, t, initial_words([44, 64, 68, 64, 76, 64, 64, 64], 440.0))
    img = runner._image()
    n = len(runner.code) // 2
    bad = hwrules.check(img, [(sharc_run.L2_CODE_SW, sharc_run.L2_CODE_SW + n)])
    check(not bad, 'no SHARC hardware-rule violations')
    try:
        sasm.lint(img, sharc_run.L2_CODE_SW, n,
                  allowed=[f'R{i}' for i in range(16)] + ['I0', 'I1', 'I2', 'I3', 'I4', 'M4'])
        check(True, 'assembler lint')
    except AssertionError as e:
        check(False, f'assembler lint: {e}')

    worst = 0
    cases = list(PRESETS) + [('extremes', 36, (127, 127, 127, 127, 127, 127, 127, 127))]
    for name, note, params in cases:
        words = initial_words(params, C.midi_hz(note), 1)
        runner = sharc_run.Runner(kernels, t, words)
        dsl, _ = runner.run_dsl(4)
        sim, _st, counts = runner.run_sim(4)
        check(all(C.f32_bits(a) == C.f32_bits(b) for a, b in zip(dsl, sim)),
              f'{name}: sim matches the float32 kernel bit for bit')
        v = Voice(t)
        v.set_params(params)
        v.note_on(note)
        ref = v.render(4)
        err0 = max(abs(a - b) for a, b in zip(ref[:C.BLOCK], sim[:C.BLOCK]))
        check(err0 < 1e-4, f'{name}: first block matches the reference ({err0:.2e})')
        check(all(math.isfinite(x) and abs(x) <= 1.0001 for x in sim), f'{name}: finite, saturated to ±1')
        worst = max(worst, max(counts))
        if params[6] <= 80:
            err = max(abs(a - b) for a, b in zip(ref, sim))
            check(err < 0.02, f'{name}: four blocks stay with the reference ({err:.2e})')
    # external ratios reach the kernel, not just the reference
    swapped = C.make_tables(ratios=[2.5] * 128)
    params = [8, 80, 16, 0, 24, 0, 70, 64]
    sim_a, _, _ = sharc_run.Runner(build(t), t, initial_words(params, 220.0)).run_sim(1)
    sim_b, _, _ = sharc_run.Runner(build(swapped), swapped, initial_words(params, 220.0)).run_sim(1)
    check(max(abs(a - b) for a, b in zip(sim_a, sim_b)) > 0.05, 'kernel hears a swapped ratio list')
    idle = sharc_run.Runner(kernels, t, initial_words([0] * 7 + [64], 440.0, trig=0))
    z, _, ic = idle.run_sim(1)
    check(all(x == 0 for x in z) and ic[0] < worst / 4, f'idle voice is silent and cheap ({ic[0]} vs {worst})')
    voices = 16 * worst
    print(f'  cost  {worst} instr/voice/block, idle {ic[0]}, 16 voices {voices}, '
          f'with the ~154k rest of the chain ~{voices + 154000}')


if __name__ == '__main__':
    print('reference')
    ref_checks()
    print('sim')
    sim_checks()
    print('FAIL' if FAILS else 'OK', len(FAILS))
    sys.exit(1 if FAILS else 0)
