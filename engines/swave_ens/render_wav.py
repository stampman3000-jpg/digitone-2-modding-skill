"""Write a few SWAVE-ENS examples.

    python3 engines/swave_ens/render_wav.py [--wave-table FILE] [-o DIR]
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'swave_common'))
sys.path.insert(0, HERE)

import model
from osc import Voice
from tables import load_waves
from wav import render_seconds, write_wav


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--wave-table', default=os.environ.get('SWAVE_WAVE_TABLE') or None)
    ap.add_argument('-o', default=os.path.join(HERE, 'examples'))
    ap.add_argument('--seconds', type=float, default=1.0)
    args = ap.parse_args()
    waves = load_waves(args.wave_table)
    # PCH2 PCH3 PCH4 WAVE PW CHRL CHRW TUNE. 130.81 Hz is C3.
    presets = [
        ('single', 130.81, (0, 0, 0, 0, 64, 0, 0, 64)),
        ('major', 130.81, (4, 7, 0, 0, 64, 0, 0, 64)),
        ('just', 130.81, (127, 125, 0, 0, 64, 0, 0, 64)),
        ('chorus', 110.00, (0, 0, 0, 40, 64, 90, 80, 64)),
    ]
    for name, freq, knobs in presets:
        v = Voice(model.N_PHASE)
        v.freq = freq
        v.params(*knobs)
        path = write_wav(os.path.join(args.o, name + '.wav'), render_seconds(v, model.render, waves, args.seconds))
        print(path, waves.source)


if __name__ == '__main__':
    main()
