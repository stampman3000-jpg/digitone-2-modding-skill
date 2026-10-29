# FM+PARALLELL

A new Digitone II machine (id **6**). It does not replace FM TONE, WAVETONE,
FM DRUM, SWARMER, or MIDI. How it plugs in: [`../INTERFACE.md`](../INTERFACE.md).

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
| 2 | 1ENV | 0–127 | Level of modulator 1, FM+ envelope figure. | A-7; figure on A-6 |
| 3 | 2FRQ | 0–127 | Listed frequency of modulator 2. | A-7 |
| 4 | 2ENV | 0–127 | Level of modulator 2. | A-7; figure on A-6 |
| 5 | 3FRQ | 0–127 | Listed frequency of modulator 3. | A-7 |
| 6 | 3ENV | 0–127 | Level of modulator 3. | A-7; figure on A-6 |
| 7 | TONE | 0–127 | Gain and a bit of extra harmonic on the summed modulators, before the carrier. Low is dark, high is bright. | A-7, “high settings introduce more high frequency harmonic contents” |
| 8 | TUNE | −64…+63 | Fine tune of the output. Stored as 0–127, center 64 = 0 cents. Knob 0 = −100 cents, knob 127 = +98.4 cents. | A-7, and parameter editing p. 1-25 |

Envelope figure (A-6): 0 silence, 32 hold at half, 64 hold at full, above 64
a decay from full that gets shorter toward 127.

## Default ratio list

The manual does not print the 128 entries. The screens show ratios such as
1/2, 1, and 2, so the default is an original list of FM-useful fractions,
four knobs each, with those three in it. Replace the whole list from a file
you make locally (INTERFACE.md). Do not commit that file.

| knobs | ratio | knobs | ratio | knobs | ratio | knobs | ratio |
|---|---|---|---|---|---|---|---|
| 0–3 | 1/8 | 32–35 | 2/3 | 64–67 | 7/4 | 96–99 | 7 |
| 4–7 | 1/6 | 36–39 | 3/4 | 68–71 | 2 | 100–103 | 8 |
| 8–11 | 1/5 | 40–43 | 4/5 | 72–75 | 5/2 | 104–107 | 9 |
| 12–15 | 1/4 | 44–47 | 1 | 76–79 | 3 | 108–111 | 10 |
| 16–19 | 1/3 | 48–51 | 5/4 | 80–83 | 7/2 | 112–115 | 12 |
| 20–23 | 2/5 | 52–55 | 4/3 | 84–87 | 4 | 116–119 | 16 |
| 24–27 | 1/2 | 56–59 | 3/2 | 88–91 | 5 | 120–123 | 20 |
| 28–31 | 3/5 | 60–63 | 5/3 | 92–95 | 6 | 124–127 | 24 |

## Cost

Measured on the SHARC simulator (instruction counts, not stall cycles). One
sounding voice, 32 samples:

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

Decay time and brightness that you want to nudge live in
`engines/fm_common.py` (`ENV_TAU_FAST`, `BETA`, `TONE_G0`, `TONE_H`). The
listed ratios and the sine are the swappable file:

```bash
python3 engines/fm_parallel/reference.py --tables /path/to/mine.json
```

`DN2_FM_TABLES` is the same path when you assemble the kernel. Format is in
INTERFACE.md. Leave the file out of git.
