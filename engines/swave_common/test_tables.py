"""Wave-table defaults, the external-file swap, and the gitignore.

    python3 engines/swave_common/test_tables.py
"""

from __future__ import annotations

import math
import os
import struct
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import law
import tables
from tables import HARM, N, dump_f32, dump_json, load_waves


def goertzel(samples, freq, sr=law.SR):
    w = 2.0 * math.pi * freq / sr
    c = 2.0 * math.cos(w)
    s1 = s2 = 0.0
    for x in samples:
        s0 = x + c * s1 - s2
        s2, s1 = s1, s0
    return s1 * s1 + s2 * s2 - c * s1 * s2


def test_default_shapes():
    w = tables.default_waves()
    saw = w.saw[0]
    # A rising saw is negative just after the jump and positive late in the cycle.
    assert saw[2] < -0.2, saw[2]
    assert saw[N - 4] > 0.2, saw[N - 4]
    sine = w.sine[0]
    err = max(abs(sine[i] - math.sin(2 * math.pi * i / N)) for i in range(N))
    assert err < 1e-5, err
    # Square: strong fundamental, weak second harmonic.
    sq = w.square[0][:-1]
    # one cycle, played as if it were audio at sr/N
    odd = goertzel(sq, law.SR / N, law.SR)
    even = goertzel(sq, 2 * law.SR / N, law.SR)
    assert odd > even * 20, (odd, even)
    assert w.nearest_pulse(0.5) == w.duties.index(0.5)
    # Tie at the midpoint steps up, matching the DSP compare.
    mid = 0.5 * (w.duties[0] + w.duties[1])
    assert w.nearest_pulse(mid) == 1
    assert w.nearest_pulse(mid - 1e-6) == 0
    print('default shapes ok')


def test_roundtrip_and_swap():
    w = tables.default_waves()
    with tempfile.TemporaryDirectory() as d:
        jp = os.path.join(d, 't.swave.json')
        fp = os.path.join(d, 't.swave.f32')
        dump_json(w, jp)
        dump_f32(w, fp)
        a = tables.load_json(jp)
        b = tables.load_f32(fp)
        assert a.flat_words()[law.WAVE_WORD:] == w.flat_words()[law.WAVE_WORD:]
        assert b.saw[0] == w.saw[0]
        # A one-cycle file (not a mip stack) is accepted and band-limited.
        sine = [math.sin(2 * math.pi * i / 64) for i in range(64)]
        doc_path = os.path.join(d, 'one.swave.json')
        import json
        json.dump({
            'version': 1,
            'waves': {
                'saw': sine,
                'sine': sine,
                'square': sine,
                'pulse': {'duties': [0.5], 'cycles': [sine]},
            },
        }, open(doc_path, 'w'))
        ext = load_waves(doc_path)
        assert ext.source == doc_path
        assert len(ext.saw) == len(HARM)
        # The imported "saw" is a sine, so it must not match the Fourier saw.
        assert max(abs(x - y) for x, y in zip(ext.saw[-1], w.saw[-1])) > 0.2
        os.environ['SWAVE_WAVE_TABLE'] = doc_path
        try:
            assert load_waves().source == doc_path
        finally:
            os.environ.pop('SWAVE_WAVE_TABLE', None)
    print('roundtrip and swap ok')


def test_gitignore():
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', '..'))
    for rel in ('engines/local/mine.swave.json', 'notes/from-os.swave.f32'):
        r = subprocess.run(['git', 'check-ignore', '-q', rel], cwd=root)
        assert r.returncode == 0, rel
    print('gitignore ok')


def test_laws():
    assert law.tune_cents(64) == 0
    assert abs(law.tune_cents(0) + 100) < 1e-9
    assert abs(law.tune_cents(127) - 100) < 1e-9
    assert law.pch_ratio(0) is None
    assert abs(law.pch_ratio(4) - law.SEMI_RATIO[4]) < 1e-8
    assert abs(law.pch_ratio(7) - law.SEMI_RATIO[7]) < 1e-8
    assert abs(law.pch_ratio(127) - 1.5) < 1e-6
    assert abs(law.pch_ratio(125) - 1.25) < 1e-6
    assert law.pch_ratio(64) == law.SEMI_DOWN[1]
    # UNIX cannot exceed UNIL: checked via the renderer in the saw test.
    assert law.ens_morph(0, 64) == 0.0
    assert abs(law.ens_morph(127, 64) - 0.5) < 1e-9
    g, off = law.morph_gain_offset(0.5)
    assert abs(g - 1) < 1e-9 and abs(off - 0.5) < 1e-9
    assert law.pw_duty(64) == 0.5
    assert law.pwad_hz(0) == 0
    assert not law.pwrs_on(0) and law.pwrs_on(1)
    print('laws ok')


if __name__ == '__main__':
    test_laws()
    test_default_shapes()
    test_roundtrip_and_swap()
    test_gitignore()
    print('OK')
