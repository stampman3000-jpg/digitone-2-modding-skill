/* FM+PARALLELL sample loop. Same order as fm_par_ref.py.
 * Three modulators into one carrier. Generic sinf. Curves from
 * fm_par_curves.h. No voice amp and no voice filter.
 */
#include "fm_par.h"
#include "fm_par_curves.h"

#include <math.h>
#include <string.h>

static float flush(float x)
{
    union { float f; uint32_t u; } v;
    if (x != x)
        return 0.0f;
    v.f = x;
    if ((v.u & 0x7f800000u) == 0)
        return 0.0f;
    return v.f;
}

static float wrap01(float x)
{
    float w;
    if (x != x)
        return 0.0f;
    w = x - floorf(x);
    if (!(w >= 0.0f && w < 1.0f))
        return 0.0f;
    return w;
}

static float clampf(float x, float lim)
{
    if (x != x)
        return 0.0f;
    if (lim < 0.0f)
        lim = -lim;
    if (x > lim)
        return lim;
    if (x < -lim)
        return -lim;
    return x;
}

static int knob_of(int p)
{
    if (p < 0)
        return 0;
    if (p > 127)
        return 127;
    return p;
}

static float sanitize_hz(float hz)
{
    if (!(hz > 0.0f))
        return 0.0f;
    if (hz > FM_PAR_HZ_MAX)
        return FM_PAR_HZ_MAX;
    return flush(hz);
}

static float sanitize_gain(float g)
{
    if (g != g)
        return 0.0f;
    if (g < 0.0f)
        g = -g;
    if (g > FM_PAR_OUT_GAIN_MAX)
        g = FM_PAR_OUT_GAIN_MAX;
    g = flush(g);
    if (g < FM_PAR_DENORM_FLOOR)
        return 0.0f;
    return g;
}

static float bp_eval(const FmParBp *bp, int n, int knob)
{
    int i;
    if (n <= 0)
        return 0.0f;
    if (knob <= (int)bp[0].knob)
        return bp[0].y;
    for (i = 1; i < n; i++) {
        if (knob <= (int)bp[i].knob) {
            int span = (int)bp[i].knob - (int)bp[i - 1].knob;
            float t, dy, scaled;
            if (span <= 0)
                return bp[i].y;
            t = (float)(knob - (int)bp[i - 1].knob) / (float)span;
            dy = bp[i].y - bp[i - 1].y;
            scaled = t * dy;
            return bp[i - 1].y + scaled;
        }
    }
    return bp[n - 1].y;
}

static const uint8_t *frq_n(int op)
{
    if (op == 1)
        return fm_par_frq2_n;
    if (op == 2)
        return fm_par_frq3_n;
    return fm_par_frq1_n;
}

static const uint8_t *frq_d(int op)
{
    if (op == 1)
        return fm_par_frq2_d;
    if (op == 2)
        return fm_par_frq3_d;
    return fm_par_frq1_d;
}

static const FmParBp *env_bp(int op, int *n)
{
    if (op == 1) {
        *n = (int)(sizeof fm_par_env2 / sizeof fm_par_env2[0]);
        return fm_par_env2;
    }
    if (op == 2) {
        *n = (int)(sizeof fm_par_env3 / sizeof fm_par_env3[0]);
        return fm_par_env3;
    }
    *n = (int)(sizeof fm_par_env1 / sizeof fm_par_env1[0]);
    return fm_par_env1;
}

int fm_par_frq_index(int knob)
{
    int i = knob_of(knob) * FM_PAR_N_FRQ / 128;
    if (i < 0)
        return 0;
    if (i > FM_PAR_N_FRQ - 1)
        return FM_PAR_N_FRQ - 1;
    return i;
}

float fm_par_frq_ratio(int op, int knob)
{
    int i;
    if (op < 0 || op > 2)
        return 0.0f;
    i = fm_par_frq_index(knob);
    return (float)frq_n(op)[i] / (float)frq_d(op)[i];
}

float fm_par_env_amount(int op, int knob)
{
    int n = 0;
    const FmParBp *bp;
    if (op < 0 || op > 2)
        return 0.0f;
    /* n is written by env_bp. Do not pass it in the same argument list. */
    bp = env_bp(op, &n);
    return bp_eval(bp, n, knob_of(knob));
}

float fm_par_tone_open(int knob)
{
    return bp_eval(fm_par_tone, (int)(sizeof fm_par_tone / sizeof fm_par_tone[0]),
                   knob_of(knob));
}

float fm_par_tune_cents(int knob)
{
    return bp_eval(fm_par_tune, (int)(sizeof fm_par_tune / sizeof fm_par_tune[0]),
                   knob_of(knob));
}

static float sine_cycle(float phase01)
{
    float s = sinf(phase01 * FM_PAR_TAU);
    if (s > 1.0f)
        return 1.0f;
    if (s < -1.0f)
        return -1.0f;
    if (s != s)
        return 0.0f;
    return s;
}

void fm_par_init(FmParVoice *v)
{
    if (!v)
        return;
    memset(v, 0, sizeof *v);
    v->param[7] = 64;
    v->out_gain = FM_PAR_OUT_GAIN_DEFAULT;
}

void fm_par_set_params(FmParVoice *v, const uint8_t params[8])
{
    int i;
    if (!v || !params)
        return;
    for (i = 0; i < FM_PAR_N_PARAMS; i++)
        v->param[i] = (uint8_t)knob_of(params[i]);
}

void fm_par_note_on(FmParVoice *v, float note_hz)
{
    if (!v)
        return;
    v->note_hz = sanitize_hz(note_hz);
    v->trig = 1;
}

void fm_par_render(FmParVoice *v, float *out, int n)
{
    int i, k;
    float gain, cents, tune, ninc, a;
    float inc[3];

    if (!v || !out || n <= 0)
        return;

    if (v->trig) {
        v->phase_c = 0.0f;
        v->phase_m[0] = v->phase_m[1] = v->phase_m[2] = 0.0f;
        v->tone_z = 0.0f;
        v->active = 1;
        v->trig = 0;
    }
    if (!v->active) {
        for (i = 0; i < n; i++)
            out[i] = 0.0f;
        return;
    }

    v->note_hz = sanitize_hz(v->note_hz);
    v->out_gain = sanitize_gain(v->out_gain);
    gain = v->out_gain;
    v->phase_c = flush(wrap01(v->phase_c));
    for (i = 0; i < 3; i++) {
        float e;
        v->phase_m[i] = flush(wrap01(v->phase_m[i]));
        e = fm_par_env_amount(i, knob_of(v->param[i * 2 + 1]));
        if (!(e >= 0.0f))
            e = 0.0f;
        v->env[i] = flush(e);
    }
    if (v->tone_z != v->tone_z || v->tone_z > 1.0e20f || v->tone_z < -1.0e20f)
        v->tone_z = 0.0f;
    else
        v->tone_z = flush(v->tone_z);

    cents = fm_par_tune_cents(knob_of(v->param[7]));
    tune = exp2f(cents / 1200.0f);
    if (!(tune > 0.0f))
        tune = 1.0f;
    ninc = v->note_hz * (1.0f / FM_PAR_SR) * tune;
    for (i = 0; i < 3; i++)
        inc[i] = ninc * fm_par_frq_ratio(i, knob_of(v->param[i * 2]));

    a = fm_par_tone_open(knob_of(v->param[6]));
    if (!(a >= 0.0f))
        a = 0.0f;
    if (a > 1.0f)
        a = 1.0f;

    for (k = 0; k < n; k++) {
        float m = 0.0f;
        float z, dev, s;
        for (i = 0; i < 3; i++) {
            float ms, scaled, weighted;
            v->phase_m[i] = flush(wrap01(v->phase_m[i] + inc[i]));
            ms = sine_cycle(v->phase_m[i]);
            scaled = ms * v->env[i];
            weighted = fm_par_mod_w[i] * scaled;
            m = m + weighted;
        }
        z = v->tone_z;
        z = z + a * (m - z);
        z = flush(z);
        if (z < FM_PAR_DENORM_FLOOR && z > -FM_PAR_DENORM_FLOOR)
            z = 0.0f;
        v->tone_z = z;
        dev = clampf(z * FM_PAR_BETA, FM_PAR_DEV_CLIP);
        v->phase_c = flush(wrap01(v->phase_c + ninc));
        s = sine_cycle(wrap01(v->phase_c + dev));
        out[k] = flush(clampf(s * gain, gain));
    }
}
