# SWAVE-PULSE

A from-scratch SuperWave pulse. Same rules as the saw: synthesis page only,
DN2 filter and amp downstream.

Manual: Elektron, *Monomachine User’s Manual*, OS 1.32, Appendix A p. A-2
(PDF p. 126). Tune is on p. 25. Eight knobs: p. 10.

## Knobs

| Knob | Abbr | Range | What it does | Manual |
|---|---|---|---|---|
| 1 | UNIL | 0–127 | Level of the pulse pair above and below the base pitch. | A-2 |
| 2 | UNIW | 0–127 | Distance of that pair. Same 700-cent squared law as the saw. | A-2 |
| 3 | SUB1 | 0–127 | Sine, one octave down. | A-2 |
| 4 | SUB2 | 0–127 | Sine, two octaves down. | A-2 |
| 5 | PW | 0–127 | Pulse width. Raw 64 (the screen’s 0) is a square. The ends are spikes, not silence. | A-2 |
| 6 | PWAD | 0–127 | Sweep speed. 0 freezes the width at PW. Full scale is 20 Hz. | A-2 |
| 7 | PWRS | 0 or 1–127 | 0 leaves the sweep running. Any other value restarts it from PW on a note-on. | A-2 |
| 8 | TUNE | 0–127 | −100 / 0 / +100 cents, same as every other machine. | p. 25 |

The manual says the center value “gives a square form, and the higher and
lower settings turn the waveform towards a spike.” PWAD “turns off the pulse
sweep” at zero and “the pulse sweep speed increases” as it goes up. PWRS
“restart[s] the pulse sweep … from the PW position each time a note is played.”

Five oscillators: base pulse, unison pair, two sines. The three pulses share
one width. The width is chosen once per 32-sample block, because the table
pointer cannot change inside the hardware loop. At the top sweep speed
(20 Hz) that is a small step, about 0.7 ms.

## What it costs

| Piece | Instructions |
|---|---|
| One plain oscillator | 512 per block |
| Five oscillators plus the sweep math | **3,545** per sounding voice |

Sixteen voices: 16 × 3,545 ≈ **57k** instructions. Voice-buffer traffic is
416 DDR accesses a voice. With a harsh +8 cycles each, sixteen voices are
about 110k plus the 154k of the rest of the chain, near 264k, under the
318–321k stock FM TONE total. **16 sounding voices** is the number to try.

Idle voices clear the buffer and return.

## A/B

`examples/square.wav` is PW centered, everything else down, 110 Hz.
`examples/pwm.wav` is a slow sweep that restarts on the note.
`examples/spike.wav` is PW at 0.

On the Monomachine, center PW should be hollow (odd harmonics). The ends
should thin out to a spike and stay audible. If the sweep is too slow or too
fast, change `PWAD_MAX_HZ` in `law.py`. If a real PWRS knob only has two
dents, the code already treats 0 as off and anything else as on.

Width and level use the same constants as the saw (`UNIW_MAX_CENTS`,
`level()`).
