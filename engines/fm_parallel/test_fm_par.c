/* Numerical checks for fm_par.c. No audio device, no firmware image.
 *
 *   gcc -std=c11 -Wall -Wextra -Werror -O2 -ffp-contract=off \
 *       -o /tmp/fm_par_test test_fm_par.c fm_par.c -lm
 */
#include "fm_par.h"

#include <math.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int fails;

static void expect(int cond, const char *msg)
{
    if (cond)
        printf("  ok  %s\n", msg);
    else {
        fprintf(stderr, "  FAIL  %s\n", msg);
        fails++;
    }
}

static int bad_float(float x)
{
    union { float f; uint32_t u; } v;
    v.f = x;
    return (v.u & 0x7f800000u) == 0x7f800000u;
}

static int denormal(float x)
{
    union { float f; uint32_t u; } v;
    v.f = x;
    return (v.u & 0x7f800000u) == 0 && (v.u & 0x007fffffu) != 0;
}

static int state_clean(const FmParVoice *v)
{
    int i;
    if (bad_float(v->phase_c) || denormal(v->phase_c))
        return 0;
    if (bad_float(v->note_hz) || denormal(v->note_hz))
        return 0;
    if (bad_float(v->out_gain) || denormal(v->out_gain))
        return 0;
    for (i = 0; i < 3; i++) {
        if (bad_float(v->phase_m[i]) || denormal(v->phase_m[i]))
            return 0;
        if (bad_float(v->env[i]) || denormal(v->env[i]))
            return 0;
    }
    return 1;
}

static int buffer_ok(const float *out, int n, float lim)
{
    int i;
    for (i = 0; i < n; i++) {
        if (bad_float(out[i]) || denormal(out[i]))
            return 0;
        if (out[i] > lim + 1.0e-6f || out[i] < -lim - 1.0e-6f)
            return 0;
    }
    return 1;
}

static void layout(void)
{
    expect(sizeof(FmParVoice) == 52, "voice is 52 bytes");
    expect(FM_PAR_STATE_BYTES == 52, "documented size is 52");
    expect(offsetof(FmParVoice, phase_c) == 0, "phase_c at 0");
    expect(offsetof(FmParVoice, phase_m) == 4, "phase_m at 4");
    expect(offsetof(FmParVoice, env) == 16, "env at 16");
    expect(offsetof(FmParVoice, note_hz) == 28, "note_hz at 28");
    expect(offsetof(FmParVoice, out_gain) == 32, "out_gain at 32");
    expect(offsetof(FmParVoice, tone_z) == 36, "tone_z at 36");
    expect(offsetof(FmParVoice, param) == 40, "param at 40");
    expect(offsetof(FmParVoice, active) == 48, "active at 48");
    expect(offsetof(FmParVoice, trig) == 49, "trig at 49");
    expect(FM_PAR_N_PARAMS == 8, "eight SYN encoders");
    expect(FM_PAR_MACHINE_STATIC == 5, "type 5 is FM+STATIC");
    expect(FM_PAR_MACHINE_DYNAMIC == 6, "type 6 is FM+DYNAMIC");
    expect(FM_PAR_MACHINE_ID == 7, "this engine is type 7");
    expect(FM_PAR_MACHINE_SUPERWAVE == 8, "super-wave starts at 8");
    expect(16 * (int)sizeof(FmParVoice) == 832, "sixteen voices are 832 bytes");
}

static void fill(uint8_t p[8], int v)
{
    int i;
    for (i = 0; i < 8; i++)
        p[i] = (uint8_t)v;
}

static void run_case(const uint8_t p[8], float hz, float gain, int blocks, float lim)
{
    FmParVoice v;
    float out[32];
    int b;
    fm_par_init(&v);
    v.out_gain = gain;
    fm_par_set_params(&v, p);
    fm_par_note_on(&v, hz);
    for (b = 0; b < blocks; b++) {
        fm_par_render(&v, out, 32);
        if (!buffer_ok(out, 32, lim) || !state_clean(&v)) {
            expect(0, "case stayed finite, denormal-free, and inside the gain");
            return;
        }
    }
}

static void stress(void)
{
    int mask, knob, step, bg;
    uint8_t p[8];
    const int backgrounds[3] = {0, 64, 127};
    {
        int before = fails;
        for (mask = 0; mask < 256; mask++) {
            int i;
            for (i = 0; i < 8; i++)
                p[i] = (mask & (1 << i)) ? 127 : 0;
            run_case(p, 440.0f, 1.0f, 4, 1.0f);
        }
        expect(fails == before, "all 256 knob corners (0 and 127) stay bounded");
    }

    for (knob = 0; knob < 8; knob++) {
        for (bg = 0; bg < 3; bg++) {
            fill(p, backgrounds[bg]);
            p[7] = 64;
            for (step = 0; step < 128; step++) {
                p[knob] = (uint8_t)step;
                run_case(p, (bg == 0) ? 8.18f : (bg == 1 ? 440.0f : 12000.0f), 1.0f, 1, 1.0f);
            }
        }
    }
    expect(1, "swept each of the 8 params across 0..127 at three backgrounds");
}

static void behaviour(void)
{
    FmParVoice v;
    float out[128];
    float held;
    uint8_t silent[8] = {0, 0, 0, 0, 0, 0, 0, 64};
    uint8_t loud[8] = {44, 64, 68, 64, 76, 64, 0, 64};
    uint8_t bright[8] = {44, 64, 68, 64, 76, 64, 127, 64};
    uint8_t mid[8] = {44, 90, 68, 80, 76, 70, 40, 64};
    int i;
    float peak = 0.0f;
    int differ = 0;

    fm_par_init(&v);
    v.phase_c = 0.25f;
    fm_par_render(&v, out, 32);
    expect(v.active == 0 && v.phase_c == 0.25f, "idle voice does not touch phase");
    expect(out[0] == 0.0f && out[31] == 0.0f, "idle voice writes silence");

    fm_par_set_params(&v, silent);
    fm_par_note_on(&v, 440.0f);
    for (i = 0; i < 64; i++) {
        fm_par_render(&v, out, 128);
        for (int k = 0; k < 128; k++)
            if (fabsf(out[k]) > peak)
                peak = fabsf(out[k]);
    }
    expect(v.active == 1 && peak > 0.99f && peak <= 1.0f, "no modulators still leaves a full carrier");

    fm_par_init(&v);
    fm_par_set_params(&v, loud);
    fm_par_note_on(&v, 220.0f);
    fm_par_render(&v, out, 32);
    held = out[0];
    fm_par_init(&v);
    fm_par_set_params(&v, bright);
    fm_par_note_on(&v, 220.0f);
    fm_par_render(&v, out, 32);
    expect(out[0] != held, "TONE changes the sound");

    for (i = 0; i < 8; i++) {
        uint8_t a[8] = {40, 64, 48, 64, 56, 64, 64, 64};
        uint8_t b[8] = {40, 64, 48, 64, 56, 64, 64, 64};
        float x[32], y[32];
        int s, moved = 0;
        a[i] = 0;
        b[i] = 127;
        fm_par_init(&v);
        fm_par_set_params(&v, a);
        fm_par_note_on(&v, 330.0f);
        fm_par_render(&v, x, 32);
        fm_par_init(&v);
        fm_par_set_params(&v, b);
        fm_par_note_on(&v, 330.0f);
        fm_par_render(&v, y, 32);
        for (s = 0; s < 32; s++)
            if (x[s] != y[s])
                moved = 1;
        if (!moved)
            differ++;
    }
    expect(differ == 0, "each of the 8 encoders moves the audio");

    fm_par_init(&v);
    fm_par_set_params(&v, mid);
    v.out_gain = 0.0f;
    fm_par_note_on(&v, 440.0f);
    fm_par_render(&v, out, 32);
    expect(out[0] == 0.0f && out[31] == 0.0f && v.phase_c != 0.0f, "zero gain is silent but the phase still runs");

    v.out_gain = 0.25f;
    fm_par_render(&v, out, 128);
    expect(buffer_ok(out, 128, 0.25f), "output stays inside the host gain");
}

static void hostile(void)
{
    FmParVoice v;
    float out[32];
    uint8_t raw[8];
    int i;
    fm_par_init(&v);
    v.active = 1;
    v.trig = 1;
    v.note_hz = NAN;
    v.out_gain = INFINITY;
    v.phase_c = NAN;
    v.phase_m[1] = -INFINITY;
    v.env[0] = NAN;
    v.env[2] = -1.0e30f;
    for (i = 0; i < 8; i++)
        raw[i] = 255;
    fm_par_set_params(&v, raw);
    fm_par_render(&v, out, 32);
    expect(buffer_ok(out, 32, FM_PAR_OUT_GAIN_MAX) && state_clean(&v),
           "NaN, Inf, and knob 255 collapse to a finite voice");
    expect(v.param[0] == 127 && v.param[7] == 127, "knobs clamp to 127");
    expect(v.trig == 0 && v.active == 1, "trig is consumed, voice stays active");
}

static void denorm(void)
{
    FmParVoice v;
    float out[32];
    union { float f; uint32_t u; } tiny;
    uint8_t p[8] = {0, 0, 0, 0, 0, 0, 0, 64};
    tiny.u = 0x00000001u; /* a denormal */
    fm_par_init(&v);
    fm_par_set_params(&v, p);
    v.active = 1;
    v.tone_z = tiny.f;
    v.env[0] = tiny.f;
    fm_par_render(&v, out, 32);
    expect(v.tone_z == 0.0f && !denormal(v.tone_z), "TONE state flushes a denormal to zero");
    expect(state_clean(&v) && buffer_ok(out, 32, 1.0f), "denormal input does not leak into the buffer");
}

static int near(float x, float y, float tol)
{
    return fabsf(x - y) <= tol;
}

static void curves(void)
{
    int k, seen[24], op, d;
    const float musical[24] = {
        1.f/64, 1.f/32, 1.f/16, 3.f/32, 1.f/8, 5.f/32, 3.f/16, 1.f/4,
        5.f/16, 3.f/8, 7.f/16, 1.f/2, 5.f/8, 3.f/4, 7.f/8, 1.f,
        5.f/4, 3.f/2, 7.f/4, 2.f, 5.f/2, 3.f, 7.f/2, 4.f
    };
    memset(seen, 0, sizeof seen);
    for (k = 0; k < 128; k++)
        seen[fm_par_frq_index(k)] = 1;
    for (k = 0; k < 24; k++)
        if (!seen[k]) {
            expect(0, "every FRQ step is reachable");
            return;
        }
    expect(1, "knob 0..127 reaches all 24 FRQ steps");
    for (op = 0; op < 3; op++) {
        for (k = 0; k < 128; k++) {
            int idx = fm_par_frq_index(k);
            if (fabsf(fm_par_frq_ratio(op, k) - musical[idx]) > 1.0e-6f) {
                expect(0, "FRQ table is the 24 musical ratios");
                return;
            }
        }
    }
    expect(fm_par_frq_ratio(0, 0) == musical[0] && fm_par_frq_ratio(2, 127) == 4.0f,
           "FRQ runs from 1/64 to 4");
    expect(fm_par_env_amount(0, 0) == 0.0f, "ENV 0 is silent");
    expect(fm_par_env_amount(0, 78) > fm_par_env_amount(0, 64), "ENV rises into the peak band");
    expect(fm_par_env_amount(0, 78) > fm_par_env_amount(0, 94), "ENV folds back after about 94");
    expect(fm_par_env_amount(0, 94) > fm_par_env_amount(0, 127), "ENV keeps falling toward 127");
    expect(fm_par_env_amount(1, 83) > fm_par_env_amount(1, 100), "peak band is above the fold");
    expect(fm_par_tone_open(0) < 0.2f && fm_par_tone_open(100) > 0.8f, "TONE opens up by 100");
    expect(fm_par_tone_open(127) - fm_par_tone_open(100) < 0.15f, "TONE saturates from about 100");
    expect(fm_par_tone_open(127) >= fm_par_tone_open(100), "TONE does not fall after it saturates");
    for (d = 1; d <= 63; d++) {
        float up = fm_par_tune_cents(64 + d);
        float dn = fm_par_tune_cents(64 - d);
        if (!near(up, -dn, 1.0e-4f)) {
            expect(0, "TUNE is symmetric about 64");
            return;
        }
    }
    expect(fm_par_tune_cents(64) == 0.0f && near(fm_par_tune_cents(0), -100.0f, 1.0e-4f),
           "TUNE center is 0 cents and knob 0 is -100");
}

static float brightness_of(const uint8_t p[8])
{
    FmParVoice v;
    float out[256];
    float acc = 0.0f, prev = 0.0f;
    int i, k, n = 0;
    fm_par_init(&v);
    fm_par_set_params(&v, p);
    fm_par_note_on(&v, 220.0f);
    for (i = 0; i < 16; i++) {
        fm_par_render(&v, out, 256);
        for (k = 0; k < 256; k++) {
            acc += fabsf(out[k] - prev);
            prev = out[k];
            n++;
        }
    }
    return acc / (float)n;
}

static void character(void)
{
    uint8_t lo[8] = {0, 78, 32, 78, 32, 78, 100, 64};
    uint8_t hi1[8] = {127, 78, 32, 78, 32, 78, 100, 64};
    uint8_t hi3[8] = {32, 78, 32, 78, 127, 78, 100, 64};
    float b1, b3;
    int knob;
    const int steps[8] = {0, 32, 64, 78, 94, 100, 110, 127};
    b1 = brightness_of(hi1) - brightness_of(lo);
    /* lo sweeps 1FRQ; for 3FRQ compare the same low knob against hi3 */
    {
        uint8_t lo3[8] = {32, 78, 32, 78, 0, 78, 100, 64};
        b3 = brightness_of(hi3) - brightness_of(lo3);
    }
    expect(b3 > b1 && b3 > 0.0f, "3FRQ moves brightness more than 1FRQ");
    for (knob = 0; knob < 8; knob++) {
        int s;
        for (s = 0; s < 8; s++) {
            FmParVoice v;
            float out[64];
            float peak = 0.0f;
            uint8_t p[8] = {16, 60, 16, 60, 16, 60, 40, 64};
            int i, k;
            p[knob] = (uint8_t)steps[s];
            fm_par_init(&v);
            fm_par_set_params(&v, p);
            fm_par_note_on(&v, 440.0f);
            for (i = 0; i < 8; i++) {
                fm_par_render(&v, out, 64);
                for (k = 0; k < 64; k++)
                    if (fabsf(out[k]) > peak)
                        peak = fabsf(out[k]);
            }
            if (!(peak > 0.98f && peak <= 1.0001f)) {
                expect(0, "loudness stays on the carrier across knob sweeps");
                return;
            }
        }
    }
    expect(1, "loudness stays on the carrier across knob sweeps");
}

static unsigned bits(float x)
{
    union { float f; uint32_t u; } v;
    v.f = x;
    return v.u;
}

static int cmp_mode(void)
{
    FmParVoice v;
    char line[256];
    float out[8192];
    fm_par_init(&v);
    while (fgets(line, sizeof line, stdin)) {
        float hz, gain;
        int n, trig, p0, p1, p2, p3, p4, p5, p6, p7, i;
        uint8_t p[8];
        if (strncmp(line, "reset", 5) == 0) {
            fm_par_init(&v);
            continue;
        }
        if (sscanf(line, "%d %f %f %d %d %d %d %d %d %d %d %d",
                   &n, &hz, &gain, &trig, &p0, &p1, &p2, &p3, &p4, &p5, &p6, &p7) != 12)
            return 2;
        if (n < 1 || n > 8192)
            return 2;
        p[0] = (uint8_t)p0; p[1] = (uint8_t)p1; p[2] = (uint8_t)p2; p[3] = (uint8_t)p3;
        p[4] = (uint8_t)p4; p[5] = (uint8_t)p5; p[6] = (uint8_t)p6; p[7] = (uint8_t)p7;
        v.note_hz = hz;
        v.out_gain = gain;
        fm_par_set_params(&v, p);
        v.trig = trig ? 1 : 0;
        fm_par_render(&v, out, n);
        for (i = 0; i < n; i++)
            printf("%08x%s", bits(out[i]), i + 1 == n ? "\n" : " ");
        printf("S %08x %08x %08x %08x %08x %08x %08x %08x %08x %u %u\n",
               bits(v.phase_c), bits(v.phase_m[0]), bits(v.phase_m[1]), bits(v.phase_m[2]),
               bits(v.env[0]), bits(v.env[1]), bits(v.env[2]), bits(v.note_hz), bits(v.out_gain),
               v.active, v.trig);
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc > 1 && strcmp(argv[1], "cmp") == 0)
        return cmp_mode();
    layout();
    curves();
    character();
    behaviour();
    hostile();
    denorm();
    stress();
    printf("%s %d\n", fails ? "FAIL" : "OK", fails);
    return fails ? 1 : 0;
}
