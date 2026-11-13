/*
 * End-to-end test: real libmonome (libmonome.c, proto/mext.c, rotation.c, unchanged)
 * talking through a stub platform layer to the real firmware ELF (64vb-sim.elf) in
 * the gs64sim simavr harness.  LED brightness is read back through the MAX7219
 * behavioural model (../max7219.c) from the firmware's own register writes.
 * Simulation only.
 *
 * usage: e2e_libmonome FIRMWARE.elf MODE [FS]
 *   MODE: tsd | sd | mono      (EEPROM calibration record preloaded accordingly)
 *   FS:   model scan rate in Hz (default 800); the calibrated period is chosen so the
 *         model rate is matched exactly (T_u = 1/FS + measured dark time)
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>

#include <monome.h>
#include "gs64sim.h"
#include "../max7219.c"

int monome_platform_wait_for_input(monome_t *monome, unsigned int msec);
extern gs64sim_t *stub_sim;
extern const char *stub_serial;
extern unsigned long stub_queries_sent;

static int fails, checks;
#define CHECK(c, ...) do { checks++; if (!(c)) { fails++; printf("FAIL "); } else printf("ok   "); \
	printf(__VA_ARGS__); printf("\n"); fflush(stdout); } while (0)

/* ------------------------------------------------------------------ MAX7219 writes */
static double *wt; static uint8_t *wa, *wd; static long nw, capw;
static void on_max(void *ctx, uint64_t c, uint8_t a, uint8_t d, uint64_t st, int nb)
{
	(void)ctx; (void)st; (void)nb;
	if (nw == capw) {
		capw = capw ? capw * 2 : 65536;
		wt = realloc(wt, capw * sizeof *wt); wa = realloc(wa, capw); wd = realloc(wd, capw);
	}
	wt[nw] = c / 16e6; wa[nw] = a; wd[nw] = d; nw++;
}

/* ------------------------------------------------------------------ firmware mirror */
enum { M_TSD, M_SD, M_MONO };
static int mode;
static int P_fw;                       /* frames per cycle */
static uint8_t lmask[16], code0[8];
static const uint8_t sd6c[6] = {15, 15, 6, 15, 11, 15};
static const uint8_t sd6m[16] = {0x00,0x04,0x10,0x01,0x05,0x11,0x09,0x0d,0x19,0x1d,0x0f,0x1b,0x1f,0x2f,0x3b,0x3f};

static uint8_t spread(int s, int P) { int acc = 0, m = 0; for (int k = 0; k < P; k++) { acc += s; if (acc >= P) { acc -= P; m |= 1 << k; } } return m; }

static void codes_for(int g, uint8_t *c)
{
	if (mode == M_TSD) { for (int f = 0; f < P_fw; f++) c[f] = g; return; }
	for (;;) {      /* SD: smallest g' >= g with a strictly increasing ramp */
		for (int f = 0; f < P_fw; f++) c[f] = ((2 * code0[f] + 1) * (g + 1)) >> 5;
		int ok = 1, last = 0;
		for (int L = 1; L < 16; L++) {
			int s = 0;
			for (int f = 0; f < P_fw; f++) if (lmask[L] >> f & 1) s += 2 * c[f] + 1;
			if (s <= last) ok = 0;
			last = s;
		}
		if (ok || g >= 15) return;
		g++;
	}
}

/* expected brightness of host level L, relative to a stock LED at intensity 15, with
 * the shutdown dark time removed (the caller divides it out) */
static double expect_rel(int L, int g)
{
	if (mode == M_MONO) return L > 7 ? (2 * g + 1) / 31.0 : 0.0;
	uint8_t c[8];
	codes_for(g, c);
	double s = 0;
	for (int f = 0; f < P_fw; f++) if (lmask[L] >> f & 1) s += (2 * c[f] + 1) / 31.0;
	return s / P_fw;
}

/* ------------------------------------------------------------------ measurement */
static double fs_model = 800, awake = 1.0;
static int g_now = 15;

static void measure(double t0, double t1, double rel[8][8])
{
	max_params p;
	memset(&p, 0, sizeof p);
	p.fs = fs_model; p.phase = 0.3; p.restart_mode = 1;   /* frozen wake, immediate writes */
	long nb = (long)((t1 - t0) / 50e-6);
	double *out = calloc(nb * 64, sizeof *out);
	max_simulate(&p, nw, wt, wa, wd, t0, 50e-6, nb, out, t1, NULL, 0, NULL);
	for (int x = 0; x < 8; x++)
		for (int y = 0; y < 8; y++) {
			double s = 0;
			for (long b = 0; b < nb; b++) s += out[b * 64 + x * 8 + (7 - y)];
			rel[x][y] = s / nb / (31.0 / 32.0 / 8.0) / awake;
		}
	free(out);
}

/* lv[x][y] = host level expected at device LED (x, y) */
static double check_grid(const char *what, int lv[8][8], double tol)
{
	double rel[8][8], worst = 0;
	int wx = 0, wy = 0;
	gs64sim_run_us(stub_sim, 40000);                 /* let the firmware apply it */
	double t0 = gs64sim_time_us(stub_sim) * 1e-6;
	gs64sim_run_us(stub_sim, 250000);
	measure(t0, t0 + 0.25, rel);
	for (int x = 0; x < 8; x++)
		for (int y = 0; y < 8; y++) {
			double e = fabs(rel[x][y] - expect_rel(lv[x][y], g_now));
			if (e > worst) { worst = e; wx = x; wy = y; }
		}
	CHECK(worst < tol, "%-46s worst |measured - expected| %.2f %% of stock at (%d,%d): level %d "
	      "measured %.3f expected %.3f", what, 100 * worst, wx, wy, lv[wx][wy], rel[wx][wy],
	      expect_rel(lv[wx][wy], g_now));
	return worst;
}

static void grab(double rel[8][8])
{
	gs64sim_run_us(stub_sim, 40000);
	double t0 = gs64sim_time_us(stub_sim) * 1e-6;
	gs64sim_run_us(stub_sim, 250000);
	measure(t0, t0 + 0.25, rel);
}

/* host level in device coordinates for which rel matches best (inverse of expect_rel) */
static int level_of(double r)
{
	int best = 0; double be = 1e9;
	for (int L = 0; L < 16; L++) { double e = fabs(expect_rel(L, g_now) - r); if (e < be) { be = e; best = L; } }
	return best;
}

/* host level -> displayed class (levels that share a step are indistinguishable) */
static int same_class(int a, int b) { return fabs(expect_rel(a, g_now) - expect_rel(b, g_now)) < 1e-9; }

static unsigned rng = 12345;
static int rnd(int n) { rng = rng * 1103515245u + 12345u; return (rng >> 16) % n; }

/* ------------------------------------------------------------------ events */
static int next_event(monome_t *m, monome_event_t *e, double max_ms)
{
	double end = gs64sim_time_us(stub_sim) + max_ms * 1000;
	while (gs64sim_time_us(stub_sim) < end) {
		if (monome_event_next(m, e) > 0) return 1;
		monome_platform_wait_for_input(m, 5);      /* the stub's USB delivery model */
	}
	return 0;
}

int main(int argc, char **argv)
{
	if (argc < 3) { fprintf(stderr, "usage: %s fw.elf tsd|sd|mono [fs]\n", argv[0]); return 2; }
	mode = !strcmp(argv[2], "sd") ? M_SD : !strcmp(argv[2], "mono") ? M_MONO : M_TSD;
	if (argc > 3) fs_model = atof(argv[3]);
	printf("== libmonome end-to-end, mode %s, model f_s %.0f Hz (simulation only)\n", argv[2], fs_model);

	stub_sim = gs64sim_new(argv[1], NULL, 0);
	if (!stub_sim) return 2;
	gs64sim_on_max_write(stub_sim, on_max, NULL);

	/* calibration record: dark time = 10 shifter words; measured below and the model
	   rate re-derived from it, so T_u matches 1/f_s + dark exactly */
	const unsigned dark_nom = 687;
	unsigned period = (unsigned)lround(16e6 / fs_model) + dark_nom;
	if (mode != M_MONO) {
		uint8_t cfg = mode == M_SD ? 1 : 0;
		uint8_t rec[5] = {0xB6, cfg, period & 255, period >> 8, 0};
		rec[4] = rec[1] ^ rec[2] ^ rec[3] ^ 0x5A;
		gs64sim_eeprom_write(stub_sim, 0x10, rec, 5);
	}
	gs64sim_run_us(stub_sim, 3.2e6);                 /* boot, start-up animation */

	if (mode == M_TSD) {
		P_fw = period <= 21333 + 687 ? 4 : 3;
		for (int L = 0; L < 16; L++) {
			int s = L ? (L * P_fw * 2 + 15) / 30 : 0;
			if (L && !s) s = 1;
			lmask[L] = spread(s, P_fw);
		}
	} else if (mode == M_SD) {
		P_fw = 6;
		memcpy(code0, sd6c, 6); memcpy(lmask, sd6m, 16);
	}
	if (mode != M_MONO) {
		long i0 = -1, i1 = -1;
		for (long i = nw - 1; i >= 0 && (i0 < 0 || i1 < 0); i--) {
			if (wa[i] == 12 && wd[i] == 1 && i1 < 0) i1 = i;
			if (wa[i] == 12 && wd[i] == 0 && i1 >= 0 && i0 < 0) i0 = i;
		}
		CHECK(i0 >= 0 && i1 > i0, "firmware runs shutdown-bracketed frames after boot");
		double dark = (wt[i1] - wt[i0]) * 16e6;
		fs_model = 16e6 / (period - dark);
		awake = 1.0 - dark / period;
		printf("     period %u ticks, dark %.0f cycles, model f_s %.3f Hz, awake %.4f, %d frames\n",
		       period, dark, fs_model, awake, P_fw);
	}

	/* ---- open: libmonome's own serial -> protocol mapping and mext_open handshake */
	monome_t *m = monome_open("/dev/ttyUSB-gs64");
	CHECK(m != NULL, "monome_open (serial %s) -> handshake completed", stub_serial);
	if (!m) { printf("E2E FAILED\n"); return 1; }
	CHECK(!strcmp(monome_get_proto(m), "mext"), "libmonome chose protocol '%s' from the serial", monome_get_proto(m));
	CHECK(monome_get_rows(m) == 8 && monome_get_cols(m) == 8, "grid size %dx%d", monome_get_cols(m), monome_get_rows(m));
	CHECK(!strcmp(monome_get_friendly_name(m), "monome 64"), "id '%s'", monome_get_friendly_name(m));
	CHECK(stub_queries_sent == 1, "handshake needed %lu query round(s)", stub_queries_sent);
	CHECK(gs64sim_tx_pending(stub_sim) == 0, "no stray device bytes after the handshake");

	int lv[8][8];
	double tol = mode == M_MONO ? 0.01 : 0.02;

#define FILL(v) do { for (int x_ = 0; x_ < 8; x_++) for (int y_ = 0; y_ < 8; y_++) lv[x_][y_] = (v); } while (0)

	/* ---- mono LED commands */
	monome_led_all(m, 0); FILL(0); check_grid("monome_led_all(0)", lv, tol);
	monome_led_all(m, 1); FILL(15); check_grid("monome_led_all(1)", lv, tol);
	monome_led_all(m, 0);
	monome_led_on(m, 3, 5); monome_led_on(m, 0, 0); monome_led_on(m, 7, 7); monome_led_on(m, 7, 0);
	monome_led_off(m, 7, 0);
	FILL(0); lv[3][5] = lv[0][0] = lv[7][7] = 15; check_grid("monome_led_on / monome_led_off", lv, tol);
	{
		uint8_t map[8] = {0x01, 0x82, 0x44, 0x28, 0x10, 0xFF, 0x00, 0xA5};
		monome_led_map(m, 0, 0, map);
		for (int y = 0; y < 8; y++) for (int x = 0; x < 8; x++) lv[x][y] = (map[y] >> x & 1) ? 15 : 0;
		check_grid("monome_led_map", lv, tol);
		uint8_t r = 0xC3, c = 0x5A;
		monome_led_row(m, 0, 2, 1, &r);
		for (int x = 0; x < 8; x++) lv[x][2] = (r >> x & 1) ? 15 : 0;
		check_grid("monome_led_row", lv, tol);
		monome_led_col(m, 6, 0, 1, &c);
		for (int y = 0; y < 8; y++) lv[6][y] = (c >> y & 1) ? 15 : 0;
		check_grid("monome_led_col", lv, tol);
	}

	/* ---- level commands */
	for (int x = 0; x < 8; x++) for (int y = 0; y < 8; y++) { lv[x][y] = (x + 8 * y) % 16; monome_led_level_set(m, x, y, lv[x][y]); }
	check_grid("monome_led_level_set x 64 (all 16 levels)", lv, tol);
	for (int L = 0; L < 16; L++) {
		char w[64];
		monome_led_level_all(m, L); FILL(L);
		snprintf(w, sizeof w, "monome_led_level_all(%d)", L);
		check_grid(w, lv, tol);
	}
	{
		uint8_t d[64];
		for (int i = 0; i < 64; i++) d[i] = rnd(16);
		monome_led_level_map(m, 0, 0, d);
		for (int y = 0; y < 8; y++) for (int x = 0; x < 8; x++) lv[x][y] = d[y * 8 + x];
		check_grid("monome_led_level_map (random)", lv, tol);
		uint8_t r[8], c[8];
		for (int i = 0; i < 8; i++) { r[i] = rnd(16); c[i] = rnd(16); }
		monome_led_level_row(m, 0, 4, 8, r);
		for (int x = 0; x < 8; x++) lv[x][4] = r[x];
		check_grid("monome_led_level_row", lv, tol);
		monome_led_level_col(m, 1, 0, 8, c);
		for (int y = 0; y < 8; y++) lv[1][y] = c[y];
		check_grid("monome_led_level_col", lv, tol);
	}

	/* ---- intensity */
	monome_led_level_all(m, 0);
	for (int x = 0; x < 8; x++) for (int y = 0; y < 8; y++) { lv[x][y] = (x + 8 * y) % 16; monome_led_level_set(m, x, y, lv[x][y]); }
	{
		int gs[] = {7, 3, 15};
		for (int i = 0; i < 3; i++) {
			char w[64];
			monome_led_intensity(m, gs[i]); g_now = gs[i];
			snprintf(w, sizeof w, "monome_led_intensity(%d) with all levels", gs[i]);
			check_grid(w, lv, tol);
		}
	}

	/* ---- rotation: libmonome rotates coordinates itself; check map/row/col agree with
	   per-LED set calls under each rotation, and that 0 degrees is the identity */
	if (mode != M_MONO) {
		monome_rotate_t rots[4] = {MONOME_ROTATE_0, MONOME_ROTATE_90, MONOME_ROTATE_180, MONOME_ROTATE_270};
		for (int ri = 0; ri < 4; ri++) {
			uint8_t d[64];
			double A[8][8], B[8][8];
			for (int i = 0; i < 64; i++) d[i] = rnd(16);
			monome_set_rotation(m, rots[ri]);
			monome_led_level_map(m, 0, 0, d);
			grab(A);
			monome_led_level_all(m, 0);
			for (int y = 0; y < 8; y++) for (int x = 0; x < 8; x++) monome_led_level_set(m, x, y, d[y * 8 + x]);
			grab(B);
			int agree = 1, ident = 1;
			for (int x = 0; x < 8; x++) for (int y = 0; y < 8; y++) {
				if (fabs(A[x][y] - B[x][y]) > tol) agree = 0;
				if (!same_class(level_of(B[x][y]), d[y * 8 + x])) ident = 0;
			}
			CHECK(agree, "rotation %d: level_map == 64 x level_set", 90 * ri);
			if (ri == 0) CHECK(ident, "rotation 0: device LED (x,y) shows host (x,y)");
			uint8_t row[8];
			for (int i = 0; i < 8; i++) row[i] = rnd(16);
			monome_led_level_all(m, 0);
			monome_led_level_row(m, 0, 3, 8, row);
			grab(A);
			monome_led_level_all(m, 0);
			for (int x = 0; x < 8; x++) monome_led_level_set(m, x, 3, row[x]);
			grab(B);
			agree = 1;
			for (int x = 0; x < 8; x++) for (int y = 0; y < 8; y++) if (fabs(A[x][y] - B[x][y]) > tol) agree = 0;
			CHECK(agree, "rotation %d: level_row == 8 x level_set", 90 * ri);
			monome_led_level_all(m, 0);
			monome_led_level_col(m, 5, 0, 8, row);
			grab(A);
			monome_led_level_all(m, 0);
			for (int y = 0; y < 8; y++) monome_led_level_set(m, 5, y, row[y]);
			grab(B);
			agree = 1;
			for (int x = 0; x < 8; x++) for (int y = 0; y < 8; y++) if (fabs(A[x][y] - B[x][y]) > tol) agree = 0;
			CHECK(agree, "rotation %d: level_col == 8 x level_set", 90 * ri);
		}
		monome_set_rotation(m, MONOME_ROTATE_0);
	}

	/* ---- keys: all 64, press and release, decoded by libmonome */
	{
		int ok_down = 0, ok_up = 0;
		monome_event_t e;
		for (int x = 0; x < 8; x++) for (int y = 0; y < 8; y++) {
			gs64sim_key(stub_sim, 7 - x, 7 - y, 1);
			if (next_event(m, &e, 100) && e.event_type == MONOME_BUTTON_DOWN && e.grid.x == (unsigned)x && e.grid.y == (unsigned)y) ok_down++;
			else printf("     key (%d,%d) down not decoded correctly\n", x, y);
			gs64sim_key(stub_sim, 7 - x, 7 - y, 0);
			if (next_event(m, &e, 100) && e.event_type == MONOME_BUTTON_UP && e.grid.x == (unsigned)x && e.grid.y == (unsigned)y) ok_up++;
			else printf("     key (%d,%d) up not decoded correctly\n", x, y);
		}
		CHECK(ok_down == 64 && ok_up == 64, "64 keys: %d down and %d up events decoded by libmonome", ok_down, ok_up);
		/* rotation applies to keys as well: press (1,2) under 90 degrees */
		monome_set_rotation(m, MONOME_ROTATE_90);
		gs64sim_key(stub_sim, 7 - 1, 7 - 2, 1);
		int got = next_event(m, &e, 100);
		unsigned kx = e.grid.x, ky = e.grid.y;
		gs64sim_key(stub_sim, 7 - 1, 7 - 2, 0);
		next_event(m, &e, 100);
		/* libmonome rotation: an LED set at the reported key position lights that key */
		monome_led_level_all(m, 0);
		monome_led_level_set(m, kx, ky, 15);
		double R[8][8];
		grab(R);
		monome_set_rotation(m, MONOME_ROTATE_0);
		CHECK(got && R[1][2] > 0.5 && same_class(level_of(R[1][2]), 15),
		      "rotation 90: key (1,2) reported as (%u,%u); setting that LED lights device LED (1,2)", kx, ky);
		monome_led_level_all(m, 0);
	}

	/* ---- tilt */
	{
		monome_event_t e;
		gs64sim_set_adc(stub_sim, 1, 3000);   /* x */
		gs64sim_set_adc(stub_sim, 0, 2000);   /* y */
		monome_tilt_enable(m, 0);
		int n = 0, last_x = 0, last_y = 0;
		double end = gs64sim_time_us(stub_sim) + 300000;
		while (gs64sim_time_us(stub_sim) < end)
			if (next_event(m, &e, 50) && e.event_type == MONOME_TILT) { n++; last_x = e.tilt.x; last_y = e.tilt.y; }
		/* 10-bit ADC of 3000 mV / 2000 mV at AREF 5 V, >> 2, - 128 */
		int ex = ((int)(3000 * 1024 / 5000) >> 2) - 128, ey = ((int)(2000 * 1024 / 5000) >> 2) - 128;
		CHECK(n >= 1 && abs(last_x - ex) <= 1 && abs(last_y - ey) <= 1,
		      "tilt enabled: %d events, last x %d y %d (expected about %d %d)", n, last_x, last_y, ex, ey);
		monome_tilt_disable(m, 0);
		gs64sim_run_us(stub_sim, 20000);
		while (monome_event_next(m, &e) > 0) ;
		gs64sim_set_adc(stub_sim, 1, 1000);
		n = 0;
		end = gs64sim_time_us(stub_sim) + 200000;
		while (gs64sim_time_us(stub_sim) < end)
			if (next_event(m, &e, 50) && e.event_type == MONOME_TILT) n++;
		CHECK(n == 0, "tilt disabled: %d events after the input changed", n);
	}

	CHECK(gs64sim_warnings(stub_sim) == 0, "harness protocol warnings: %llu", (unsigned long long)gs64sim_warnings(stub_sim));
	monome_close(m);
	gs64sim_free(stub_sim);
	printf("E2E %s %s: %d checks, %d failed\n", argv[2], fails ? "FAILED" : "PASSED", checks, fails);
	return fails ? 1 : 0;
}
