# Slotting an engine in

FM+DYNAMIC and FM+PARALLELL are new Digitone II machines. They do not replace
FM TONE, WAVETONE, FM DRUM, SWARMER, or MIDI, and they do not replace the
FM+STATIC machine that is already shipped as type 5. A super-wave engine
should use the same shape: its own machine id from 8 upward, its own 8 SYN
knobs, its own state, and the same hook.

This repo does not contain Elektron firmware. Addresses below are the ones
recorded in `skills/digitone-2-modding-skill/references/sharc.md` and
`coldfire.md` for OS 1.11. Confirm them on your own disassembly before a flash.
The displaced instruction at the hook is checked at build time against your
own OS image (`dspblocks.call_hook`); it is not stored here.

Manual for the sound: Elektron, *Monomachine User's Manual* OS 1.32,
<https://www.elektron.se/wp-content/uploads/2024/09/monomachine_manual_OS1.32.pdf>,
appendix A pages A-6 and A-7.

## Machine ids

| id | machine | who renders it |
|---|---|---|
| 0 | FM TONE | stock |
| 1 | WAVETONE | stock |
| 2 | FM DRUM | stock |
| 3 | SWARMER | stock |
| 4 | MIDI | stock (no oscillator loop) |
| 5 | FM+STATIC | shipped custom firmware, not this repo. Hook passes through |
| 6 | FM+DYNAMIC | `engines/fm_dynamic` |
| 7 | FM+PARALLELL | `engines/fm_parallel` |
| 8+ | super-wave | reserved, pass through |

`engines/hook.py` `decide` is the rule, and it is tested: ids 0–5, 8 and above,
and anything else pass through untouched. Only 6 and 7 are ours. Do not widen
that into "anything ≥ 5", or the shipped static machine (and later a
super-wave) would skip the stock loops and play nothing.

On the ColdFire side the stock code only accepts ids 0–4 (`machine + 1 < 6` at
`0x400dd2ae`, `type <= 4` accessors, machine list `{0,2,1,3,4}` at
`0x401ddd58`). Extending that bound and appending descriptors is what adds a
machine. Overwriting an entry in that list, or reusing ids 0–4, is not.

The SYN page is the normal eight encoders. When the selected machine is 6 or
7 the page shows that machine's names (see each engine README). FM TONE's
handlers stay on FM TONE. New parameter-table records are appended
(`coldfire.md`, `paramtable.relocate`), not written over the stock ones.

## What the DSP hook does

Stock already copies the frame's machine id into the voice's engine word
every block (`0x1c2997` writes `0x2554b8 + 564*voice + 436`). The oscillator
loops at `0x1c93e5..0x1c9447` then render whichever stock machine that word
names. The dispatch jump is at `0x1c90a6` (table `0x8052db90`, M4 = index),
which is after the copy and before those loops.

Hook that one instruction with a CALL. The routine:

1. Saves R0–R15, I0–I4, and M4 (the same save the track-trim example uses).
2. Reads the machine id. It does not change it.
3. If the id is not 6 or 7, restores registers and **replays the original
   jump**, so stock dispatch is unchanged. Return. Type 5 (shipped
   FM+STATIC) takes this path.
4. If the id is 6 or 7:
   - point R4 at **our** state, `0x20098000 + voice*512`, not the stock engine
     state at `0x2495e0`;
   - point R12 at the voice buffer the stock render already uses
     (`0x804acf90 + 128*voice`, or whatever register the disassembly already
     holds — prefer that register);
   - call `fm_dyn` or `fm_par` (`render(I4=state, I5=buffer)`, 32 samples);
   - store **4** into that voice's engine word so the stock oscillator loops
     do not also render it.

The 4 is the value those loops already treat as "no stock oscillator" (MIDI
uses it too). We write it only after our render, and only on a voice whose
machine id is already 6 or 7. A SWARMER voice, a WAVETONE voice, a MIDI
voice, and the shipped FM+STATIC voice never take this branch, and the
dispatch table itself is not edited.

`hook.build_addrs` computes the three addresses with shifts (564 = 2⁹+2⁵+2⁴+2²,
state stride 512, buffer stride 128). It matches `fm_common.engine_word_addr`,
`state_addr`, and `voice_buf_addr` for voices 0–15.

Before flashing, check that the instruction after `0x1c90a6` is where a stock
prep returns, and that the hooked instruction is a single 48-bit jump with no
delay slot you still need. `call_hook` will refuse the site if the bytes are
not the ones you pass in from your own image.

The voice manager sets `active` (state word 0) to 0 when it frees the voice.
The engine then writes silence and returns. It does not clear `active` by
itself: a bare carrier is a valid sound, and the DN2 amp envelope is
downstream. Set `trig` (word 1) on the note-on block; the engine clears it,
zeros the phases, and sets `active`.

## State (128 words, 512 bytes, one per voice)

Words are little-endian. Knobs are integers 0–127 (the frame's raw value is
`knob<<8 | fine`; store `raw>>8`). The hook fills 0–12. The engine owns the rest.

| word | name | |
|---|---|---|
| 0 | active | 0 = idle early-out, 1 = render |
| 1 | trig | 1 on the note-on block |
| 2–9 | knobs | encoder 1..8, meaning depends on the machine |
| 10 | note Hz | float, already the played note |
| 11 | out gain | float, default 1 (not a SYN knob; see below) |
| 12 | table pointer | byte address of the packed sine/ratio blob |
| 13–16 | carrier, mod1, mod2, mod3 phase | float cycles |
| 17–19 | env1, env2, env3 | FM+ envelope state |
| 20–21 | fen, ven | dynamic sweeps (parallel reuses these for TONE) |
| 22–24 | feedback memory | |
| 25–31 | per-engine scratch | |
| 32–63 | modulator sum | 32 floats |
| 64–127 | dynamic mod-1 inc and level | 32 + 32 floats |

L2 data for this starts at `0x20098000` (inside the free window up to
`0x200B0000`). Sixteen voices use 8 KiB. The table blob follows them at
`0x2009A000`. Do not put the sine table in DDR.

Output is a sine clipped to ±`out gain`, so a runaway saturates instead of
wrapping. Default gain is 1, a full-scale carrier. Stock engines hit the
filter at their own scale (SWARMER is huge; the pre-filter bus is nearer
±0.1). Gain is the one number to set by ear when the hook is wired, against
a stock FM TONE note at the same amp settings. It is not a ninth SYN knob.

## Standalone FM+PAR state

The C engine in `engines/fm_parallel/fm_par.c` is the reference DSP for type
7. Its voice is **52 bytes** (16 voices = 832 bytes), laid out in `fm_par.h`.
Curves are one table per knob in `fm_par_curves.h`, placeholders to fit by
ear. It uses `sinf`, not the sine table below, and it does not load a ratio
file. The 512-byte slot above is the assembler kernel's working memory.

## Sine and listed-ratio tables

Built-in defaults live in `fm_common.py` (a 2048-point sine, and 128 listed
ratios). No Monomachine image is read, and nothing extracted from one belongs
in this repo.

At build time, a local file can replace the sine, the ratio list, or both.
The reference model and the SHARC blob load the same file, so a WAV rendered
with `--tables` matches the kernel you assemble with that file.

```
python3 engines/fm_parallel/reference.py --tables /path/to/mine.fm2t
python3 engines/fm_dynamic/reference.py --tables /path/to/mine.json
```

If `--tables` is omitted, `DN2_FM_TABLES` is used. If that is unset, the
built-ins are used. FM+DYNAMIC's 1FRQ and 2FRQ are continuous laws, not this
list. The SHARC FM+PARALLELL sketch can index it. The standalone FM+PAR
engine does not: its 24 musical steps live in `fm_par_curves.h`. FM+STATIC
is type 5, already shipped, and is not built here.

Do not commit the file. `.gitignore` ignores `*.fm2t`, `fm-tables.json`, and
`external-tables/`. If `git status` shows your table, leave it out of the commit.

### JSON

UTF-8 object. `version` is optional. You may give either array, or both.
Missing `sine` keeps the built-in sine; missing `ratios` keeps the built-in list.

```json
{
  "version": 1,
  "sine": [0.0, 0.003, "... one cycle, length a power of two ..."],
  "ratios": [0.125, "... exactly 128 carrier-relative ratios ..."]
}
```

### Raw little-endian (`*.fm2t`)

| offset | type | |
|---|---|---|
| 0 | 4 bytes | magic `FM2T` |
| 4 | uint32 | version `1` |
| 8 | uint32 | sine length |
| 12 | uint32 | ratio count, must be 128 |
| 16 | float32[sine] | one cycle, index 0 = sin(0) |
| 16+4*sine | float32[128] | ratio for knob 0..127 |

Sine length is a power of two from 64 to 4096 (the mask in the oscillator is
`length-1`, and 4096 still fits in L2 next to the voice state). Samples must
be finite and within ±1.25. Ratios must be finite and in 0..64. Files over
1 MB are refused. `fm_common.load_table_file` / `dump_raw` / `active_tables`
implement this. The loader never opens an OS image; you produce the floats
locally however you like.

Other curves (the FM+ envelope, 1FEN, TONE, tune) are not in the file. They
are the named constants at the top of `fm_common.py`. Change those, then
re-render and re-assemble.

## FM+STATIC and super-wave

FM+STATIC is type 5 and already shipped in the custom firmware. This repo
does not implement it, and `decide` does not claim id 5. Super-wave machines
are types 8 and above. Same rule as above: a new id is one more equality
test, never a `>=` range. Screen order on manual page A-6, for reference
only: 1FRQ, 1FIN, 1ENV, 1FB, 2FRQ, 2VOL, TONE, TUNE.
