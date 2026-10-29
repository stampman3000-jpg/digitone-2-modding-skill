# SuperWave engines — interface

Three new Digitone II machines: **SWAVE-SAW**, **SWAVE-PULSE**, **SWAVE-ENS**.
They copy the Monomachine synthesis page (Elektron, *Monomachine User’s
Manual*, OS 1.32, Appendix A). They do not replace a stock machine.

Stock machine ids, from the frame (`firmware.md`):

| Id | Machine |
|---|---|
| 0 | FM TONE |
| 1 | WAVETONE |
| 2 | FM DRUM |
| 3 | SWARMER |
| 4 | MIDI |

These engines use new ids:

| Id | Machine | Entry | State phases |
|---|---|---|---|
| 5 | SWAVE-SAW | `swave_saw_entry` | 8 |
| 6 | SWAVE-PULSE | `swave_pulse_entry` | 5 |
| 7 | SWAVE-ENS | `swave_ens_entry` | 8 |

Nothing in this tree writes ids 0–4, and nothing patches the stock dispatch
table entries for them (`0x8052db90`). A voice whose frame machine id is 0–4
is left completely alone: engine word, voice buffer, and parameters.

## Where it hooks

The stock render loops (FM TONE, WAVETONE, FM DRUM) each test the voice’s
engine word at `0x2554b8 + 564*v + 436`. That word is rewritten every block
by `0x1c2997`. The value **4** matches none of those loops (it is also what a
MIDI voice carries, because MIDI has no oscillator). It is a skip sentinel,
not a request to become the MIDI machine.

After `0x1c2997`, for each voice:

1. Read the frame machine id (the field at frame `+0x94`, per voice).
2. If it is 0, 1, 2, 3, or 4: do nothing.
3. If it is 5, 6, or 7:
   - store 4 into that voice’s engine word, so the stock loops skip it;
   - call the matching entry below.

Do not do this by overwriting a stock table slot. The stock table is only
five machines wide; a new index would read off the end of it. Run a separate
loop, gated on ids 5–7, beside the stock loops.

Call:

```
R4 = state pointer
R12 = voice buffer pointer     (the stock mono buffer, 0x804acf90 + 128*v)
```

32 samples, implicit. The entry moves R4→I0 and R12→I1 and falls into the
kernel. The kernel clobbers R0–R15, I0–I4, and M4. Save whatever the stock
code after the hook still reads.

The waveform block’s **byte address** is state word 11 (`W_TAB`), not a third
argument. Point it at L2 (or any RAM you filled first). Never point it at
DDR you have not written: power-on DDR is garbage and a NaN there will not be
stopped by MIN/MAX/CLIP.

Suggested placement, in the free L2 window (`0x20090000`–`0x200B0000`):

- code at `0x20090000` (short-word `0xBC8000`), one engine or all three
- waveform block + per-voice state at `0x20098000` upward

The default waveform block is 9,420 float32 words, about 37 KB. Three
kernels together are about 20 KB of code. State is `13 + nphase` words per
voice (see below), times 16.

## ColdFire side — its own SYN page

The eight knobs are a new synthesis page for machine ids 5, 6, and 7. Do not
reuse the FM TONE / WAVETONE / FM DRUM / SWARMER / MIDI page handlers, and do
not borrow one of their parameter slots. Stock UI code refuses new slots
(`slot <= 100` in several places); a new page needs its own handler.

Each block, the ColdFire side copies the eight raw knob values (0–127) and
the note frequency in hertz into the state block below. It does not ask the
DSP to read a stock machine’s parameter layout. Knob order is the Monomachine
order, which is the DATA ENTRY order (manual p. 10 and Appendix A):

**SAW:** UNIL, UNIW, UNIX, SUBX, SUB1, SUB2, TUNE, (unused)

**PULSE:** UNIL, UNIW, SUB1, SUB2, PW, PWAD, PWRS, TUNE

**ENS:** PCH2, PCH3, PCH4, WAVE, PW, CHRL, CHRW, TUNE

Per-knob behaviour, ranges, and the manual line they come from are in each
engine’s README.

`out_gain` (state word 2) is how loud the voice buffer is before the stock
filter. Leave it at 1 until you have measured a stock engine’s buffer on the
unit or in the emulator. These oscillators peak around ±1 each, and a full
saw stack can reach the mix clip at ±12. There is no hidden makeup gain.

Note-on: set flag bit 1 only on the block where the frame’s note-on mask has
this voice. PWRS uses that bit to restart the pulse sweep. The engine does
not clear it; the next block’s copy from the ColdFire does.

Flag bit 0 clear means the voice is free (not in release). The engine writes
32 zeros and returns. During release, leave bit 0 set: the DN2 amp is what
fades the note.

## State block

Words are 32-bit. Floats are IEEE-754. Integers are the raw knob or a pointer.

| Word | Type | Name |
|---|---|---|
| 0 | int | flags. bit 0 = sounding, bit 1 = note-on this block |
| 1 | float | freq_hz, before TUNE |
| 2 | float | out_gain. Use 1.0 until measured |
| 3–10 | int | knobs 1–8, raw 0–127 |
| 11 | int | byte address of the waveform block |
| 12 | float | pulse-sweep phase, 0–1 (PULSE only; the others ignore it) |
| 13… | float | oscillator phases, one per oscillator |

Phases free-run. The manual only says the pulse *sweep* restarts, so the
audio oscillators are not reset on note-on. If a recording shows they do
restart, zero the phase words in the hook on note-on and leave the kernel.

## Waveform block

Built by `WaveSet.flat_words()` in `engines/swave_common/tables.py`.

| Words | Contents |
|---|---|
| 0–63 | float32 `2^(n/12)` for n = 0..63 |
| 64–67 | just ratios 6/5, 5/4, 4/3, 3/2 |
| 68–131 | float32 `2^(-n/12)` |
| 132… | cycles |

Cycles are groups of 6 mips. Each mip is **129** float32 samples: 128 plus a
copy of sample 0 so the interpolator can read index and index+1 with no
branch. Harmonic limits, brightest mip first: **64, 32, 16, 8, 4, 1**. The
oscillator picks the brightest mip whose top harmonic is still under
Nyquist (`increment * harmonics < 0.5`).

Order of the groups: saw, sine, square, then one group per pulse duty.
Default duties: 1/32, 1/8, 1/4, 3/8, 1/2, 5/8, 3/4, 7/8, 31/32.

The defaults are Fourier series computed in `tables.py`. They are not
extracted from anything.

### Swapping the table at build time

Set `SWAVE_WAVE_TABLE` to a path, or pass `--wave-table PATH` to
`render_wav.py` / `python3 engines/swave_common/tables.py`. The SHARC duty
compares are baked from the file’s duty list when you call `sharc.build()`.
The samples themselves are not baked into the code; copy `flat_words()` into
the data block and point state word 11 at it.

Two file shapes. Both are gitignored (`*.swave.json`, `*.swave.f32`, and
anything under `engines/local/`). Do not commit a table you made from a
Monomachine OS image. This repo does not contain an extractor and should not
gain one.

**JSON** (`version` 1):

```json
{
  "version": 1,
  "waves": {
    "saw": [0.0, 0.1],
    "sine": [0.0, 1.0],
    "square": [1.0, -1.0],
    "pulse": {
      "duties": [0.5],
      "cycles": [[1.0, -1.0]]
    }
  }
}
```

A wave may be one cycle of any length (the loader drops harmonics above each
mip and resamples to 128), or a finished stack of 6 cycles of length 128 or
129. `saw`, `sine`, `square`, and `pulse.duties` / `pulse.cycles` are all
required.

**Raw little-endian** (`SWV1`):

| Offset | Type | Meaning |
|---|---|---|
| 0 | 4 bytes | `SWV1` |
| 4 | u32 | version = 1 |
| 8 | u32 | length = 128 |
| 12 | u32 | mip count = 6 |
| 16 | u32 | number of pulse duties |
| 20 | u32 | flags, bit 0 = guard sample present |
| 24 | u32 × 6 | harmonic limits 64, 32, 16, 8, 4, 1 |
| then | f32 × duties | the duty of each pulse slot |
| then | f32 | saw mips, sine mips, square mips, pulse mips |

Each mip is `length` samples, or `length + 1` if the guard flag is set.
This build rejects any other length or harmonic list: the kernel’s address
math is fixed.

`python3 engines/swave_common/tables.py --dump-json out.swave.json` writes
the defaults so you can see a valid file. That file is gitignored.

## Cost (already measured)

Per sounding voice, per 32-sample block, active path, from the assembler:

| Engine | Instructions | Plain osc | Voices to try |
|---|---|---|---|
| SAW | 5,345 | 512 (16 × 32) | 12 |
| PULSE | 3,545 | 512 | 16 |
| ENS | 5,986 | 512, or 640 for the offset saw | 12 |

The “voices to try” column keeps a full stack under the stock ~318–321k
block total even if every voice-buffer DDR access costs 8 extra cycles.
Details are in each README. Idle voices are the cheap path.

## Listening files

`examples/` under each engine. They are faded and normalized so a speaker
can play them. The engine output is not.
