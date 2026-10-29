"""FM+PARALLELL reference model.

Manual OS 1.32 appendix A, page A-7: "three exact copies of the most efficient
FM+ structure." The block diagram is three modulators, each with a listed
frequency and an FM+ envelope, summed, then TONE, then one carrier.

Listed frequencies come from the ratio table (built-in, or a local file).
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import fm_common as C

# Screen order on manual p. A-7 (the prose says "1-3FRQ" then "1-3ENV";
# the screenshot pairs each frequency with its envelope).
PARAMS = (
    ('1FRQ', '0–127',
     'Modulator 1 listed frequency. Manual A-7. The list is stepped; the '
     'manual screens show ratios such as 1/2, 1 and 2.'),
    ('1ENV', '0–127',
     'Modulator 1 level, FM+ envelope figure (manual A-6).'),
    ('2FRQ', '0–127',
     'Modulator 2 listed frequency. Manual A-7.'),
    ('2ENV', '0–127',
     'Modulator 2 level, FM+ envelope figure (manual A-6).'),
    ('3FRQ', '0–127',
     'Modulator 3 listed frequency. Manual A-7.'),
    ('3ENV', '0–127',
     'Modulator 3 level, FM+ envelope figure (manual A-6).'),
    ('TONE', '0–127',
     'Colours the summed modulators before the carrier. High settings add '
     'high-frequency harmonics. Manual A-7.'),
    ('TUNE', '−64–+63 (0–127)',
     'Output tune, ±100 cents, center 64. Manual p. 1-25 and A-7.'),
)

# Knobs for the default ratio list: 1/1 = 44, 3/2 = 56, 2/1 = 68, 3/1 = 76, 5/1 = 88.
PRESETS = (
    ('stack', 60, (44, 90, 68, 80, 76, 70, 90, 64)),
    ('bright', 72, (68, 110, 88, 100, 76, 90, 127, 64)),
    ('fifth', 64, (44, 48, 56, 36, 68, 24, 60, 64)),
)


class Voice:
    def __init__(self, tables=None):
        self.tables = tables or C.active_tables()
        self.params = [44, 0, 68, 0, 76, 0, 64, 64]
        self.note_hz = 440.0
        self.out_gain = C.OUT_GAIN_DEFAULT
        self.active = 0
        self.trig = 0
        self.ph_c = 0.0
        self.ph = [0.0, 0.0, 0.0]
        self.env = [0.0, 0.0, 0.0]
        self.z = [0.0, 0.0, 0.0]

    def set_params(self, params):
        self.params = C.clamp_params(params)

    def note_on(self, note=None, hz=None):
        if note is not None:
            self.note_hz = C.midi_hz(note)
        if hz is not None:
            self.note_hz = float(hz)
        self.trig = 1

    def render_block(self):
        t = self.tables
        p = C.clamp_params(self.params)
        was = self.trig
        if was:
            self.ph_c = 0.0
            self.ph = [0.0, 0.0, 0.0]
            self.z = [0.0, 0.0, 0.0]
            self.active = 1
            self.trig = 0
        if not self.active:
            return C.silent_block()

        ninc = C.note_inc(self.note_hz, t['tune'][p[7]])
        incs, decs = [], []
        for i, (fi, ei) in enumerate(((0, 1), (2, 3), (4, 5))):
            self.env[i], dec = C.step_hold_env(self.env[i], p[ei], was, t)
            incs.append(ninc * t['ratios'][p[fi]])
            decs.append(dec)
        g = t['tone_g'][p[6]]
        h = t['tone_h'][p[6]]
        sine = t['sine']
        out = []
        for _ in range(C.BLOCK):
            m = 0.0
            for i in range(3):
                self.ph[i], s = C.advance_osc(self.ph[i], incs[i], 0.0, 0.0, sine)
                m += s * self.env[i]
                self.env[i] *= decs[i]
            dev = C.clip(C.tone_shape(m, g, h) * C.BETA, C.DEV_CLIP)
            self.ph_c, s = C.advance_osc(self.ph_c, ninc, 1.0, dev, sine)
            out.append(C.clip(s * self.out_gain, self.out_gain))
        return out

    def render(self, blocks):
        audio = []
        for _ in range(blocks):
            audio.extend(self.render_block())
        return audio


def render_preset(name, tables=None, seconds=2.0):
    preset = {n: (note, params) for n, note, params in PRESETS}[name]
    note, params = preset
    v = Voice(tables)
    v.set_params(params)
    v.note_on(note)
    return v.render(int(seconds * C.SR / C.BLOCK))


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='Render FM+PARALLELL examples from the reference model')
    ap.add_argument('--tables', help='local sine + ratio file (JSON or .fm2t). Else $DN2_FM_TABLES.')
    ap.add_argument('--seconds', type=float, default=2.0)
    args = ap.parse_args()
    tables = C.active_tables(args.tables)
    here = os.path.dirname(os.path.abspath(__file__))
    for name, _, _ in PRESETS:
        audio = render_preset(name, tables, args.seconds)
        path = os.path.join(here, 'examples', f'{name}.wav')
        peak = C.write_wav(path, audio)
        print(f'{path}  raw peak {peak:.4f}')
