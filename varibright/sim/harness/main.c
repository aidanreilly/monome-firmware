/*
 * gs64sim command line front end (simulation only).
 *
 * usage: gs64sim [options] firmware.elf
 *   -m MCU          simavr core (default atmega1281)
 *   -f HZ           clock (default 16000000)
 *   -T MS           total simulated time in ms (default 1000)
 *   -s FILE         script of timed commands (see below)
 *   -t FILE         MAX7219 write trace: "cycle addr data start nbits" per line
 *   -o FILE         device->host bytes: "cycle 0xNN" per line (default stdout)
 *   -e FILE         preload EEPROM from a binary file (before reset)
 *   -E FILE         dump EEPROM to a binary file at the end
 *   -p              pty bridge: create a pseudo terminal, print its path, forward bytes
 *                   both ways and run paced to wall-clock time until killed (or -T)
 *   -q              quiet (no summary on stderr)
 *   -i LO:HI:FILE   ISR watch: write "entry_cycle exit_cycle" per pass through the PC
 *                   byte range [LO, HI) (hex) to FILE
 *
 * script lines ('#' comments), times in ms of simulated time, executed in order:
 *   @T host HH HH ...        queue bytes into the FT245 receive FIFO
 *   @T key ROW COL down|up   keypad (ROW = PORTB[6:4] value, COL = shift index)
 *   @T pwren 0|1             FT245 PWREN level (0 = USB configured)
 *   @T txe 0|1               FT245 TXE level
 *   @T adc CH MV             ADC input in millivolts
 *   @T ee ADDR HH HH ...     write EEPROM bytes
 *   @T eedump ADDR N         print EEPROM bytes to the output file
 *   @T mark TEXT             print "cycle # TEXT" to the output file
 */
#define _DEFAULT_SOURCE
#define _XOPEN_SOURCE 600
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>

#include "gs64sim.h"

typedef struct {
	double t_ms;
	char line[512];
} cmd_t;

static FILE *g_out;
static FILE *g_isr;

static void isr_cb(void *ctx, uint64_t a, uint64_t b)
{
	(void)ctx;
	fprintf(g_isr, "%llu %llu\n", (unsigned long long)a, (unsigned long long)b);
}

static void tx_cb(void *ctx, uint64_t cycle, uint8_t b)
{
	(void)ctx;
	fprintf(g_out, "%llu 0x%02x\n", (unsigned long long)cycle, b);
}

static int parse_bytes(char *p, uint8_t *buf, int max)
{
	int n = 0;
	char *tok;
	while (n < max && (tok = strtok(p, " \t\r\n")) != NULL) {
		p = NULL;
		buf[n++] = (uint8_t)strtoul(tok, NULL, 16);
	}
	return n;
}

static void exec_cmd(gs64sim_t *s, char *line)
{
	char verb[32];
	int off = 0;
	if (sscanf(line, "%31s %n", verb, &off) < 1)
		return;
	char *rest = line + off;
	uint8_t buf[256];
	if (!strcmp(verb, "host")) {
		int n = parse_bytes(rest, buf, sizeof buf);
		gs64sim_host_write(s, buf, n);
	} else if (!strcmp(verb, "key")) {
		int r, c;
		char st[16];
		if (sscanf(rest, "%d %d %15s", &r, &c, st) == 3)
			gs64sim_key(s, r, c, !strcmp(st, "down") || !strcmp(st, "1"));
	} else if (!strcmp(verb, "pwren")) {
		gs64sim_set_pwren(s, atoi(rest));
	} else if (!strcmp(verb, "txe")) {
		gs64sim_set_txe(s, atoi(rest));
	} else if (!strcmp(verb, "adc")) {
		int ch;
		unsigned mv;
		if (sscanf(rest, "%d %u", &ch, &mv) == 2)
			gs64sim_set_adc(s, ch, mv);
	} else if (!strcmp(verb, "ee")) {
		char *e;
		unsigned long a = strtoul(rest, &e, 0);
		int n = parse_bytes(e, buf, sizeof buf);
		gs64sim_eeprom_write(s, (uint16_t)a, buf, (uint16_t)n);
	} else if (!strcmp(verb, "eedump")) {
		unsigned a, n;
		if (sscanf(rest, "%i %i", &a, &n) == 2 && n <= sizeof buf) {
			gs64sim_eeprom_read(s, (uint16_t)a, buf, (uint16_t)n);
			fprintf(g_out, "%llu # eeprom %u:", (unsigned long long)gs64sim_cycles(s), a);
			for (unsigned i = 0; i < n; i++)
				fprintf(g_out, " %02x", buf[i]);
			fprintf(g_out, "\n");
		}
	} else if (!strcmp(verb, "mark")) {
		rest[strcspn(rest, "\r\n")] = 0;
		fprintf(g_out, "%llu # %s\n", (unsigned long long)gs64sim_cycles(s), rest);
	} else {
		fprintf(stderr, "gs64sim: unknown script command '%s'\n", verb);
	}
}

static cmd_t *load_script(const char *path, int *n)
{
	FILE *f = fopen(path, "r");
	if (!f) {
		perror(path);
		exit(1);
	}
	cmd_t *c = NULL;
	int cap = 0, k = 0;
	char line[512];
	while (fgets(line, sizeof line, f)) {
		char *p = line;
		while (*p == ' ' || *p == '\t')
			p++;
		if (*p != '@')
			continue;               /* blank lines and '#' comments */
		if (!strstr(p, " mark ")) {
			char *h = strchr(p, '#');
			if (h)
				*h = 0;
		}
		double t;
		int off;
		if (sscanf(p, "@%lf %n", &t, &off) < 1)
			continue;
		if (k == cap) {
			cap = cap ? cap * 2 : 64;
			c = realloc(c, cap * sizeof *c);
		}
		c[k].t_ms = t;
		snprintf(c[k].line, sizeof c[k].line, "%s", p + off);
		k++;
	}
	fclose(f);
	*n = k;
	return c;
}

static double now_s(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec + ts.tv_nsec * 1e-9;
}

int main(int argc, char **argv)
{
	const char *mcu = NULL, *script = NULL, *trace = NULL, *out = NULL, *eein = NULL,
		   *eeout = NULL, *isrw = NULL;
	uint32_t freq = 0;
	double total_ms = 1000;
	int pty = 0, quiet = 0, opt, total_set = 0;
	while ((opt = getopt(argc, argv, "m:f:T:s:t:o:e:E:pqi:")) != -1) {
		switch (opt) {
		case 'm': mcu = optarg; break;
		case 'f': freq = (uint32_t)strtoul(optarg, NULL, 0); break;
		case 'T': total_ms = atof(optarg); total_set = 1; break;
		case 's': script = optarg; break;
		case 't': trace = optarg; break;
		case 'o': out = optarg; break;
		case 'e': eein = optarg; break;
		case 'E': eeout = optarg; break;
		case 'p': pty = 1; break;
		case 'q': quiet = 1; break;
		case 'i': isrw = optarg; break;
		default:
			fprintf(stderr, "usage: %s [-m mcu] [-f hz] [-T ms] [-s script] [-t trace] "
				"[-o out] [-e ee.bin] [-E ee.bin] [-p] [-q] fw.elf\n", argv[0]);
			return 2;
		}
	}
	if (optind >= argc) {
		fprintf(stderr, "gs64sim: no firmware given\n");
		return 2;
	}
	gs64sim_t *s = gs64sim_new(argv[optind], mcu, freq);
	if (s && isrw) {
		unsigned lo, hi;
		char path[400];
		if (sscanf(isrw, "%x:%x:%399s", &lo, &hi, path) != 3 || !(g_isr = fopen(path, "w"))) {
			fprintf(stderr, "gs64sim: bad -i %s\n", isrw);
			return 1;
		}
		gs64sim_watch_isr(s, lo, hi, isr_cb, NULL);
	}
	if (!s)
		return 1;
	g_out = out ? fopen(out, "w") : stdout;
	if (!g_out) {
		perror(out);
		return 1;
	}
	FILE *tf = NULL;
	if (trace) {
		tf = fopen(trace, "w");
		if (!tf) {
			perror(trace);
			return 1;
		}
		fprintf(tf, "# gs64sim MAX7219 trace: cycle addr data start_cycle nbits (f=%u)\n",
			gs64sim_freq(s));
		gs64sim_trace_file(s, tf);
	}
	if (eein) {
		FILE *f = fopen(eein, "rb");
		if (!f) {
			perror(eein);
			return 1;
		}
		uint8_t buf[8192];
		size_t n = fread(buf, 1, sizeof buf, f);
		fclose(f);
		gs64sim_eeprom_write(s, 0, buf, (uint16_t)n);
	}
	int st = 0;
	if (!pty) {
		gs64sim_on_tx(s, tx_cb, NULL);
		int nc = 0, k = 0;
		cmd_t *cmds = script ? load_script(script, &nc) : NULL;
		double f = gs64sim_freq(s);
		uint64_t end = (uint64_t)(total_ms * 1e-3 * f);
		while (st == 0 && gs64sim_cycles(s) < end) {
			uint64_t next = end;
			if (k < nc) {
				uint64_t tc = (uint64_t)(cmds[k].t_ms * 1e-3 * f);
				if (tc <= gs64sim_cycles(s)) {
					exec_cmd(s, cmds[k].line);
					k++;
					continue;
				}
				if (tc < next)
					next = tc;
			}
			st = gs64sim_run_cycles(s, next - gs64sim_cycles(s));
		}
		free(cmds);
	} else {
		int m = posix_openpt(O_RDWR | O_NOCTTY);
		if (m < 0 || grantpt(m) || unlockpt(m)) {
			perror("pty");
			return 1;
		}
		struct termios tio;
		tcgetattr(m, &tio);
		cfmakeraw(&tio);
		tcsetattr(m, TCSANOW, &tio);
		fcntl(m, F_SETFL, O_NONBLOCK);
		printf("%s\n", ptsname(m));
		fflush(stdout);
		double t0 = now_s();
		uint64_t end = total_set ? (uint64_t)(total_ms * 1e-3 * gs64sim_freq(s)) : UINT64_MAX;
		uint8_t buf[512];
		while (st == 0 && gs64sim_cycles(s) < end) {
			ssize_t n = read(m, buf, sizeof buf);
			if (n > 0)
				gs64sim_host_write(s, buf, (size_t)n);
			st = gs64sim_run_us(s, 1000);
			size_t k = gs64sim_host_read(s, buf, sizeof buf);
			if (k > 0 && write(m, buf, k) < 0 && errno != EAGAIN)
				break;
			double ahead = gs64sim_time_us(s) * 1e-6 - (now_s() - t0);
			if (ahead > 0.002)
				usleep((useconds_t)(ahead * 1e6));
		}
		close(m);
	}
	if (eeout) {
		uint16_t n = gs64sim_eeprom_size(s);
		uint8_t *buf = malloc(n);
		gs64sim_eeprom_read(s, 0, buf, n);
		FILE *f = fopen(eeout, "wb");
		if (f) {
			fwrite(buf, 1, n, f);
			fclose(f);
		}
		free(buf);
	}
	if (!quiet)
		fprintf(stderr, "gs64sim: %.3f ms simulated, %llu MAX7219 words, %zu bytes unread "
			"in rx fifo, %llu warnings, state %d\n", gs64sim_time_us(s) / 1000.0,
			(unsigned long long)gs64sim_max_count(s), gs64sim_rx_pending(s),
			(unsigned long long)gs64sim_warnings(s), st);
	if (tf)
		fclose(tf);
	if (g_out != stdout)
		fclose(g_out);
	if (g_isr)
		fclose(g_isr);
	gs64sim_free(s);
	return st == 2 ? 3 : 0;
}
