# SWAVE-SAW

A from-scratch SuperWave saw for the Digitone II. It follows the Monomachine
SWAVE-SAW synthesis page and stops there: no amp envelope and no filter. The
DN2’s own filter and amp sit downstream.

Manual: Elektron, *Monomachine User’s Manual*, OS 1.32,
[PDF](https://www.elektron.se/wp-content/uploads/2024/09/monomachine_manual_OS1.32.pdf).
Appendix A pp. A-1–A-2 are PDF pages 125–126. The tune sentence is on p. 25.
The eight DATA ENTRY knobs are described on p. 10.

## Knobs

The manual lists these in knob order. Knob 8 is empty: a knob with no name
does nothing (p. 10). Every value is the usual 0–127 MIDI control (Appendix B,
synth parameter 1 is CC 48).

| Knob | Abbr | Range | What it does | Manual |
|---|---|---|---|---|
| 1 | UNIL | 0–127 | Level of the saw pair, one above the base pitch and one below. 0 is off. | A-1 |
| 2 | UNIW | 0–127 | How far that pair sits from the base pitch. 0 is none. | A-1 |
| 3 | UNIX | 0–127 | Level of a second pair at twice the UNIW distance. It cannot get louder than UNIL, so UNIL has to come up first. | A-1 |
| 4 | SUBX | 0–127 | Square wave, one octave down. | A-2 |
| 5 | SUB1 | 0–127 | Sine, one octave down. | A-2 |
| 6 | SUB2 | 0–127 | Sine, two octaves down. | A-2 |
| 7 | TUNE | 0–127 | Fine tune, −100 cents at 0, 0 cents at 64, +100 cents at 127. | p. 25, A-2 |
| 8 | — | — | Unused. | p. 10 |

With every knob at its lowest value you hear only the base saw. TUNE at 0 is
still that saw, 100 cents flat. Center TUNE (64) if you want concert pitch.

Levels are linear (knob / 127). UNIW uses a squared curve so the bottom half
of the knob is a chorus and the top opens up. Full UNIW is **700 cents**
(a fifth). The extended pair is at twice that distance, in cents. Both of
those numbers are in `engines/swave_common/law.py` (`UNIW_MAX_CENTS`) and are
the first things to change after an A/B.

## How the sound is made

Eight oscillators, which is the machine the manual describes:

1. base saw
2. unison saw, up
3. unison saw, down
4. extended saw, up
5. extended saw, down
6. square sub
7. sine sub, −1 octave
8. sine sub, −2 octaves

Each one reads a band-limited cycle (a Fourier series written for this repo,
not a dump of anything). A mip is chosen from the pitch so the top harmonic
stays under Nyquist. The cycles can be swapped at build time; see
`engines/INTERFACE_swave.md`.

The voice buffer is clipped (it saturates, it does not wrap) and then scaled
by `out_gain` in the state block. Default gain is 1. A full stack of eight
can peak around ±8 before that gain. Do not invent a makeup gain to match a
stock DN2 machine until you have measured one.

## What it costs

Measured on the assembled kernel, one sounding voice, one 32-sample block.
An idle voice (flag bit 0 clear) only clears the buffer, about 100
instructions, and returns.

| Piece | Instructions |
|---|---|
| One plain oscillator (16-instruction loop × 32 samples) | 512 |
| Eight oscillators | about 4,100 |
| Pitch, detune, mip pick, clear, saturate | the rest |
| **Sounding voice, everything** | **5,345** |

Each plain oscillator also touches the voice buffer 64 times (read and write,
32 samples). That buffer is DDR. The waveform table should live in L2.

Stock Digitone audio is about 318–321k instructions for a block of 16 FM TONE
voices, and about 154k with no engines. Sixteen of these saws is 16 × 5,345 ≈
**85k** instructions, plus 16 × 608 DDR buffer accesses. If you budget a harsh
8 extra cycles per DDR access, sixteen voices land on the ceiling. **Use 12
sounding voices** until a load reading on the unit says otherwise:

12 × 5,345 + 8 × 12 × 608 ≈ 123k, and 123k + 154k ≈ 277k, under the stock total.

## A/B on a real Monomachine

Record the Monomachine dry: filter open, long amp decay, no delay, one note
(A2, 110 Hz is what `examples/bare.wav` uses). Move one knob at a time.

1. All knobs down, TUNE centered. You should hear one saw. Compare with `examples/bare.wav`.
2. Raise UNIL, then UNIW. The pair should open evenly up and down, not both sharp.
3. UNIX should stay silent until UNIL is up, then sit twice as far out.
4. SUBX is a square one octave down; SUB1 and SUB2 are sines.
5. TUNE at the ends should be a semitone flat and a semitone sharp.

If the width feels wrong, change `UNIW_MAX_CENTS` only. If the middle of a
level knob is too loud or too quiet, change `level()` in `law.py`. The
example WAVs are normalized so you can hear them; the engine is not.

## Files

- `model.py` — the reference renderer
- `sharc.py` — assembles the SHARC kernel. It loads `SWAVE_WAVE_TABLE` when that variable is set
- `test_swave_saw.py` — reference checks, then the kernel against the reference
- `examples/` — short listening files
