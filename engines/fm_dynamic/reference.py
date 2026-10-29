"""FM+DYNAMIC reference model.

Manual OS 1.32 appendix A, page A-7, and the FM+ envelope figure on A-6.
Two modulators sum into one carrier. There is no TONE block on this machine.
Modulator 1's frequency and level move on note-on (1FEN, 1VEN). Modulator 2
is an exponential ratio with the shared FM+ envelope and its own feedback.

The oscillator uses the sine table (built-in, or a local file). That is the
same table the SHARC kernel loads, so a swapped file changes this model and
the DSP together.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import fm_common as C

# Encoder order is the machine screen on manual p. A-7, left to right,
# top row then bottom row. LEV is the separate level knob, not one of these.
PARAMS = (
    ('1FRQ', '0–127',
     'Modulator 1 linear frequency. Knob 64 is ratio 1.0 (tracks the note). '
     'Manual A-7: "sets the linear continuous frequency control of modulator 1."'),
    ('1FEN', '0–127',
     'Modulator 1 frequency envelope. Note-on sweep added to 1FRQ; higher is '
     'faster and deeper. Manual A-7.'),
    ('1VOL', '0–127',
     'Modulator 1 output level. High settings (from knob 80) add amplitude '
     'feedback. Manual A-7: "for high 1VOL settings amplitude feedback is '
     'introduced."'),
    ('1VEN', '0–127',
     'Modulator 1 volume envelope. Note-on sweep added to 1VOL. Manual A-7.'),
    ('2FRQ', '0–127',
     'Modulator 2 exponential frequency. Knob 64 is ratio 1; each 16 steps is '
     'an octave. Manual A-7.'),
    ('2ENV', '0–127',
     'Modulator 2 level, the FM+ envelope figure (manual A-6): 0–64 holds, '
     '65–127 decays from full, faster toward 127.'),
    ('2FB', '0–127',
     'Modulator 2 feedback. Manual A-7.'),
    ('TUNE', '−64–+63 (0–127)',
     'Output tune, ±100 cents, center 64. Manual p. 1-25 and A-7.'),
)

# name, note, 8 knobs. Chosen to show the sweeps, the feedback, and a hold.
PRESETS = (
    ('sweep', 69, (64, 110, 0, 120, 72, 100, 30, 64)),
    ('feedback', 57, (48, 40, 110, 20, 88, 70, 100, 64)),
    ('held', 69, (64, 0, 60, 0, 80, 40, 20, 64)),
)


class Voice:
    def __init__(self, tables=None):
        self.tables = tables or C.active_tables()
        self.params = [0, 0, 0, 0, 64, 0, 0, 64]
        self.note_hz = 440.0
        self.out_gain = C.OUT_GAIN_DEFAULT
        self.active = 0
        self.trig = 0
        self.ph_c = 0.0
        self.ph1 = 0.0
        self.ph2 = 0.0
        self.env2 = 0.0
        self.fen = 0.0
        self.ven = 0.0
        self.z1 = 0.0
        self.z2 = 0.0

    def set_params(self, params):
        self.params = C.clamp_params(params)

    def note_on(self, note=None, hz=None):
        if note is not None:
            self.note_hz = C.midi_hz(note)
        if hz is not None:
            self.note_hz = float(hz)
        self.trig = 1

    def render_block(self):
        """32 samples. Mutes itself once every level has died away."""
        t = self.tables
        p = C.clamp_params(self.params)
        was = self.trig
        if was:
            self.ph_c = self.ph1 = self.ph2 = 0.0
            self.z1 = self.z2 = 0.0
            self.fen = t['fen_d'][p[1]]
            self.ven = t['ven_d'][p[3]]
            self.active = 1
            self.trig = 0
        if not self.active:
            return C.silent_block()

        ninc = C.note_inc(self.note_hz, t['tune'][p[7]])
        self.env2, dec2 = C.step_hold_env(self.env2, p[5], was, t)
        fb2 = p[6] * C.FB_SCALE
        fb1 = t['vol_fb'][p[2]]
        base_vol = p[2] * C.VOL_SCALE
        fen_c = t['fen_c'][p[1]]
        ven_c = t['ven_c'][p[3]]
        inc2 = ninc * t['exp_ratio'][p[4]]
        if C.LINEAR_TRACKS_NOTE:
            base = C.linear_ratio(p[0])
        else:
            base = (p[0] * C.VOL_SCALE) * C.LINEAR_HZ_MAX
        sine = t['sine']
        out = []
        for _ in range(C.BLOCK):
            if C.LINEAR_TRACKS_NOTE:
                inc1 = ninc * max(0.0, base + self.fen)
            else:
                inc1 = max(0.0, base + self.fen) * C.SR_INV
            self.fen *= fen_c
            lev = min(1.0, max(0.0, base_vol + self.ven))
            self.ven *= ven_c
            self.ph1, s1 = C.advance_osc(self.ph1, inc1, fb1, self.z1, sine)
            self.z1 = s1
            self.ph2, s2 = C.advance_osc(self.ph2, inc2, fb2, self.z2, sine)
            self.z2 = s2
            m2 = s2 * self.env2
            self.env2 *= dec2
            dev = C.clip((s1 * lev + m2) * C.BETA, C.DEV_CLIP)
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
    ap = argparse.ArgumentParser(description='Render FM+DYNAMIC examples from the reference model')
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
