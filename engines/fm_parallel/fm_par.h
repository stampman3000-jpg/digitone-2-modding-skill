/* FM+PARALLELL voice, machine type 7.
 *
 * Original work (MIT, see LICENSE). Knob names and ranges follow the
 * Elektron Monomachine manual OS 1.32, appendix A page A-7. The sine is
 * the C library sine. Curves live in fm_par_curves.h (placeholders, fit
 * by ear). Nothing here is an Elektron oscillator or a measured table.
 *
 * One SYN page, eight encoders, machine-screen order. No voice amp and
 * no voice filter: those stay downstream. TONE is the manual's brightness
 * control, a one-pole on the modulator sum, not a second filter page.
 *
 *   1  1FRQ   0..127   24-step listed ratio of modulator 1
 *   2  1ENV   0..127   modulator 1 amount (peaks, then folds back)
 *   3  2FRQ   0..127   24-step listed ratio of modulator 2
 *   4  2ENV   0..127   modulator 2 amount
 *   5  3FRQ   0..127   24-step listed ratio of modulator 3 (the bright one)
 *   6  3ENV   0..127   modulator 3 amount
 *   7  TONE   0..127   brightness, saturates from about 100
 *   8  TUNE   0..127   fine tune, symmetric about 64
 *
 * Shared engine loop, one voice, no allocation:
 *
 *   fm_par_set_params(&v, knobs);
 *   if (note_on) fm_par_note_on(&v, hz);
 *   fm_par_render(&v, bus, 32);
 *
 * Call it only when the voice's machine type is FM_PAR_MACHINE_ID (7).
 * Type 5 is the shipped FM+STATIC engine: do not point this at it.
 * Stock machines are types 0..4. Super-wave starts at 8.
 *
 * Persistent state is FM_PAR_STATE_BYTES (52) per voice, little-endian
 * float32, the same endianness as the ADSP-21569. Sixteen voices are
 * 832 bytes. No sine table and no ratio file.
 *
 *   offset  bytes  field
 *   0       4      carrier phase, cycles
 *   4       12     modulator phases (3)
 *   16      12     modulator amounts (3)
 *   28      4      note Hz
 *   32      4      output gain (host scale, not a SYN knob)
 *   36      4      TONE one-pole state
 *   40      8      the eight knobs, bytes 0..127
 *   48      1      active (0 = write silence and return)
 *   49      1      trig (1 on the note-on block; the engine clears it)
 *   50      2      padding
 *
 * The carrier amplitude is only out_gain. Turning a knob does not scale
 * it, which is what keeps a sweep from riding the loudness.
 */
#ifndef FM_PAR_H
#define FM_PAR_H

#include <stdint.h>

#define FM_PAR_MACHINE_STATIC    5
#define FM_PAR_MACHINE_DYNAMIC   6
#define FM_PAR_MACHINE_ID        7
#define FM_PAR_MACHINE_SUPERWAVE 8

#define FM_PAR_N_PARAMS          8
#define FM_PAR_BLOCK             32
#define FM_PAR_STATE_BYTES       52

#define FM_PAR_SR                48000.0f
#define FM_PAR_TAU               6.283185307179586f
#define FM_PAR_DENORM_FLOOR      1.0e-20f
#define FM_PAR_OUT_GAIN_DEFAULT  1.0f
#define FM_PAR_OUT_GAIN_MAX      4.0f
#define FM_PAR_HZ_MAX            24000.0f

typedef struct FmParVoice {
    float phase_c;
    float phase_m[3];
    float env[3];
    float note_hz;
    float out_gain;
    float tone_z;
    uint8_t param[8];
    uint8_t active;
    uint8_t trig;
    uint8_t pad[2];
} FmParVoice;

_Static_assert(sizeof(FmParVoice) == FM_PAR_STATE_BYTES,
               "FM+PAR voice must stay 52 bytes");

void fm_par_init(FmParVoice *v);
void fm_par_set_params(FmParVoice *v, const uint8_t params[8]);
void fm_par_note_on(FmParVoice *v, float note_hz);
void fm_par_render(FmParVoice *v, float *out, int n);

/* Curve readers. op is 0, 1, or 2. Knobs outside 0..127 are clamped. */
int fm_par_frq_index(int knob);
float fm_par_frq_ratio(int op, int knob);
float fm_par_env_amount(int op, int knob);
float fm_par_tone_open(int knob);
float fm_par_tune_cents(int knob);

#endif
