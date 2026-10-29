# FM+DYNAMIC

A new Digitone II machine (id **5**). It does not replace FM TONE, WAVETONE,
FM DRUM, SWARMER, or MIDI. How it plugs in: [`../INTERFACE.md`](../INTERFACE.md).

The sound follows Elektron’s *Monomachine User’s Manual* OS 1.32, appendix A
page **A-7** (FM+DYNAMIC “FM+DYN”) and the FM+ envelope figure on page **A-6**.
<https://www.elektron.se/wp-content/uploads/2024/09/monomachine_manual_OS1.32.pdf>

Two modulators sum into one carrier. Modulator 1’s frequency and level can
sweep on every note-on. Modulator 2 sits on an exponential ratio. There is no
TONE block on this machine (the diagram on A-7 has none). The DN2 filter and
amp stay downstream; this page does not add another of either.

Knob order is the machine screen on A-7, left to right, top row then bottom
row. LEV is the track level knob, not one of these eight.

| knob | name | range | what it does | manual |
|---|---|---|---|---|
| 1 | 1FRQ | 0–127 | Linear frequency of modulator 1. 0 is stopped, 64 is ratio 1.0, 127 is just under 2. Tracks the note. | A-7, “linear continuous frequency control of modulator 1” |
| 2 | 1FEN | 0–127 | Note-on sweep **added to 1FRQ**. Higher is faster and deeper. 0 adds nothing. | A-7, “speed and depth of the exponential envelope… added to 1FRQ” |
| 3 | 1VOL | 0–127 | Output level of modulator 1. From knob 80 upward, amplitude feedback fades in (the manual says “high” and does not give the number). | A-7, “volume & feedback… high 1VOL settings” |
| 4 | 1VEN | 0–127 | Note-on sweep **added to** that level, then clipped at full. | A-7, “added to the output volume block of modulator 1” |
| 5 | 2FRQ | 0–127 | Exponential frequency of modulator 2. 64 is ratio 1. Each 16 steps is one octave. | A-7, “exponential continuous frequency control of modulator 2” |
| 6 | 2ENV | 0–127 | Level of modulator 2, the FM+ envelope figure. | A-7, “as described by the FM+ Envelope Figure”; figure on A-6 |
| 7 | 2FB | 0–127 | Feedback around modulator 2. 127 is strong but still stable. | A-7, “controls the modulator 2 feedback” |
| 8 | TUNE | −64…+63 | Fine tune of the output. Stored as 0–127, center 64 = 0 cents. Knob 0 = −100 cents, knob 127 = +98.4 cents (63 steps). | A-7 “tune of the output”, and parameter editing p. 1-25 “100 cents up or down” |

The FM+ envelope figure (A-6), used by 2ENV:

| knob | behaviour |
|---|---|
| 0 | silence |
| 32 | hold at half |
| 64 | hold at full |
| 96 | decay from full, a fraction of a second |
| 127 | a few milliseconds |

1FRQ and 2FRQ are continuous. They do not use the listed-ratio table (that
table is for FM+PARALLELL). The sine they read can still be swapped; see
INTERFACE.md.

## Cost

Measured on the SHARC simulator (instruction counts, not stall cycles). One
sounding voice, 32 samples:

| | instructions |
|---|---|
| note-on block | 2,311 |
| later blocks | 2,272 |
| voice freed (`active` = 0) | 114 |

Sixteen sounding voices are about **37k** instructions. The rest of a block
with no engines is about 154k (`sharc.md`), so a full block of this machine
is about **191k**. A stock block full of FM TONE is about 318–321k. The sine
table and the curves sit in L2, not DDR. The voice buffer write is the same
one the stock engine already does.

Default output gain is 1 (a full-scale carrier, clipped to ±gain). It is
state word 11, not a SYN knob. Set it by ear against FM TONE once the hook
is on the unit; stock engines do not all use the same internal scale.

## Listen, and A/B with a Monomachine

```bash
python3 engines/fm_dynamic/reference.py              # examples/*.wav
python3 engines/fm_dynamic/test_engine.py
```

The WAVs are the reference model, normalized to peak 0.5 so a laptop can play
them. `sweep` is the frequency and level sweeps, `feedback` is high 1VOL and
2FB, `held` sits in the hold half of the envelope figure.

To compare with the instrument: same note, same eight numbers (TUNE on the
Monomachine is the −64…+63 display). Open the amp (ATK 0, HOLD 127, DEC 127,
REL 0), keep the filter from closing the sound down, distortion 0, delay send
0. Record a few seconds and play it next to the WAV.

If the decay is too fast or the sweep is too wide, the constants at the top
of `engines/fm_common.py` are the ear-tune (`ENV_TAU_FAST`, `FEN_DEPTH_MAX`,
`BETA`, `VOL_FB_KNEE`, `FB_MAX`). If 1FRQ on the real machine does **not**
follow the keyboard, set `LINEAR_TRACKS_NOTE = False` and rebuild: 1FRQ then
runs in Hz up to `LINEAR_HZ_MAX`. The manual’s example screen shows “1.0”
beside “1.33”, which is why the default is a ratio.

A local sine table (and, for the other engine, a ratio list) can be loaded
at build time. Format, and the “do not commit this” rule, are in
INTERFACE.md.

```bash
python3 engines/fm_dynamic/reference.py --tables /path/to/mine.fm2t
```
