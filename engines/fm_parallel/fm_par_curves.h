/* FM+PARALLELL curves. Edit this file to retune the engine.
 *
 * One table per SYN knob, plus the three modulator weights. The DSP
 * (fm_par.c) only reads these. Heights are generic placeholders. Do not
 * paste measured Monomachine sweeps, syx, or extracted tables in here.
 *
 * Listening notes that fixed the shape, not the numbers:
 *   FRQ     24 musical steps (the same simple ratios as FM+STATIC)
 *   3FRQ    dominates brightness (see fm_par_mod_w)
 *   ENV     peaks around knobs 72..83, folds back above about 94
 *   TONE    brightness, flattens from about knob 100
 *   TUNE    smooth and symmetric about knob 64
 *   level   stays about constant across a sweep, so these tables do not
 *           scale the carrier
 *
 * FRQ index for knob k (0..127) is (k * 24) / 128. Knob 0 is the first
 * ratio, knob 127 is the last.
 */
#ifndef FM_PAR_CURVES_H
#define FM_PAR_CURVES_H

#define FM_PAR_N_FRQ 24

/* Carrier phase deviation, in cycles, per unit of filtered modulator.
 * Placeholder until it is A/B'd. */
#define FM_PAR_BETA      0.20f
#define FM_PAR_DEV_CLIP  2.0f

/* How hard each modulator pulls the carrier. The third is the bright one.
 * Placeholder mix, not a measurement. */
static const float fm_par_mod_w[3] = { 0.25f, 0.50f, 1.00f };

typedef struct FmParBp {
    unsigned knob; /* 0..127, or 128 for a virtual TUNE endpoint */
    float y;
} FmParBp;

/* 1/64, 1/32, 1/16, 3/32, 1/8, 5/32, 3/16, 1/4,
 * 5/16, 3/8, 7/16, 1/2, 5/8, 3/4, 7/8, 1,
 * 5/4, 3/2, 7/4, 2, 5/2, 3, 7/2, 4
 * Three copies so one knob can be replaced without editing the others.
 */
static const uint8_t fm_par_frq1_n[24] = {
    1, 1, 1, 3, 1, 5, 3, 1, 5, 3, 7, 1, 5, 3, 7, 1, 5, 3, 7, 2, 5, 3, 7, 4
};
static const uint8_t fm_par_frq1_d[24] = {
    64, 32, 16, 32, 8, 32, 16, 4, 16, 8, 16, 2, 8, 4, 8, 1, 4, 2, 4, 1, 2, 1, 2, 1
};
static const uint8_t fm_par_frq2_n[24] = {
    1, 1, 1, 3, 1, 5, 3, 1, 5, 3, 7, 1, 5, 3, 7, 1, 5, 3, 7, 2, 5, 3, 7, 4
};
static const uint8_t fm_par_frq2_d[24] = {
    64, 32, 16, 32, 8, 32, 16, 4, 16, 8, 16, 2, 8, 4, 8, 1, 4, 2, 4, 1, 2, 1, 2, 1
};
static const uint8_t fm_par_frq3_n[24] = {
    1, 1, 1, 3, 1, 5, 3, 1, 5, 3, 7, 1, 5, 3, 7, 1, 5, 3, 7, 2, 5, 3, 7, 4
};
static const uint8_t fm_par_frq3_d[24] = {
    64, 32, 16, 32, 8, 32, 16, 4, 16, 8, 16, 2, 8, 4, 8, 1, 4, 2, 4, 1, 2, 1, 2, 1
};

/* Modulation amount. Not monotonic: rise, peak inside 72..83, fold after 94.
 * The y values are round placeholders. */
static const FmParBp fm_par_env1[] = {
    {0, 0.00f},
    {32, 0.40f},
    {64, 0.85f},
    {78, 1.00f},
    {94, 0.80f},
    {127, 0.45f},
};
static const FmParBp fm_par_env2[] = {
    {0, 0.00f},
    {32, 0.40f},
    {64, 0.85f},
    {78, 1.00f},
    {94, 0.80f},
    {127, 0.45f},
};
static const FmParBp fm_par_env3[] = {
    {0, 0.00f},
    {32, 0.40f},
    {64, 0.85f},
    {78, 1.00f},
    {94, 0.80f},
    {127, 0.45f},
};

/* One-pole openness on the modulator sum. 0 is dark, 1 is open.
 * Almost finished by knob 100; 100..127 barely moves. */
static const FmParBp fm_par_tone[] = {
    {0, 0.05f},
    {64, 0.35f},
    {100, 0.90f},
    {127, 1.00f},
};

/* Cents. Slope is 100/64 on both sides of 64, so knob 64+d matches
 * the negative of knob 64-d. The 128 point is virtual (no such knob);
 * knob 127 lands at +98.4375 cents. */
static const FmParBp fm_par_tune[] = {
    {0, -100.0f},
    {64, 0.0f},
    {128, 100.0f},
};

#endif
