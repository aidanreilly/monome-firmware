/*
 * gs64sim: simavr harness for the gs64 (MAX7219 + FT245 + keypad) firmware.
 * Simulation only.  See sim/README.md for the pin contract (PLAN.md section 6).
 *
 * Typical host-side use (e.g. a libmonome platform stub):
 *
 *   gs64sim_t *s = gs64sim_new("64vb-sim.elf", NULL, 0);
 *   gs64sim_run_us(s, 300000);                    // let the firmware boot
 *   gs64sim_host_write(s, (uint8_t[]){0x00}, 1);  // platform_write()
 *   gs64sim_run_until_tx(s, 1, 250000);           // platform_wait_for_input()
 *   n = gs64sim_host_read(s, buf, sizeof buf);    // platform_read()
 */
#ifndef GS64SIM_H
#define GS64SIM_H

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct gs64sim gs64sim_t;

/* MAX7219 word latched on LOAD rising edge.  start = cycle of the first CLK rising edge
 * of this word, nbits = CLK edges since the previous LOAD rising edge (16 if clean). */
typedef void (*gs64sim_max_cb)(void *ctx, uint64_t cycle, uint8_t addr, uint8_t data,
			       uint64_t start, int nbits);
/* byte the firmware wrote to the FT245 (WR falling edge) */
typedef void (*gs64sim_tx_cb)(void *ctx, uint64_t cycle, uint8_t byte);

/* mcu NULL = "atmega1281", freq 0 = 16 MHz.  Returns NULL on load failure. */
gs64sim_t *gs64sim_new(const char *elf, const char *mcu, uint32_t freq);
void gs64sim_free(gs64sim_t *s);

/* run.  Return value: 0 running, 1 firmware stopped (sleep with interrupts off / done),
 * 2 crashed. */
int gs64sim_run_cycles(gs64sim_t *s, uint64_t n);
int gs64sim_run_us(gs64sim_t *s, double us);
/* run until at least `nbytes` device->host bytes are pending or max_us elapsed.
 * Returns the number of pending bytes. */
size_t gs64sim_run_until_tx(gs64sim_t *s, size_t nbytes, double max_us);
uint64_t gs64sim_cycles(const gs64sim_t *s);
double gs64sim_time_us(const gs64sim_t *s);
uint32_t gs64sim_freq(const gs64sim_t *s);

/* host -> device: bytes are appended to the FT245 receive FIFO (RXF goes low). */
void gs64sim_host_write(gs64sim_t *s, const uint8_t *buf, size_t n);
size_t gs64sim_rx_pending(const gs64sim_t *s);
/* device -> host: pop captured bytes. */
size_t gs64sim_host_read(gs64sim_t *s, uint8_t *buf, size_t max);
size_t gs64sim_tx_pending(const gs64sim_t *s);

/* keypad: row = value on PORTB bits 4..6 when the row is scanned, col = shift index
 * (0 = bit on E5 right after E4 LD goes high, i = after i CLK rising edges). */
void gs64sim_key(gs64sim_t *s, int row, int col, int down);

/* FT245 status pins (defaults: PWREN low = USB configured, TXE low = can accept) */
void gs64sim_set_pwren(gs64sim_t *s, int level);
void gs64sim_set_txe(gs64sim_t *s, int level);
/* ADC input in millivolts (AVCC = AREF = 5000 mV) */
void gs64sim_set_adc(gs64sim_t *s, int channel, uint32_t mv);

/* EEPROM access (any time) */
int gs64sim_eeprom_write(gs64sim_t *s, uint16_t addr, const uint8_t *buf, uint16_t n);
int gs64sim_eeprom_read(gs64sim_t *s, uint16_t addr, uint8_t *buf, uint16_t n);
uint16_t gs64sim_eeprom_size(const gs64sim_t *s);

/* observers */
void gs64sim_on_max_write(gs64sim_t *s, gs64sim_max_cb cb, void *ctx);
void gs64sim_on_tx(gs64sim_t *s, gs64sim_tx_cb cb, void *ctx);
/* write every MAX7219 word to f as "cycle addr data start nbits" (decimal) */
void gs64sim_trace_file(gs64sim_t *s, FILE *f);
/* latest value of each MAX7219 register (index = address 0..15) */
const uint8_t *gs64sim_max_regs(const gs64sim_t *s);
uint64_t gs64sim_max_count(const gs64sim_t *s);
/* protocol warnings so far (MAX words with nbits != 16, WR with DDRD != 0xFF,
 * RD while the FIFO is empty) */
uint64_t gs64sim_warnings(const gs64sim_t *s);

/* ISR watch: cb(entry, exit) each time the PC enters the byte-address range [lo, hi)
 * (e.g. an ISR function from avr-nm -S) and leaves it again.  entry = cycle at which
 * the first instruction in the range is about to run, exit = cycle after the
 * instruction that left it (reti).  lo = hi = 0 disables. */
typedef void (*gs64sim_isr_cb)(void *ctx, uint64_t entry, uint64_t exit);
void gs64sim_watch_isr(gs64sim_t *s, uint32_t lo, uint32_t hi, gs64sim_isr_cb cb, void *ctx);

/* escape hatch: the underlying avr_t * (struct avr_t from simavr) */
void *gs64sim_avr(gs64sim_t *s);

#ifdef __cplusplus
}
#endif
#endif
