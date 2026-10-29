"""Write a few SWAVE-SAW examples. Fade and peak normalize are file-only.

    python3 engines/swave_saw/render_wav.py [--wave-table FILE] [-o DIR]
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
    # name, freq, knobs UNIL UNIW UNIX SUBX SUB1 SUB2 TUNE
    presets = [
        ('bare', 110, (0, 0, 0, 0, 0, 0, 64)),
        ('unison', 110, (100, 36, 0, 0, 0, 0, 64)),
        ('stack', 55, (110, 48, 90, 50, 40, 30, 64)),
    ]
    for name, freq, knobs in presets:
        v = Voice(model.N_PHASE)
        v.freq = freq
        v.params(*knobs)
        path = write_wav(os.path.join(args.o, name + '.wav'), render_seconds(v, model.render, waves, args.seconds))
        print(path, waves.source)


if __name__ == '__main__':
    main()
