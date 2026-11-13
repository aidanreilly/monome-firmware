/* C API smoke test against the harness self-test firmware (simulation only). */
#include <stdio.h>
#include <string.h>
#include "gs64sim.h"

static int fails;
#define CHECK(c, ...) do { if (!(c)) { fails++; printf("FAIL: " __VA_ARGS__); printf("\n"); } \
	else { printf("ok: " __VA_ARGS__); printf("\n"); } } while (0)

static uint64_t n_int;
static uint64_t last_int;
static double max_dev;
static void on_max(void *ctx, uint64_t c, uint8_t a, uint8_t d, uint64_t start, int nbits)
{
	(void)ctx; (void)d; (void)start;
	if (nbits != 16) fails++;
	if (a == 0x0A && c > 16000) {
		if (last_int) {
			double dev = (double)(c - last_int) - 20000.0;
			if (dev < 0) dev = -dev;
			if (dev > max_dev) max_dev = dev;
		}
		last_int = c;
		n_int++;
	}
}

int main(int argc, char **argv)
{
	const char *elf = argc > 1 ? argv[1] : "build/testfw.elf";
	gs64sim_t *s = gs64sim_new(elf, NULL, 0);
	if (!s) return 1;
	uint8_t pre[1] = {0xA5};
	gs64sim_eeprom_write(s, 0, pre, 1);
	gs64sim_on_max_write(s, on_max, NULL);
	gs64sim_run_us(s, 5000);
	CHECK(gs64sim_max_regs(s)[1] == 0xA5, "digit 1 shows preloaded EEPROM byte (0x%02x)",
	      gs64sim_max_regs(s)[1]);
	CHECK(gs64sim_max_regs(s)[0x0B] == 7 && gs64sim_max_regs(s)[0x0C] == 1, "init words decoded");
	uint8_t q[3] = {0x00, 0x01, 0x05}, r[16];
	gs64sim_host_write(s, q, 3);
	size_t n = gs64sim_run_until_tx(s, 3, 250000);
	n = gs64sim_host_read(s, r, sizeof r);
	CHECK(n == 3 && !memcmp(q, r, 3), "echo of 00 01 05 (%zu bytes, %.1f us)", n, gs64sim_time_us(s));
	gs64sim_key(s, 6, 3, 1);
	n = gs64sim_run_until_tx(s, 3, 20000);
	n = gs64sim_host_read(s, r, sizeof r);
	CHECK(n == 3 && r[0] == 0x21 && r[1] == 3 && r[2] == 6, "key down row 6 col 3 -> 21 03 06");
	gs64sim_key(s, 6, 3, 0);
	n = gs64sim_run_until_tx(s, 3, 20000);
	n = gs64sim_host_read(s, r, sizeof r);
	CHECK(n == 3 && r[0] == 0x20 && r[1] == 3 && r[2] == 6, "key up -> 20 03 06");
	gs64sim_run_us(s, 50000);
	CHECK(n_int > 30 && max_dev < 200, "ISR intensity writes: %llu, max period deviation %.0f cycles",
	      (unsigned long long)n_int, max_dev);
	uint8_t ee[5];
	gs64sim_eeprom_read(s, 0, ee, 5);
	CHECK(ee[4] == 0x00, "boot counter written to EEPROM (0xff+1 = 0x%02x)", ee[4]);
	CHECK(gs64sim_warnings(s) == 0, "no protocol warnings (%llu)", (unsigned long long)gs64sim_warnings(s));
	gs64sim_free(s);
	printf("%s\n", fails ? "API TEST FAILED" : "API TEST PASSED");
	return fails ? 1 : 0;
}
