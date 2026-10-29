"""FM+DYNAMIC: reference behaviour, and SHARC sim vs that reference.

    python3 engines/fm_dynamic/test_engine.py

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
    check([p[0] for p in PARAMS] == ['1FRQ', '1FEN', '1VOL', '1VEN', '2FRQ', '2ENV', '2FB', 'TUNE'],
          'knob order matches the A-7 screen')
    check(C.MACHINE_FM_DYNAMIC == 5 and C.MACHINE_FM_DYNAMIC not in C.STOCK_MACHINES, 'machine id 5 is new')
    check(t['start'][0] == 0 and abs(t['start'][32] - 0.5) < 1e-6 and t['start'][64] == 1, 'envelope holds 0, 0.5, 1')
    check(t['decay'][0] == 1 and t['decay'][64] == 1, 'knob ≤ 64 does not decay')
    h127 = C.samples_to_half(t['decay'][127])
    h96 = C.samples_to_half(t['decay'][96])
    h65 = C.samples_to_half(t['decay'][65])
    check(h127 < h96 < h65 and C.samples_to_half(t['decay'][64]) is None, '127 decays faster than 96, 64 holds')
    check(t['fen_d'][0] == 0 and t['fen_d'][127] > t['fen_d'][64] > 0, '1FEN depth grows with the knob')
    check(t['fen_c'][127] < t['fen_c'][40] < 1, '1FEN gets faster toward 127')
    check(t['vol_fb'][79] == 0 and t['vol_fb'][127] > 0, 'feedback only at high 1VOL')
    check(abs(C.tune_cents(64)) < 1e-9 and abs(C.tune_cents(0) + 100) < 1e-6, 'TUNE center 0 cents, knob 0 is −100')
    check(abs(C.linear_ratio(64) - 1) < 1e-6 and abs(C.exp_ratio(64) - 1) < 1e-6, 'both frequencies are ratio 1 at 64')

    def run(params, blocks=8, hz=440.0):
        v = Voice(t)
        v.set_params(params)
        v.note_on(hz=hz)
        return v, v.render(blocks)

    v, audio = run([0, 0, 0, 0, 64, 0, 0, 64], 40)
    check(v.active == 1 and max(abs(x) for x in audio) > 0.5, 'bare carrier keeps sounding while active')
    check(all(math.isfinite(x) and abs(x) <= 1.0001 for x in audio), 'output stays finite and inside ±gain')

    def env_after(p, blocks):
        v, _ = run([0, 0, 0, 0, 64, p, 0, 64], blocks)
        return v.env2

    check(abs(env_after(64, 30) - 1) < 1e-6, '2ENV 64 holds at full')
    check(abs(env_after(32, 30) - 0.5) < 1e-6, '2ENV 32 holds at half')
    check(env_after(127, 80) < C.IDLE_FLOOR, '2ENV 127 dies away')

    _, quiet = run([64, 0, 40, 0, 64, 40, 0, 64], 4)
    _, swept = run([64, 120, 40, 0, 64, 40, 0, 64], 4)
    check(max(abs(a - b) for a, b in zip(quiet, swept)) > 0.05, '1FEN moves the sound')

    z = C.make_tables(sine=[0.0] * 64)
    v = Voice(z)
    v.set_params([64, 0, 90, 0, 80, 64, 40, 64])
    v.note_on(hz=220)
    check(max(abs(x) for x in v.render_block()) == 0, 'a zero sine table silences the voice')

    for name, note, params in PRESETS:
        audio = []
        v = Voice(t)
        v.set_params(params)
        v.note_on(note)
        audio = v.render(20)
        check(max(abs(x) for x in audio) > 0.2, f'preset {name} makes a sound')
        path = os.path.join(HERE, 'examples', f'{name}.wav')
        if os.path.exists(path):
            with wave.open(path) as w:
                ok = w.getframerate() == C.SR and w.getnchannels() == 1 and w.getnframes() > C.SR
            check(ok, f'{name}.wav is 48 kHz mono and at least a second')
        else:
            check(False, f'missing {name}.wav (run reference.py)')


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
    r0 = sharc_run.Runner(kernels, t, initial_words([64] * 8, 440.0, 1))
    img = r0._image()
    n = len(r0.code) // 2
    bad = hwrules.check(img, [(sharc_run.L2_CODE_SW, sharc_run.L2_CODE_SW + n)])
    check(not bad, 'no SHARC hardware-rule violations' + ('' if not bad else ' ' + str(bad[:2])))
    try:
        sasm.lint(img, sharc_run.L2_CODE_SW, n,
                  allowed=[f'R{i}' for i in range(16)] + ['I0', 'I1', 'I2', 'I3', 'I4', 'M4'])
        check(True, 'assembler lint')
    except AssertionError as e:
        check(False, f'assembler lint: {e}')

    worst = 0
    for name, note, params in list(PRESETS) + [('extremes', 40, (127, 127, 127, 127, 127, 127, 127, 127))]:
        words = initial_words(params, C.midi_hz(note), 1)
        runner = sharc_run.Runner(kernels, t, words)
        dsl, _ = runner.run_dsl(4)
        sim, _state, counts = runner.run_sim(4)
        bits = all(C.f32_bits(a) == C.f32_bits(b) for a, b in zip(dsl, sim))
        check(bits, f'{name}: sim matches the float32 kernel bit for bit')
        v = Voice(t)
        v.set_params(params)
        v.note_on(note)
        ref = v.render(1)
        err = max(abs(a - b) for a, b in zip(ref, sim[:C.BLOCK]))
        check(err < 1e-4, f'{name}: first block matches the reference ({err:.2e})')
        check(all(math.isfinite(x) and abs(x) <= 1.0001 for x in sim), f'{name}: finite, saturated to ±1')
        worst = max(worst, max(counts))
        if params[2] < 80 and params[6] <= 40:
            v = Voice(t)
            v.set_params(params)
            v.note_on(note)
            err4 = max(abs(a - b) for a, b in zip(v.render(4), sim))
            check(err4 < 0.02, f'{name}: four blocks stay with the reference ({err4:.2e})')
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
