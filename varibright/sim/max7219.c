/*
 * MAX7219 behavioural model (simulation only, not validated against hardware).
 *
 * Input : time-stamped 16-bit register writes (time of the LOAD rising edge).
 * Output: per-LED light integrated exactly into time bins of width dt.
 *         out[bin*64 + digit*8 + seg] = fraction of the bin during which that
 *         LED was driven (0..1).  digit = register address - 1 (0..7),
 *         seg = data bit index (0 = D0 = segment G, 7 = D7 = DP).
 *
 * Model (see README for the justification of each assumption):
 *  - The scan oscillator advances one digit slot every T_d = 1/(8*fs) seconds
 *    (optionally with per-slot gaussian jitter and a linear frequency drift).
 *    Digits 0..scan_limit are scanned in order; slot length does not depend on
 *    the scan limit, so fewer digits give a faster frame (datasheet: scan rate
 *    = 8*fosc/N).
 *  - Inside a slot, the first `blank` fraction is dark (inter-digit blanking).
 *    The PWM on-time for intensity code n is (2n+1)/32 of the remaining active
 *    part; it is placed at pwm_pos (0 = immediately after blanking, 1 = ending
 *    at the slot end, 0.5 centred).
 *  - digit_effect / int_effect: 0 = a register write changes the output
 *    immediately (mid-slot); 1 = the value is sampled at the start of each
 *    digit slot (a mid-slot write is seen from the next slot on).
 *  - Shutdown (reg 0x0C bit0 = 0) halts the oscillator and blanks the display;
 *    leaving shutdown either restarts the scan at `restart_digit` at that
 *    instant (restart_mode 0) or resumes the frozen digit/slot position
 *    (restart_mode 1), or restarts the interrupted digit's slot (2), or moves
 *    to the next digit (3), after an optional dark `wake_delay`.  The datasheet
 *    only says the oscillator is halted and that leaving shutdown typically
 *    takes < 250 us; all four variants are modelled.
 *  - Display test (0x0F bit0 = 1) lights every segment of all 8 digits with
 *    duty 31/32 regardless of the other registers (oscillator runs).
 *  - Decode mode (0x09) applies the Code-B font to the selected digits.
 *  - Scan limit (0x0B) is applied at the next slot boundary.
 */
#include <stdint.h>
#include <string.h>
#include <math.h>

typedef struct {
	double fs;          /* frame rate with 8 digits scanned (Hz)                */
	double phase;       /* frame fraction already elapsed at t = tstart [0,1)   */
	double blank;       /* inter-digit blanking fraction of each slot           */
	double pwm_pos;     /* 0 left, 0.5 centre, 1 right                          */
	int digit_effect;   /* 0 immediate, 1 next slot                             */
	int int_effect;     /* 0 immediate, 1 next slot                             */
	double osc_jitter;  /* rms fractional jitter of each slot length            */
	double drift;       /* fractional fs change per second (fs*(1+drift*t))     */
	uint32_t seed;
	int restart_digit;  /* digit scanned first after leaving shutdown (mode 0)  */
	int restart_mode;   /* on leaving shutdown: 0 restart at restart_digit, slot
			       start; 1 frozen oscillator, resume mid-slot; 2 same
			       digit, slot restarts; 3 next digit, slot start      */
	double wake_delay;  /* dark, halted time after leaving shutdown (datasheet:
			       typically < 250 us)                                  */
	double wake_jitter; /* + uniform(-1,1) * wake_jitter on each wake           */
	double tstart;      /* time at which the oscillator state is defined        */
	uint8_t regs[16];   /* initial register file                                */
	int hold_latch;     /* next-slot model + frozen wake: 0 = the resumed partial
			       slot re-samples the registers at wake (as if a slot
			       started); 1 = it keeps the values latched at the real
			       slot start, before the halt                          */
} max_params;

static const uint8_t codeb[16] = {
	/* 0..9, '-', E, H, L, P, blank ; segments DP A B C D E F G = bits 7..0 */
	0x7E, 0x30, 0x6D, 0x79, 0x33, 0x5B, 0x5F, 0x70, 0x7F, 0x7B,
	0x01, 0x4F, 0x37, 0x0E, 0x67, 0x00
};

static uint32_t rng_state;
static double urand(void)
{
	rng_state ^= rng_state << 13; rng_state ^= rng_state >> 17; rng_state ^= rng_state << 5;
	return (rng_state + 0.5) / 4294967296.0;
}
static double nrand(void)
{
	double u1 = urand(), u2 = urand();
	return sqrt(-2.0 * log(u1)) * cos(6.283185307179586 * u2);
}

static double *g_out;
static double g_t0, g_dt;
static long g_nbins;

static void add_light(double a, double b, uint8_t bits, int digit)
{
	if (b <= a || !bits) return;
	double x = (a - g_t0) / g_dt, y = (b - g_t0) / g_dt;
	if (y <= 0 || x >= g_nbins) return;
	if (x < 0) x = 0;
	if (y > g_nbins) y = g_nbins;
	long i = (long)floor(x);
	while (i < g_nbins && i < y) {
		double lo = x > i ? x : (double)i;
		double hi = y < i + 1 ? y : (double)(i + 1);
		double w = hi - lo;
		if (w > 0) {
			double *o = g_out + i * 64 + digit * 8;
			for (int s = 0; s < 8; s++) if (bits & (1 << s)) o[s] += w;
		}
		i++;
	}
}

static uint8_t seg_of(const uint8_t *r, int digit, uint8_t raw)
{
	if (r[9] & (1 << digit)) return (raw & 0x80) | codeb[raw & 0x0F];
	return raw;
}

/* light the part of [x,y) that falls in the PWM window of code n for a slot [a, a+len) */
static void slot_part(const max_params *p, double a, double len, double x, double y,
		      int n, uint8_t bits, int digit)
{
	double act = len * (1.0 - p->blank);
	double on = act * (2 * n + 1) / 32.0;
	double w0 = a + len * p->blank + p->pwm_pos * (act - on);
	double w1 = w0 + on;
	if (x < w0) x = w0;
	if (y > w1) y = w1;
	add_light(x, y, bits, digit);
}

/*
 * returns number of slots simulated.  frame_log (optional, size max_log) receives
 * the start time of every slot of digit 0.
 */
long max_simulate(const max_params *p, long n, const double *t, const uint8_t *addr,
		  const uint8_t *data, double t0, double dt, long nbins, double *out,
		  double tend, double *frame_log, long max_log, long *n_log)
{
	uint8_t r[16];
	memcpy(r, p->regs, 16);
	g_out = out; g_t0 = t0; g_dt = dt; g_nbins = nbins;
	memset(out, 0, sizeof(double) * nbins * 64);
	rng_state = p->seed ? p->seed : 0x12345678u;
	long nl = 0;

	double Td0 = 1.0 / (8.0 * p->fs);
	long k = 0;            /* next write index */
	long nslots = 0;
	double now = p->tstart;
	int running = (r[12] & 1) || (r[15] & 1);

	/* apply writes earlier than tstart instantly */
	while (k < n && t[k] < now) { r[addr[k] & 15] = data[k]; k++; }
	running = (r[12] & 1) || (r[15] & 1);

	double ph = p->phase - floor(p->phase);
	double pos = ph * 8.0;           /* slots into the frame */
	int digit = (int)floor(pos);
	double slot_frac = pos - digit;  /* fraction of current slot already elapsed */
	int lim = r[15] & 1 ? 7 : (r[11] & 7);
	if (digit > lim) { digit = 0; slot_frac = 0; }
	int halt_digit = digit;
	double halt_frac = 0;
	int have_hold = 0;
	uint8_t hold_dig = 0, hold_int = 0;

	while (now < tend) {
		if (!running) {
			/* oscillator halted: consume writes until it restarts */
			if (k >= n) break;
			now = t[k];
			r[addr[k] & 15] = data[k]; k++;
			running = (r[12] & 1) || (r[15] & 1);
			if (running) {
				now += p->wake_delay;
				if (p->wake_jitter > 0) now += p->wake_jitter * (2.0 * urand() - 1.0);
				switch (p->restart_mode) {
				case 1: digit = halt_digit; slot_frac = halt_frac; break;
				case 2: digit = halt_digit; slot_frac = 0; break;
				case 3: digit = halt_digit >= lim ? 0 : halt_digit + 1; slot_frac = 0; break;
				default: digit = p->restart_digit & 7; slot_frac = 0;
				}
				lim = r[15] & 1 ? 7 : (r[11] & 7);
				if (digit > lim) digit = 0;
			}
			continue;
		}
		double Td = Td0 / (1.0 + p->drift * now);
		if (p->osc_jitter > 0) Td *= 1.0 + p->osc_jitter * nrand();
		double a = now - slot_frac * Td;   /* slot start */
		double e = a + Td;
		int resumed = slot_frac > 0;
		slot_frac = 0;
		if (digit == 0 && frame_log && nl < max_log) frame_log[nl++] = a;
		/* latched values at slot start */
		uint8_t lat_dig = r[1 + digit];
		uint8_t lat_int = r[10] & 15;
		if (resumed && have_hold && p->hold_latch) { lat_dig = hold_dig; lat_int = hold_int; }
		have_hold = 0;
		double x = now;
		int stopped = 0;
		for (;;) {
			double y = (k < n && t[k] < e) ? t[k] : e;
			/* emit [x, y) with current state */
			if (r[15] & 1) {
				slot_part(p, a, Td, x, y, 15, 0xFF, digit);
			} else {
				uint8_t raw = p->digit_effect ? lat_dig : r[1 + digit];
				int code = p->int_effect ? lat_int : (r[10] & 15);
				slot_part(p, a, Td, x, y, code, seg_of(r, digit, raw), digit);
			}
			if (y >= e) break;
			/* apply write */
			r[addr[k] & 15] = data[k]; k++;
			x = y;
			if (!((r[12] & 1) || (r[15] & 1))) {
				running = 0; now = y; stopped = 1;
				halt_digit = digit; halt_frac = (y - a) / Td;
				have_hold = 1; hold_dig = lat_dig; hold_int = lat_int;
				break;
			}
		}
		nslots++;
		if (stopped) continue;
		now = e;
		lim = r[15] & 1 ? 7 : (r[11] & 7);
		digit = digit >= lim ? 0 : digit + 1;
	}
	if (n_log) *n_log = nl;
	return nslots;
}
