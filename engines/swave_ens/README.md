# SWAVE-ENS

A from-scratch SuperWave ensemble. Up to four notes from one voice, each note
a pair of saws. No amp, no filter.

Manual: Elektron, *Monomachine User’s Manual*, OS 1.32, Appendix A p. A-2
(PDF p. 126).

## Knobs

| Knob | Abbr | Range | What it does | Manual |
|---|---|---|---|---|
| 1 | PCH2 | 0–127 | Second note. 0 is OFF. | A-2 |
| 2 | PCH3 | 0–127 | Third note. 0 is OFF. | A-2 |
| 3 | PCH4 | 0–127 | Fourth note. 0 is OFF. | A-2 |
| 4 | WAVE | 0–127 | With PW centered, this runs the tone from saw to square. | A-2 |
| 5 | PW | 0–127 | Center (raw 64, screen 0) keeps WAVE in the saw-to-square range. Off center it pushes toward a spike or back to a saw. | A-2 |
| 6 | CHRL | 0–127 | Level of the second saw. 0 locks it to the morph and, if the morph does not need it, silences it. | A-2 |
| 7 | CHRW | 0–127 | Detune of that second saw, only while CHRL is up. Full scale is 40 cents, squared. | A-2 |
| 8 | TUNE | 0–127 | −100 / 0 / +100 cents on every note. | p. 25 |

The manual’s example: play C-4 with PCH2 = 4, PCH3 = 7, PCH4 = OFF and you
hear C, E, G. Those numbers are the knob values. Raw 1–63 are +1..+63
equal-tempered semitones, raw 64–123 are −1..−60, and raw 124–127 are the
just ratios the manual names, in this order: **6/5, 5/4, 4/3, 3/2**. The
manual does not say where those four sit on the knob. This placement keeps
“4” and “7” meaning a third and a fifth. If the screen on your machine shows
them somewhere else, only `pch_ratio()` in `law.py` has to change.

Defaults (PCH off, WAVE down, PW centered, chorus off) are one saw, which is
what the manual says.

## How the two saws make the waveform

The manual says the ensemble waveforms “are constructed from two saw tooth
oscillators” and run “from saw tooth through square to spikes.” Each note is:

- saw A, at the note
- saw B, subtracted, read at a phase offset

Offset of half a cycle and full level is a square. A small offset is a spike.
Gain 0 leaves only saw A. CHRL can bring saw B in even on a plain saw, and
CHRW then detunes it. That is the chorus, and it is why the machine tops out
at eight oscillators (four notes × two saws) rather than a second copy of
everything.

40 cents (`CHRW_MAX_CENTS`) is a guess. Chorus on the real machine may be
wider, or it may be a separate copy of the whole chord. Listen, then change
that one constant. A separate copy would mean more oscillators and fewer
voices (see below).

## What it costs

| Piece | Instructions |
|---|---|
| Plain saw read | 512 per block |
| Second saw (phase offset) | 640 per block |
| **Sounding voice, four notes, both saws** | **5,986** |

The kernel always runs all eight reads. A note that is OFF multiplies by zero;
it does not get cheaper. Sixteen voices would be about 96k instructions and,
with a harsh +8 cycles on each DDR buffer access, over the 318–321k stock
total once you add the rest of the chain (~154k). **Use 12 sounding voices**:

12 × 5,986 + 8 × 12 × 608 ≈ 130k, plus 154k ≈ 284k.

## A/B

`examples/single.wav` is the default, C3.
`examples/major.wav` is PCH2 = 4, PCH3 = 7 (C major).
`examples/just.wav` is raw 127 and 125 (3/2 and 5/4).
`examples/chorus.wav` is a saw with CHRL and CHRW up and WAVE part way.

On the Monomachine, confirm the on-screen PCH numbers against this table
before chasing the tone. Then the chorus width.
