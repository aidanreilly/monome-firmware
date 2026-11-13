/*
 * gs64sim: simavr harness for the gs64 firmware (simulation only).
 *
 * Pins (PLAN.md section 6):
 *   PORTE: E0 MAX CLK, E1 MAX LOAD, E2 MAX DIN, E3 key CLK, E4 key LD, E5 key data (in)
 *   PORTB: B4..B6 key row select
 *   PORTC: C0 TXE (in), C1 RXF (in), C2 WR, C3 RD, C4 PWREN (in)
 *   PORTD: FT245 data bus
 */
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <simavr/sim_avr.h>
#include <simavr/sim_elf.h>
#include <simavr/sim_irq.h>
#include <simavr/sim_io.h>
#include <simavr/avr_ioport.h>
#include <simavr/avr_eeprom.h>
#include <simavr/avr_adc.h>

#include "gs64sim.h"

#define E_MCLK 0x01
#define E_MLOAD 0x02
#define E_MDIN 0x04
#define E_KCLK 0x08
#define E_KLD 0x10
#define C_TXE 0
#define C_RXF 1
#define C_WR 0x04
#define C_RD 0x08
#define C_PWREN 4

typedef struct {
	uint8_t *b;
	size_t head, tail, cap;
} bq_t;

static void bq_push(bq_t *q, uint8_t v)
{
	if (q->tail == q->cap) {
		if (q->head > 0) {
			memmove(q->b, q->b + q->head, q->tail - q->head);
			q->tail -= q->head;
			q->head = 0;
		} else {
			q->cap = q->cap ? q->cap * 2 : 1024;
			q->b = realloc(q->b, q->cap);
		}
	}
	q->b[q->tail++] = v;
}
static size_t bq_len(const bq_t *q) { return q->tail - q->head; }

struct gs64sim {
	avr_t *avr;
	/* port shadow state */
	uint8_t pe, pb, pc;
	/* MAX7219 */
	uint16_t sr;
	int nbits;
	uint64_t word_start;
	uint8_t max_regs[16];
	uint64_t max_count;
	gs64sim_max_cb max_cb;
	void *max_ctx;
	FILE *trace;
	/* keypad */
	uint8_t keys[8];      /* bit col set = pressed */
	uint8_t kshift;       /* shift register contents, bit 0 = next out */
	int kld;              /* LD level */
	/* FT245 */
	bq_t rx, tx;
	gs64sim_tx_cb tx_cb;
	void *tx_ctx;
	int rd_active;
	uint64_t warnings;
	avr_irq_t *pin_e5, *pin_c[8], *pin_d[8];
	/* ISR watch */
	uint32_t isr_lo, isr_hi;
	int in_isr;
	uint64_t isr_entry;
	gs64sim_isr_cb isr_cb;
	void *isr_ctx;
};

static inline void isr_check(gs64sim_t *s)
{
	if (!s->isr_hi)
		return;
	int in = s->avr->pc >= s->isr_lo && s->avr->pc < s->isr_hi;
	if (in && !s->in_isr) {
		s->in_isr = 1;
		s->isr_entry = s->avr->cycle;
	} else if (!in && s->in_isr) {
		s->in_isr = 0;
		if (s->isr_cb)
			s->isr_cb(s->isr_ctx, s->isr_entry, s->avr->cycle);
	}
}

static int run1(gs64sim_t *s)
{
	int st = avr_run(s->avr);
	isr_check(s);
	return st;
}

static avr_irq_t *pin(avr_t *avr, char port, int n)
{
	return avr_io_getirq(avr, AVR_IOCTL_IOPORT_GETIRQ(port), n);
}

static uint8_t ddr(avr_t *avr, char port)
{
	/* ATmega1281 I/O: PINx/DDRx/PORTx; data-space address of DDRx */
	switch (port) {
	case 'B': return avr->data[0x24];
	case 'C': return avr->data[0x27];
	case 'D': return avr->data[0x2A];
	case 'E': return avr->data[0x2D];
	}
	return 0;
}
static uint8_t portreg(avr_t *avr, char port)
{
	switch (port) {
	case 'B': return avr->data[0x25];
	case 'C': return avr->data[0x28];
	case 'D': return avr->data[0x2B];
	case 'E': return avr->data[0x2E];
	}
	return 0;
}

static void key_update_out(gs64sim_t *s)
{
	int bit = s->kshift & 1;            /* 1 = pressed */
	avr_raise_irq(s->pin_e5, bit ? 0 : 1); /* active low */
}

static void key_reload(gs64sim_t *s)
{
	int row = (s->pb >> 4) & 7;
	s->kshift = s->keys[row];
}

static void rxf_update(gs64sim_t *s)
{
	avr_raise_irq(s->pin_c[C_RXF], bq_len(&s->rx) ? 0 : 1);
}

static void drive_d(gs64sim_t *s, uint8_t v)
{
	for (int i = 0; i < 8; i++)
		avr_raise_irq(s->pin_d[i], (v >> i) & 1);
}

static void max_word(gs64sim_t *s)
{
	uint8_t a = (s->sr >> 8) & 0x0F, d = s->sr & 0xFF;
	uint64_t c = s->avr->cycle;
	if (s->nbits != 16)
		s->warnings++;
	s->max_regs[a] = d;
	s->max_count++;
	if (s->trace)
		fprintf(s->trace, "%llu %u %u %llu %d\n", (unsigned long long)c, a, d,
			(unsigned long long)s->word_start, s->nbits);
	if (s->max_cb)
		s->max_cb(s->max_ctx, c, a, d, s->word_start, s->nbits);
	s->nbits = 0;
}

static void porte_cb(struct avr_irq_t *irq, uint32_t value, void *param)
{
	gs64sim_t *s = param;
	uint8_t v = (uint8_t)(value & ddr(s->avr, 'E'));
	uint8_t old = s->pe;
	s->pe = v;
	uint8_t rise = v & ~old, fall = old & ~v;
	/* MAX7219: DIN sampled on CLK rising edge, word latched on LOAD rising edge */
	if (rise & E_MCLK) {
		if (s->nbits == 0)
			s->word_start = s->avr->cycle;
		s->sr = (uint16_t)((s->sr << 1) | ((v & E_MDIN) ? 1 : 0));
		s->nbits++;
	}
	if (rise & E_MLOAD)
		max_word(s);
	/* keypad 74HC165-style: LD low = parallel load (transparent), LD high = shift */
	if (fall & E_KLD) {
		s->kld = 0;
	}
	if (rise & E_KLD) {
		key_reload(s);
		s->kld = 1;
	}
	if ((rise & E_KCLK) && s->kld) {
		s->kshift >>= 1;   /* serial input tied high = not pressed */
	}
	if (!s->kld)
		key_reload(s);
	key_update_out(s);
}

static void portb_cb(struct avr_irq_t *irq, uint32_t value, void *param)
{
	gs64sim_t *s = param;
	s->pb = (uint8_t)(value & ddr(s->avr, 'B'));
	if (!s->kld) {
		key_reload(s);
		key_update_out(s);
	}
}

static void portc_cb(struct avr_irq_t *irq, uint32_t value, void *param)
{
	gs64sim_t *s = param;
	/* pin level = PORT bit: driven when DDR = 1, pull-up (high) or low when DDR = 0.
	   (Masking with DDR made RD look low until the first write after DDRC was set,
	   so the first host byte was preceded by a phantom 0x00.) */
	uint8_t v = (uint8_t)(value & (C_WR | C_RD));
	uint8_t old = s->pc;
	s->pc = v;
	uint8_t rise = v & ~old, fall = old & ~v;
	if (fall & C_RD) {
		if (bq_len(&s->rx)) {
			drive_d(s, s->rx.b[s->rx.head]);
			s->rd_active = 1;
		} else {
			s->warnings++;
			drive_d(s, 0xFF);
			s->rd_active = 0;
		}
	}
	if (rise & C_RD) {
		if (s->rd_active && bq_len(&s->rx))
			s->rx.head++;
		s->rd_active = 0;
		rxf_update(s);
	}
	if (fall & C_WR) {
		uint8_t b = portreg(s->avr, 'D');
		if (ddr(s->avr, 'D') != 0xFF)
			s->warnings++;
		bq_push(&s->tx, b);
		if (s->tx_cb)
			s->tx_cb(s->tx_ctx, s->avr->cycle, b);
	}
}

/* simavr messages go to stderr (stdout may carry device bytes); trace chatter dropped */
static void quiet_logger(struct avr_t *avr, const int level, const char *fmt, va_list ap)
{
	if (level > LOG_WARNING)
		return;
	if (!strncmp(fmt, "Loaded", 6))
		return;
	vfprintf(stderr, fmt, ap);
}

gs64sim_t *gs64sim_new(const char *elf, const char *mcu, uint32_t freq)
{
	avr_global_logger_set(quiet_logger);
	elf_firmware_t f;
	memset(&f, 0, sizeof f);
	if (elf_read_firmware(elf, &f) != 0) {
		fprintf(stderr, "gs64sim: cannot read %s\n", elf);
		return NULL;
	}
	avr_t *avr = avr_make_mcu_by_name(mcu ? mcu : "atmega1281");
	if (!avr) {
		fprintf(stderr, "gs64sim: unknown mcu\n");
		return NULL;
	}
	avr_init(avr);
	f.frequency = freq ? freq : 16000000;
	avr->log = LOG_NONE;             /* silence the "Loaded ..." chatter on stdout */
	avr_load_firmware(avr, &f);
	avr->log = LOG_ERROR;
	avr->frequency = freq ? freq : 16000000;
	avr->vcc = avr->avcc = avr->aref = 5000;

	gs64sim_t *s = calloc(1, sizeof *s);
	s->avr = avr;
	s->pin_e5 = pin(avr, 'E', 5);
	for (int i = 0; i < 8; i++) {
		s->pin_c[i] = pin(avr, 'C', i);
		s->pin_d[i] = pin(avr, 'D', i);
	}
	avr_irq_register_notify(pin(avr, 'E', IOPORT_IRQ_REG_PORT), porte_cb, s);
	avr_irq_register_notify(pin(avr, 'B', IOPORT_IRQ_REG_PORT), portb_cb, s);
	avr_irq_register_notify(pin(avr, 'C', IOPORT_IRQ_REG_PORT), portc_cb, s);
	/* idle input levels */
	avr_raise_irq(s->pin_c[C_TXE], 0);
	avr_raise_irq(s->pin_c[C_PWREN], 0);
	rxf_update(s);
	key_update_out(s);
	return s;
}

void gs64sim_free(gs64sim_t *s)
{
	if (!s)
		return;
	avr_terminate(s->avr);
	free(s->rx.b);
	free(s->tx.b);
	free(s);
}

int gs64sim_run_cycles(gs64sim_t *s, uint64_t n)
{
	uint64_t end = s->avr->cycle + n;
	while (s->avr->cycle < end) {
		int st = run1(s);
		if (st == cpu_Done)
			return 1;
		if (st == cpu_Crashed)
			return 2;
	}
	return 0;
}

int gs64sim_run_us(gs64sim_t *s, double us)
{
	return gs64sim_run_cycles(s, (uint64_t)(us * s->avr->frequency / 1e6 + 0.5));
}

size_t gs64sim_run_until_tx(gs64sim_t *s, size_t nbytes, double max_us)
{
	uint64_t end = s->avr->cycle + (uint64_t)(max_us * s->avr->frequency / 1e6);
	while (bq_len(&s->tx) < nbytes && s->avr->cycle < end) {
		int st = run1(s);
		if (st == cpu_Done || st == cpu_Crashed)
			break;
	}
	return bq_len(&s->tx);
}

uint64_t gs64sim_cycles(const gs64sim_t *s) { return s->avr->cycle; }
double gs64sim_time_us(const gs64sim_t *s) { return s->avr->cycle * 1e6 / s->avr->frequency; }
uint32_t gs64sim_freq(const gs64sim_t *s) { return s->avr->frequency; }

void gs64sim_host_write(gs64sim_t *s, const uint8_t *buf, size_t n)
{
	for (size_t i = 0; i < n; i++)
		bq_push(&s->rx, buf[i]);
	if (!s->rd_active)
		rxf_update(s);
}
size_t gs64sim_rx_pending(const gs64sim_t *s) { return bq_len(&s->rx); }

size_t gs64sim_host_read(gs64sim_t *s, uint8_t *buf, size_t max)
{
	size_t n = bq_len(&s->tx);
	if (n > max)
		n = max;
	memcpy(buf, s->tx.b + s->tx.head, n);
	s->tx.head += n;
	return n;
}
size_t gs64sim_tx_pending(const gs64sim_t *s) { return bq_len(&s->tx); }

void gs64sim_key(gs64sim_t *s, int row, int col, int down)
{
	if (row < 0 || row > 7 || col < 0 || col > 7)
		return;
	if (down)
		s->keys[row] |= 1 << col;
	else
		s->keys[row] &= ~(1 << col);
	if (!s->kld) {
		key_reload(s);
		key_update_out(s);
	}
}

void gs64sim_set_pwren(gs64sim_t *s, int level) { avr_raise_irq(s->pin_c[C_PWREN], !!level); }
void gs64sim_set_txe(gs64sim_t *s, int level) { avr_raise_irq(s->pin_c[C_TXE], !!level); }

void gs64sim_set_adc(gs64sim_t *s, int channel, uint32_t mv)
{
	avr_irq_t *irq = avr_io_getirq(s->avr, AVR_IOCTL_ADC_GETIRQ, ADC_IRQ_ADC0 + channel);
	if (irq)
		avr_raise_irq(irq, mv);
}

int gs64sim_eeprom_write(gs64sim_t *s, uint16_t addr, const uint8_t *buf, uint16_t n)
{
	avr_eeprom_desc_t d = { .ee = (uint8_t *)buf, .offset = addr, .size = n };
	return avr_ioctl(s->avr, AVR_IOCTL_EEPROM_SET, &d);
}

int gs64sim_eeprom_read(gs64sim_t *s, uint16_t addr, uint8_t *buf, uint16_t n)
{
	avr_eeprom_desc_t d = { .ee = NULL, .offset = addr, .size = n };
	int r = avr_ioctl(s->avr, AVR_IOCTL_EEPROM_GET, &d);
	if (d.ee)
		memcpy(buf, d.ee, n);
	return r;
}

uint16_t gs64sim_eeprom_size(const gs64sim_t *s) { return (uint16_t)(s->avr->e2end + 1); }

void gs64sim_on_max_write(gs64sim_t *s, gs64sim_max_cb cb, void *ctx) { s->max_cb = cb; s->max_ctx = ctx; }
void gs64sim_on_tx(gs64sim_t *s, gs64sim_tx_cb cb, void *ctx) { s->tx_cb = cb; s->tx_ctx = ctx; }
void gs64sim_trace_file(gs64sim_t *s, FILE *f) { s->trace = f; }
const uint8_t *gs64sim_max_regs(const gs64sim_t *s) { return s->max_regs; }
uint64_t gs64sim_max_count(const gs64sim_t *s) { return s->max_count; }
uint64_t gs64sim_warnings(const gs64sim_t *s) { return s->warnings; }
void *gs64sim_avr(gs64sim_t *s) { return s->avr; }
void gs64sim_watch_isr(gs64sim_t *s, uint32_t lo, uint32_t hi, gs64sim_isr_cb cb, void *ctx)
{
	s->isr_lo = lo; s->isr_hi = hi; s->isr_cb = cb; s->isr_ctx = ctx; s->in_isr = 0;
}
