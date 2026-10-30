# FM+PARALLELL

A new Digitone II machine (id **7**). It does not replace FM TONE, WAVETONE,
FM DRUM, SWARMER, MIDI, or the shipped FM+STATIC (id **5**). How it plugs in: [`../INTERFACE.md`](../INTERFACE.md).

The sound follows Elektron’s *Monomachine User’s Manual* OS 1.32, appendix A
page **A-7** (FM+PARALLELL “FM+PAR”) and the FM+ envelope figure on page
**A-6**.
<https://www.elektron.se/wp-content/uploads/2024/09/monomachine_manual_OS1.32.pdf>

The manual calls it three copies of the most efficient FM+ structure. The
diagram is three modulators, each with a listed frequency and an FM+ envelope,
summed, then TONE, then one carrier. The DN2 filter and amp stay downstream.

Knob order is that screen, left to right, top row then bottom row. The prose
says “1-3FRQ” then “1-3ENV”; the screenshot pairs each frequency with its
envelope, and that is the encoder order used here. LEV is the track level
knob, not one of these eight.

| knob | name | range | what it does | manual |
|---|---|---|---|---|
| 1 | 1FRQ | 0–127 | Listed frequency of modulator 1. | A-7, “listed frequencies for Modulator 1–3” |
| 2 | 1ENV | 0–127 | Modulator 1 amount. Placeholder peaks around 72–83 and folds back after about 94. | A-7 |
| 3 | 2FRQ | 0–127 | Listed frequency of modulator 2. | A-7 |
| 4 | 2ENV | 0–127 | Modulator 2 amount, same shape as 1ENV until fitted. | A-7 |
| 5 | 3FRQ | 0–127 | Listed frequency of modulator 3. This one dominates brightness. | A-7 |
| 6 | 3ENV | 0–127 | Modulator 3 amount, same shape as 1ENV until fitted. | A-7 |
| 7 | TONE | 0–127 | Brightness of the summed modulators, before the carrier. Placeholder flattens from about 100. | A-7, “high settings introduce more high frequency harmonic contents” |
| 8 | TUNE | −64…+63 | Fine tune of the output. Stored as 0–127, center 64 = 0 cents. Knob 0 = −100 cents, knob 127 = +98.4 cents. | A-7, and parameter editing p. 1-25 |

The manual’s envelope figure (A-6) draws holds and a decay. The standalone
engine does not copy that drawing. ENV amount is the fold-back placeholder
in `fm_par_curves.h`, to be replaced by ear.

## Standalone engine

`fm_par.c` and `fm_par_ref.py` are the DSP. Sine is `sinf`. There is no
wavetable and no ratio file. Every knob is one small table in
[`fm_par_curves.h`](fm_par_curves.h). That header is the file to edit when
fitting by ear. Do not commit measured sweeps.

The placeholder shapes, not measured heights:

- **1FRQ, 2FRQ, 3FRQ** — 24 musical ratios, the same simple list as FM+STATIC: 1/64, 1/32, 1/16, 3/32, 1/8, 5/32, 3/16, 1/4, 5/16, 3/8, 7/16, 1/2, 5/8, 3/4, 7/8, 1, 5/4, 3/2, 7/4, 2, 5/2, 3, 7/2, 4. Knob `k` selects step `(k * 24) / 128`. Each knob has its own copy of the list.
- **3FRQ** dominates brightness. The mix is `fm_par_mod_w` (third weight largest).
- **1ENV, 2ENV, 3ENV** — amount, not a straight ramp. The placeholder peaks in the 72–83 band and folds back above about 94.
- **TONE** — one-pole brightness on the summed modulators. It flattens from about knob 100. Not a voice filter.
- **TUNE** — smooth cents, symmetric about knob 64. Knob 0 is −100 cents, knob 127 is +98.4 cents.
- **Loudness** — the carrier amplitude is only the host `out_gain`. Knobs do not scale it, so a sweep stays about the same level.

State is **52 bytes** per voice (16 voices = 832). Layout is in `fm_par.h`.

```bash
python3 engines/fm_parallel/test_fm_par.py
```

The SHARC sketch (`kernel.py`, `reference.py`) is separate. Its swappable
ratio stand-in is still the list in `fm_common.py`, not these tables.

## Cost (SHARC sketch)

Measured on the SHARC simulator (instruction counts, not stall cycles). This
is `kernel.py`, not the 52-byte C engine. One sounding voice, 32 samples:

| | instructions |
|---|---|
| note-on block | 2,972 |
| later blocks | 2,954–2,963 |
| voice freed (`active` = 0) | 131 |

Sixteen sounding voices are about **48k** instructions. With the rest of a
block that has no engines (~154k, `sharc.md`) the total is about **202k**. A
stock block full of FM TONE is about 318–321k. Sine and ratios are in L2.

Default output gain is 1, clipped to ±gain. State word 11, not a SYN knob.
Match it to FM TONE by ear when the hook is wired.

## Listen, and A/B with a Monomachine

```bash
python3 engines/fm_parallel/reference.py
python3 engines/fm_parallel/test_engine.py
```

WAVs in `examples/` are normalized to peak 0.5 for listening. `stack` is
ratios 1, 2, and 3 with decays, `bright` pushes TONE and the higher ratios,
`fifth` holds 1, 3/2, and 2.

On the Monomachine: same note, same eight numbers (TUNE is the −64…+63
display). Amp open (ATK 0, HOLD 127, DEC 127, REL 0), filter not closing the
sound, distortion 0, delay send 0. Record a few seconds and play it beside
the WAV.

What to nudge on the standalone engine is `fm_par_curves.h`: one table per
knob, plus `fm_par_mod_w` and `FM_PAR_BETA`. The heights are placeholders.
Leave measured sweeps out of git.

The SHARC sketch still has its own constants in `engines/fm_common.py`
(`ENV_TAU_FAST`, `BETA`, `TONE_G0`, `TONE_H`) and an optional local table
file. That file is not the curves header:

```bash
python3 engines/fm_parallel/reference.py --tables /path/to/mine.json
```

`DN2_FM_TABLES` is the same path when you assemble the kernel. Format is in
INTERFACE.md. Leave the file out of git.
