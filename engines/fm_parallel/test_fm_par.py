"""FM+PARALLELL standalone engine.

    python3 engines/fm_parallel/test_fm_par.py

Checks the placeholder curves, the Python model, and (via gcc) fm_par.c.
"""
from __future__ import annotations

import math
import os
import platform
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..')))

import fm_common as C
import fm_par_ref as R
from fm_par_ref import Voice

FAILS = []


def check(cond, msg):
    if cond:
        print(f'  ok  {msg}')
    else:
        FAILS.append(msg)
        print(f'  FAIL  {msg}')


def bits(x):
    return struct.unpack('<I', struct.pack('<f', float(x)))[0]


def curves():
    check(tuple(R.RATIOS[0]) == tuple(R.RATIOS[1]) == tuple(R.RATIOS[2]) == R.MUSICAL,
          'each FRQ knob starts on the 24 musical ratios')
    check(len(R.MUSICAL) == 24, '24 FRQ steps')
    seen = {R.frq_index(k) for k in range(128)}
    check(seen == set(range(24)), 'knob 0..127 reaches every FRQ step')
    check(R.frq_ratio(0, 0) == R.f32(1 / 64) and R.frq_ratio(2, 127) == 4.0,
          'FRQ runs from 1/64 to 4')
    for op in range(3):
        a0 = R.env_amount(op, 0)
        a64 = R.env_amount(op, 64)
        a78 = R.env_amount(op, 78)
        a83 = R.env_amount(op, 83)
        a94 = R.env_amount(op, 94)
        a127 = R.env_amount(op, 127)
        check(a0 == 0 and a78 > a64 and a78 >= a83 > a94 > a127,
              f'ENV {op + 1} peaks in 72..83 and folds back after 94')
    check(R.tone_open(100) > 0.8 and R.tone_open(127) - R.tone_open(100) < 0.15,
          'TONE saturates from about 100')
    check(all(abs(R.tune_cents(64 + d) + R.tune_cents(64 - d)) < 1e-4 for d in range(64)),
          'TUNE is symmetric about 64')
    check(R.tune_cents(64) == 0 and abs(R.tune_cents(0) + 100) < 1e-4,
          'TUNE center is 0 cents, knob 0 is -100')
    check(R.MOD_W[2] > R.MOD_W[1] > R.MOD_W[0], 'modulator 3 is weighted brightest')
    check([p[0] for p in R.PARAMS] ==
          ['1FRQ', '1ENV', '2FRQ', '2ENV', '3FRQ', '3ENV', 'TONE', 'TUNE'],
          'eight knobs, screen order')
    check(R.STATE_BYTES == 52 and R.MACHINE_ID == 7, '52-byte voice, machine type 7')
    check(C.MACHINE_FM_STATIC == 5 and C.MACHINE_FM_DYNAMIC == 6
          and C.MACHINE_FM_PARALLEL == 7 and C.MACHINE_SUPERWAVE == 8,
          'firmware ids match the header')
    check(C.decide(5, 99) == (0, 99), 'shipped FM+STATIC is left alone')
    check(C.decide(6, 99) == (6, 4) and C.decide(7, 3) == (7, 4),
          'the hook owns types 6 and 7 only')
    check(all(m not in C.STOCK_MACHINES for m in (5, 6, 7)),
          'none of the FM+ types replace a stock machine')


def _finite(x):
    return math.isfinite(x) and abs(x) < 1e20


def model():
    def brightness(params):
        v = Voice()
        v.set_params(params)
        v.note_on(220.0)
        x = v.render(4096)
        return sum(abs(x[i] - x[i - 1]) for i in range(1, len(x))) / len(x)

    lo = brightness([0, 78, 32, 78, 32, 78, 100, 64])
    hi1 = brightness([127, 78, 32, 78, 32, 78, 100, 64])
    lo3 = brightness([32, 78, 32, 78, 0, 78, 100, 64])
    hi3 = brightness([32, 78, 32, 78, 127, 78, 100, 64])
    check((hi3 - lo3) > (hi1 - lo) and (hi3 - lo3) > 0, '3FRQ moves brightness more than 1FRQ')

    peaks = []
    for knob in range(8):
        for step in (0, 32, 64, 78, 94, 100, 110, 127):
            p = [16, 60, 16, 60, 16, 60, 40, 64]
            p[knob] = step
            v = Voice()
            v.set_params(p)
            v.note_on(440.0)
            x = v.render(2048)
            check(all(_finite(s) and abs(s) <= 1.0001 for s in x), f'finite block knob {knob}={step}')
            peaks.append(max(abs(s) for s in x))
    check(min(peaks) > 0.98 and max(peaks) <= 1.0001, 'loudness stays on the carrier')

    v = Voice()
    v.phase_c = 0.3
    z = v.render(32)
    check(v.active == 0 and z == [0.0] * 32 and v.phase_c == 0.3, 'idle voice is silent')

    # Corners, a short render: no NaN, inside the gain.
    for mask in range(256):
        p = [127 if mask & (1 << i) else 0 for i in range(8)]
        v = Voice()
        v.set_params(p)
        v.note_on(440.0)
        x = v.render(64)
        if not all(_finite(s) and abs(s) <= 1.0001 for s in x):
            check(False, f'corner {mask} stayed bounded')
            break
    else:
        check(True, 'all 256 knob corners stay bounded')

    v = Voice()
    v.set_params([255] * 8)
    check(v.param == [127] * 8, 'knobs clamp to 127')
    v.note_hz = float('nan')
    v.out_gain = float('inf')
    v.tone_z = float('nan')
    v.active = 1
    v.trig = 1
    x = v.render(32)
    check(all(_finite(s) and abs(s) <= R.H['FM_PAR_OUT_GAIN_MAX'] + 1e-5 for s in x),
          'NaN and Inf inputs collapse to a finite voice')
    check(v.tone_z == 0.0 or _finite(v.tone_z), 'TONE state stays finite')


def compile_c():
    flags = ['-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-ffp-contract=off']
    if platform.machine() in ('x86_64', 'amd64'):
        flags += ['-msse2', '-mfpmath=sse']
    bin_path = '/tmp/fm_par_test'
    src = ['test_fm_par.c', 'fm_par.c', '-lm']
    cmd = ['gcc', *flags, '-o', bin_path, *src]
    subprocess.check_call(cmd, cwd=HERE)
    return bin_path


def c_and_cross():
    try:
        bin_path = compile_c()
    except (OSError, subprocess.CalledProcessError) as e:
        check(False, 'gcc build of fm_par.c (%s)' % e)
        return
    run = subprocess.run([bin_path], cwd=HERE, text=True, capture_output=True)
    sys.stdout.write(run.stdout)
    sys.stderr.write(run.stderr)
    check(run.returncode == 0, 'C self-test')

    lines = []
    cases = [
        (32, 440.0, 1.0, 1, [44, 78, 68, 60, 80, 90, 40, 64]),
        (32, 440.0, 1.0, 0, [44, 78, 68, 60, 80, 90, 40, 64]),
        (64, 110.0, 0.5, 1, [0, 0, 0, 0, 0, 0, 0, 0]),
        (64, 110.0, 0.5, 0, [127, 127, 127, 127, 127, 127, 127, 127]),
        (32, 880.0, 1.0, 1, [5, 72, 40, 83, 127, 94, 100, 1]),
        (32, 880.0, 1.0, 0, [5, 72, 40, 83, 127, 94, 100, 127]),
    ]
    lines.append('reset')
    for n, hz, gain, trig, p in cases:
        lines.append('%d %s %s %d %s' % (n, hz, gain, trig, ' '.join(str(x) for x in p)))
    proc = subprocess.run([bin_path, 'cmp'], input='\n'.join(lines) + '\n',
                          text=True, capture_output=True, cwd=HERE)
    check(proc.returncode == 0, 'C compare harness')
    if proc.returncode != 0:
        print(proc.stderr)
        return
    v = Voice()
    worst = 0.0
    out_lines = [ln for ln in proc.stdout.splitlines() if ln and not ln.startswith('S ')]
    state_lines = [ln for ln in proc.stdout.splitlines() if ln.startswith('S ')]
    check(len(out_lines) == len(cases), 'one C buffer per case')
    for (n, hz, gain, trig, p), blob, st in zip(cases, out_lines, state_lines):
        v.note_hz = hz
        v.out_gain = gain
        v.set_params(p)
        v.trig = trig
        audio = v.render(n)
        got = [int(w, 16) for w in blob.split()]
        check(len(got) == n, 'C buffer length')
        for a, b in zip(audio, got):
            worst = max(worst, abs(a - struct.unpack('<f', struct.pack('<I', b))[0]))
        # state: phase_c, 3 phases, 3 envs, hz, gain
        parts = st.split()
        cstate = [struct.unpack('<f', struct.pack('<I', int(w, 16)))[0] for w in parts[1:10]]
        py = [v.phase_c, *v.phase_m, *v.env, v.note_hz, v.out_gain]
        for a, b in zip(py, cstate):
            worst = max(worst, abs(a - b))
    check(worst == 0.0, 'Python matches the C engine bit for bit (worst %g)' % worst)


if __name__ == '__main__':
    print('curves')
    curves()
    print('model')
    model()
    print('c')
    c_and_cross()
    print('FAIL' if FAILS else 'OK', len(FAILS))
    sys.exit(1 if FAILS else 0)
