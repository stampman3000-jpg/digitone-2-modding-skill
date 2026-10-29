"""Sine and ratio tables: built-in defaults, and a local file the repo never stores.

    python3 engines/test_tables.py
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fm_common as C

FAILS = []


def check(cond, msg):
    if cond:
        print(f'  ok  {msg}')
    else:
        FAILS.append(msg)
        print(f'  FAIL  {msg}')


def expect_error(fn, text):
    try:
        fn()
    except ValueError as e:
        check(text.lower() in str(e).lower(), f'rejected ({e})')
        return
    check(False, 'should have rejected a bad table')


def main():
    t = C.make_tables()
    check(len(t['sine']) == C.N_SINE_DEFAULT, 'default sine length')
    check(abs(t['sine'][0]) < 1e-6 and t['sine'][C.N_SINE_DEFAULT // 4] > 0.9, 'default sine is a sine')
    check(len(t['ratios']) == 128, '128 listed ratios')
    labels = C.default_ratio_entries()
    check(labels[44][0] == '1' and abs(labels[44][1] - 1) < 1e-6, 'knob 44 is ratio 1')
    check(labels[24][0] == '1/2', 'knob 24 is 1/2')
    check(labels[68][0] == '2', 'knob 68 is 2')

    sine = C.default_sine(128)
    ratios = [1.5] * 128
    built = C.make_tables(sine=sine, ratios=ratios)
    raw_path = tempfile.mktemp(suffix='.fm2t')
    json_path = tempfile.mktemp(suffix='.json')
    try:
        C.dump_raw(raw_path, built)
        back = C.load_table_file(raw_path)
        check(back['sine'] == built['sine'] and back['ratios'] == built['ratios'], 'raw FM2T round trip')
        with open(json_path, 'w') as f:
            json.dump({'version': 1, 'sine': sine, 'ratios': ratios}, f)
        back = C.load_table_file(json_path)
        check(len(back['sine']) == 128 and abs(back['ratios'][10] - 1.5) < 1e-6, 'JSON round trip')
        with open(json_path, 'w') as f:
            json.dump({'ratios': [4.0] * 128}, f)
        back = C.load_table_file(json_path)
        check(len(back['sine']) == C.N_SINE_DEFAULT and abs(back['ratios'][0] - 4) < 1e-6,
              'JSON may replace only the ratio list')
    finally:
        for p in (raw_path, json_path):
            if os.path.exists(p):
                os.unlink(p)

    expect_error(lambda: C.make_tables(sine=[0.0] * 1000), 'power of two')
    expect_error(lambda: C.make_tables(ratios=[0.0] * 10), '128')
    expect_error(lambda: C.make_tables(ratios=[math.nan] * 128), 'finite')
    expect_error(lambda: C.make_tables(sine=[2.0] * 64), '±1.25')
    blob = struct.pack('<4sIII', b'FM2T', 99, 64, 128)
    path = tempfile.mktemp(suffix='.fm2t')
    try:
        open(path, 'wb').write(blob + b'\x00' * (64 + 128) * 4)
        expect_error(lambda: C.load_table_file(path), 'version')
    finally:
        os.unlink(path)
    saved = os.environ.pop(C.ENV_TABLE, None)
    try:
        check(len(C.active_tables()['sine']) == C.N_SINE_DEFAULT, 'no env var means the built-in tables')
    finally:
        if saved is not None:
            os.environ[C.ENV_TABLE] = saved


if __name__ == '__main__':
    main()
    print('FAIL' if FAILS else 'OK', len(FAILS))
    sys.exit(1 if FAILS else 0)
