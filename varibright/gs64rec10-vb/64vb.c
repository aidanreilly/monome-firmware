/************************************************************************
 gs64rec10 varibright firmware: mext protocol, per-LED brightness
 (revision 3, after the workstream A/C simulations; see ../REPORT.md)

 Derived from 64int.c (unfinished mext variant of this board), 64.c (the
 series build, used as the reference for pinout and physical orientation)
 and monome/mk firmware (default and tilt) for the mext packet handling.

 Board: ATmega325 @ 16 MHz.
   MAX7219 bit-banged on PORTE: E0 CLK, E1 LOAD, E2 DIN
   keypad 165-type shift register on PORTE: E3 CLK, E4 LD, E5 data in,
     row select on PORTB 4..6
   FT245 FIFO: PORTD data, PORTC C0 TXE, C1 RXF, C2 WR, C3 RD, C4 PWREN
   accelerometer on ADC0 / ADC1

 Brightness. A Timer1 CTC interrupt fires once per MAX7219 scan frame
 (period T_u, calibrated by the user against the chip's own oscillator).
 Every tick writes one shutdown-bracketed burst of 11 words:
     0x0C=0, 0x0A=code[f], digits 1..8 = frame f, 0x0C=1
 The chip is halted while its registers change, so it never shows a mixed
 state. The first word is written at a fixed Timer1 count (tick_align), so
 the tick is cycle-exact whatever the interrupt latency was.
 Two display modes share this burst and therefore one calibration:
   T-SD (default): constant intensity, level step s of P shown in s of P
        frames spread evenly (P = 3 or 4 from the calibrated rate, so 4 or
        5 brightness steps). Simulated rate tolerance about +-1.1..2 %.
   SD   (opt-in):  16 levels from intensity-weighted frames (tables
        15/15/6/15/11/15 or 15/15/7/15/3). Simulated tolerance +-0.1 %.
 Without a valid calibration in EEPROM the unit is a mono mext grid
 (levels > 7 on), written from the main loop with the frame timer off.

 Coordinates (identical to 64.c, which is the physical reference):
   LED (x, y)  = MAX7219 digit register x+1, data bit (7 - y)
   key (x, y)  = row select 7 - x, shift position 7 - y

 Concurrency (PLAN.md section 5): once the frame timer runs, only the
 Timer1 ISR touches PORTE bits 0..2. It rewrites PORTE with whole-byte
 writes that carry bits 3..7 through unchanged; main only uses sbi / cbi
 (single atomic instructions) on E3 / E4 and never writes PORTE as a byte
 while the timer runs. Interrupts are never disabled for more than a few
 cycles while the timer runs (keeps the tick alignment window).

 Validated by inspection and in simulation only. Not tested on hardware.
*************************************************************************/

#define F_CPU 16000000UL
#include <inttypes.h>
#include <avr/io.h>
#include <avr/interrupt.h>
#include <avr/eeprom.h>
#include <avr/pgmspace.h>
#include <util/delay.h>
#include <util/atomic.h>
#include "button.h"


/* ===================================================================
   SIM shim. simavr has no ATmega325 core, so `make sim` builds for the
   atmega1281. Only register and vector NAMES differ; no logic differs.
   (On the 1281 the Timer0 clock-select bits live in TCCR0B.)
   =================================================================== */
#ifdef SIM
#  define KEY_TIMER_vect TIMER0_COMPA_vect
#  define KEY_TIMER_INIT() do { TCCR0A = (1 << WGM01); \
                                TCCR0B = (1 << CS02) | (1 << CS00); } while (0)
#else
#  define KEY_TIMER_vect TIMER0_COMP_vect
#  define KEY_TIMER_INIT() do { TCCR0A = (1 << WGM01) | (1 << CS02) | (1 << CS00); } while (0)
#endif


/* ===================================================================
   options (pass with VBFLAGS)
   =================================================================== */
/* extra nop after every MAX7219 port write (signal-integrity margin).
   0 is within datasheet timing at 16 MHz, see max_word(). */
#ifndef VB_SHIFT_NOPS
#  define VB_SHIFT_NOPS 0
#endif
/* 1: only write to the FT245 while TXE is low. 0 (default): write blindly
   like every monome firmware does (TXE wiring is unverified on hardware). */
#ifndef VB_USE_TXE
#  define VB_USE_TXE 0
#endif
/* 1: mext tilt subsystem (accelerometer on ADC1 = x, ADC0 = y) */
#ifndef VB_TILT
#  define VB_TILT 1
#endif
/* Timer1 count at which the first word of each burst starts (tick_align).
   Must exceed the worst interrupt entry latency plus the ISR prologue:
   about 88 cycles from the compare match to the TCNT1 poll (response, jmp,
   15 pushes, loads) plus up to about 40 cycles when the key-timer ISR has
   just started or a 4..5-cycle instruction is executing. 160 leaves ~30. */
#ifndef VB_ALIGN_T0
#  define VB_ALIGN_T0 160
#endif

/* Timer1 frame period limits, 62.5 ns ticks. The period includes the
   ~56 us the chip spends in shutdown each tick. */
#define VB_PERIOD_MIN      12000u
#define VB_PERIOD_MAX      34000u
#define VB_DARK_TICKS      687u      /* 0x0C=0 .. 0x0C=1 LOAD edges, constant (measured in simavr) */
#define VB_DEFAULT_PERIOD  (20000u + VB_DARK_TICKS)   /* 800 Hz typical */
/* T-SD: P = 4 when f_s >= 750 Hz, else 3 (simulated windows >= +-1.1 %) */
#define VB_TSD_P4_MAX      (21333u + VB_DARK_TICKS)
/* SD: 6-frame table when f_s >= 600 Hz, else the 5-frame table */
#define VB_SD6_MAX         26700u

/* EEPROM calibration record, 5 bytes at EE_CAL_ADDR:
   [0] magic 0xB6  [1] cfg  [2] period low  [3] period high
   [4] cfg ^ lo ^ hi ^ 0x5A
   cfg bit 0: display mode (0 T-SD, 1 SD); bits 4..7: forced P (0 = auto).
   The 4-byte record 0xB5 of revision 2 (plain FLIP) is not accepted.
   Address 0 is avoided (most exposed to brown-out corruption). */
#define EE_CAL_ADDR   ((uint8_t *)0x10)
#define EE_CAL_MAGIC  0xB6
#define EE_CAL_XOR    0x5A

#define DM_TSD 0
#define DM_SD  1


/* ===================================================================
   protocol (mext), byte-exact with libmonome src/proto/mext.h
   =================================================================== */
#define SIZE_X 8
#define SIZE_Y 8
#define GRIDS 1

/* host -> device */
#define _SYS_QUERY 0x00
#define _SYS_QUERY_ID 0x01
#define _SYS_WRITE_ID 0x02
#define _SYS_GET_GRID_SIZE 0x05
#define _SYS_VB_GET 0x0A          /* extension, never sent by libmonome */
#define _SYS_VB_SET 0x0B          /* extension, never sent by libmonome */
#define VB_SET_KEY 0xA5           /* first payload byte of a valid 0x0B / 0x0C */
#define _SYS_ADC_CAPTURE 0x0C     /* extension: supply-ripple capture, see adc_capture() */

#define _LED_SET0 0x10
#define _LED_SET1 0x11
#define _LED_ALL0 0x12
#define _LED_ALL1 0x13
#define _LED_MAP 0x14
#define _LED_ROW 0x15
#define _LED_COL 0x16
#define _LED_INT 0x17
#define _LED_SETX 0x18
#define _LED_ALLX 0x19
#define _LED_MAPX 0x1A
#define _LED_ROWX 0x1B
#define _LED_COLX 0x1C

#define _TILT_GET_STATE 0x80
#define _TILT_ENABLE 0x81
#define _TILT_DISABLE 0x82

/* device -> host */
#define _SYS_QUERY_RESPONSE 0x00
#define _SYS_ID 0x01
#define _SYS_REPORT_GRID_SIZE 0x03
#define _SYS_VB_REPORT 0x0A       /* extension, only in reply to 0x0A/0x0B */
#define _KEY_UP 0x20
#define _KEY_DOWN 0x21
#define _TILT_STATES 0x80
#define _TILT_EVENT 0x81

#define SS_LED_GRID 1
#define SS_KEY_GRID 2
#define SS_TILT 8

/* _SYS_VB_REPORT status byte */
#define VBS_ACTIVE   0x01   /* varibright frame interrupt in use (period != 0) */
#define VBS_EE_VALID 0x02   /* EEPROM holds a valid calibration record */
#define VBS_PATTERN  0x04   /* calibration band pattern is showing */
#define VBS_PROBE    0x08   /* a probe pattern is showing */

/* host -> device total packet length (header included), = 1 + libmonome
   outgoing_payload_lengths[addr][cmd]. Every header libmonome does not
   list is a lone byte there (payload 0), and is consumed as such here. */
static const uint8_t len_sys[16] PROGMEM = {
	1, 1, 33, 1,  4, 1, 3, 1,  3, 1, 1, 6,  5, 1, 1, 1    /* 0x0A..0x0C: ext. */
};
static const uint8_t len_led[16] PROGMEM = {
	3, 3, 1, 1,  11, 4, 4, 2,  4, 2, 35, 7,  7, 1, 1, 1
};
static const uint8_t len_tilt[16] PROGMEM = {
	1, 2, 2, 1,  1, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1
};
static const uint8_t len_ring[16] PROGMEM = {
	4, 3, 34, 5,  3, 1, 1, 1,  1, 1, 1, 1,  1, 1, 1, 1
};
#define RX_MAX 35


/* ===================================================================
   pins and MAX7219 registers
   =================================================================== */
#define E0_CLK 0x01
#define E1_LOAD 0x02
#define E2_DIN 0x04
#define LED_MASK (E0_CLK | E1_LOAD | E2_DIN)

#define E3_CLK 0x08
#define E4_LD 0x10
#define E5_SER1 0x20

#define B4_A0 0x10
#define B5_A1 0x20
#define B6_A2 0x40

#define C0_TXE 0x01
#define C1_RXF 0x02
#define C2_WR 0x04
#define C3_RD 0x08
#define C4_PWREN 0x10

#define MAX_DIGIT0    0x01
#define MAX_DECODE    0x09
#define MAX_INTENSITY 0x0A
#define MAX_SCANLIMIT 0x0B
#define MAX_SHUTDOWN  0x0C
#define MAX_TEST      0x0F

/* timing */
#define KEY_TICK          25   /* timer0 /1024 CTC: 26 * 64 us = 1.664 ms, as 64.c */
#define RX_STARVE         20   /* max bytes read per main loop pass */
#define RX_TIMEOUT_TICKS  60   /* drop a partial packet after ~100 ms of silence */
#define RX_REPLY_ROOM     40   /* output ring room needed before reading a host byte */


/* ===================================================================
   Mode SD frame tables (workstream A recommendation 2). Codes in frame
   order; mask bit k = LED lit in frame k.
   =================================================================== */
#define NF_MAX 8
static const uint8_t sd6_code[6] PROGMEM = { 15, 15, 6, 15, 11, 15 };
static const uint8_t sd6_mask[16] PROGMEM = {
	0x00, 0x04, 0x10, 0x01, 0x05, 0x11, 0x09, 0x0d,
	0x19, 0x1d, 0x0f, 0x1b, 0x1f, 0x2f, 0x3b, 0x3f };
static const uint8_t sd5_code[5] PROGMEM = { 15, 15, 7, 15, 3 };
static const uint8_t sd5_mask[16] PROGMEM = {
	0x00, 0x10, 0x04, 0x14, 0x01, 0x11, 0x05, 0x15,
	0x09, 0x19, 0x0d, 0x1d, 0x0b, 0x1b, 0x0f, 0x1f };


/* ===================================================================
   globals
   =================================================================== */
static uint8_t lvl[8][8];              /* host level 0..15 of LED (x, y) */

/* frame buffer: fb[f][x] bit (7 - y) = LED (x, y) lit in frame f; each
   byte is the MAX7219 digit register image for digit x+1 */
volatile uint8_t fb[NF_MAX][8];
volatile uint8_t fcode[NF_MAX];        /* intensity code of each frame */
volatile uint8_t vb_nf = 1;            /* frames per cycle (ISR reads) */
static uint8_t lmask[16];              /* host level -> frame mask */
static uint8_t base_code[NF_MAX];      /* SD: unscaled frame codes */

static uint8_t mono_plane[8];          /* level > 7, same layout */
static uint8_t mono_dirty;

/* ISR state */
#define ISR_OFF    0                   /* frame timer stopped, main owns E0..E2 */
#define ISR_FRAMES 1                   /* frames (T-SD / SD / probe 4) */
#define ISR_CAL    2                   /* calibration band */
#define ISR_PROBE  3                   /* shutdown-toggle probes 1..3 */
volatile uint8_t isr_mode;
static uint8_t isr_f;                  /* ISR private: frame index */
static uint8_t cal_phase;              /* ISR private */
volatile uint16_t cal_period;          /* read by ISR in ISR_CAL */
volatile uint8_t cal_on[8] = { 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF };
/* probes 1..3 (ISR private after start) */
static uint16_t pr_awake, pr_dark, pr_pairs, pr_count;
static uint8_t pr_half, pr_ref;
/* probe 4: alternate between two periods every alt_n ticks */
static uint16_t alt_a, alt_b, alt_n, alt_cnt;
static uint8_t alt_sel;

/* what the display shows */
#define VIEW_NORMAL  0                 /* host levels (or mono) */
#define VIEW_PATTERN 1                 /* calibration band */
#define VIEW_PREVIEW 2                 /* level ramp test image (calibration UI) */
#define VIEW_PROBE1  3                 /* ... VIEW_PROBE1 + 3 = probe 4 */
static uint8_t vb_view;

static uint16_t vb_period;             /* 0 = mono (uncalibrated) */
static uint8_t vb_dmode;               /* DM_TSD / DM_SD */
static uint8_t vb_forcep;              /* T-SD: forced P, 0 = auto */
static uint8_t g_int = 15;             /* LED_INT global intensity */

volatile uint8_t scan_keypads;
/* debounced key events not yet delivered, in order: bit 7 down, bits 5..3 row, 2..0 shift */
#define KQ_LEN 32
static uint8_t kq[KQ_LEN];
static uint8_t kq_w, kq_r;

static uint8_t cal_active, cal_armed, cal_result, cal_dirty;

static uint8_t out_buf[256];           /* ring, uint8 indices wrap */
static uint8_t out_w, out_r;

static char id[32] = "monome 64";

#if VB_TILT
static uint8_t tilt_on, tilt_axis, tilt_index, tilt_prime;
static int8_t tilt_bucket[2][8];
static int16_t tilt_accum[2];
static int16_t tilt_val[2];
#endif


/* ===================================================================
   MAX7219 shifter: unrolled, no delays.
   One 16-bit word, MSB first (D15..D8 = address, D7..D0 = data).
   Per bit:  out PORTE, lo|hi   (CLK low, DIN valid)
             out PORTE, (..)|CLK (rising edge shifts DIN in)
   Constant time whatever the data (SHIFT_DATA is asm, addresses are
   compile-time constants in the ISR): 87 cycles (5.4 us) per word.
   Datasheet minimums are 50 ns CLK high / low, 25 ns DIN setup, 100 ns
   period; the tightest case here is 62.5 / 62.5 / 62.5 / 125 ns.
   LOAD: falls with the first write (tCSS 25 ns before the first rising
   CLK), rises one cycle after the last CLK falls (tCSH 0 ns) and stays
   high for >= 1 cycle (62.5 ns > tCSW 50 ns) before the next word.
   PORTE bits 3..7 come from `base` and are written back unchanged.
   =================================================================== */
#if VB_SHIFT_NOPS
#  define SHIFT_NOP() __asm__ __volatile__ ("nop")
#  define SHIFT_NOPS_ "nop\n\t"
#else
#  define SHIFT_NOP() do { } while (0)
#  define SHIFT_NOPS_ ""
#endif

/* address bit: `addr` is always a compile-time constant (see MAX_ROWS), so
   this folds into two plain `out` instructions */
#define SHIFT_BIT(v, b) do { \
		uint8_t t_ = lo; \
		if ((v) & (1 << (b))) t_ = hi; \
		PORTE = t_; SHIFT_NOP(); \
		PORTE = t_ | E0_CLK; SHIFT_NOP(); \
	} while (0)

/* data byte: constant time for every value (6 cycles per bit, no branch);
   left to the compiler, the last bit became a branch to a duplicated tail
   and the burst length depended on the data, which moved the wake edge */
#define SHIFT_DATA(lo, hi, d) do { \
		uint8_t t_; \
		__asm__ __volatile__( \
			".irp b,7,6,5,4,3,2,1,0\n\t" \
			"mov  %[t], %[l]\n\t" \
			"sbrc %[v], \\b\n\t" \
			"mov  %[t], %[h]\n\t" \
			"out  %[p], %[t]\n\t" SHIFT_NOPS_ \
			"ori  %[t], %[c]\n\t" \
			"out  %[p], %[t]\n\t" SHIFT_NOPS_ \
			".endr" \
			: [t] "=&d" (t_) \
			: [l] "r" (lo), [h] "r" (hi), [v] "r" (d), \
			  [p] "I" (_SFR_IO_ADDR(PORTE)), [c] "M" (E0_CLK)); \
	} while (0)

static inline void max_word(uint8_t base, uint8_t addr, uint8_t data)
	__attribute__((always_inline));
static inline void max_word(uint8_t base, uint8_t addr, uint8_t data)
{
	const uint8_t lo = base;
	const uint8_t hi = base | E2_DIN;

	PORTE = lo;                         /* LOAD low, CLK low */
	SHIFT_BIT(addr, 7); SHIFT_BIT(addr, 6); SHIFT_BIT(addr, 5); SHIFT_BIT(addr, 4);
	SHIFT_BIT(addr, 3); SHIFT_BIT(addr, 2); SHIFT_BIT(addr, 1); SHIFT_BIT(addr, 0);
	SHIFT_DATA(lo, hi, data);
	PORTE = lo;                         /* CLK low */
	PORTE = lo | E1_LOAD;               /* LOAD rising edge latches the word */
}

/* the 8 digit registers with constant addresses (no loop: a loop variable
   address would compile to data-dependent code) */
#define MAX_ROWS(base, expr) do { \
		max_word(base, 1, expr(0)); max_word(base, 2, expr(1)); \
		max_word(base, 3, expr(2)); max_word(base, 4, expr(3)); \
		max_word(base, 5, expr(4)); max_word(base, 6, expr(5)); \
		max_word(base, 7, expr(6)); max_word(base, 8, expr(7)); \
	} while (0)

/* main-loop write. Only allowed while the frame timer is off (PLAN.md 5);
   silently ignored otherwise. */
static void to_led(uint8_t addr, uint8_t data)
{
	if (isr_mode != ISR_OFF) return;
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		max_word(PORTE & ~LED_MASK, addr, data);
	}
}


/* ===================================================================
   Cycle-exact tick (workstream A recommendation 4). Spin until TCNT1L
   reaches VB_ALIGN_T0, then pad by the 0..4 cycles the 5-cycle poll loop
   overshot, so the code after this always starts at the same timer
   count. Each sbrc/rjmp pair costs 2 cycles, 3 when its bit is set.
   If the ISR was entered later than VB_ALIGN_T0 no compensation is
   possible and the burst simply starts late (counted in the tests).
   =================================================================== */
_Static_assert(VB_ALIGN_T0 + 4 < 256, "VB_ALIGN_T0 must fit TCNT1L");

static inline void tick_align(void) __attribute__((always_inline));
static inline void tick_align(void)
{
	uint8_t t;
	__asm__ __volatile__(
		"1:	lds  %0, %1"  "\n\t"
		"	cpi  %0, %2"  "\n\t"
		"	brlo 1b"      "\n\t"
		"	subi %0, %2"  "\n\t"
		"	cpi  %0, 5"   "\n\t"
		"	brsh 2f"      "\n\t"
		"	neg  %0"      "\n\t"
		"	subi %0, -4"  "\n\t"
		"	sbrc %0, 0"   "\n\t"
		"	rjmp .+0"     "\n\t"
		"	sbrc %0, 1"   "\n\t"
		"	rjmp .+0"     "\n\t"
		"	sbrc %0, 1"   "\n\t"
		"	rjmp .+0"     "\n\t"
		"	sbrc %0, 2"   "\n\t"
		"	rjmp .+0"     "\n\t"
		"	sbrc %0, 2"   "\n\t"
		"	rjmp .+0"     "\n\t"
		"	sbrc %0, 2"   "\n\t"
		"	rjmp .+0"     "\n\t"
		"	sbrc %0, 2"   "\n\t"
		"	rjmp .+0"     "\n\t"
		"2:"
		: "=&d" (t)
		: "n" (_SFR_MEM_ADDR(TCNT1L)), "M" (VB_ALIGN_T0));
}


/* ===================================================================
   Timer1 frame interrupt (CTC, prescale 1, period OCR1A + 1 ticks)
   =================================================================== */
ISR(TIMER1_COMPA_vect)
{
	uint8_t base = PORTE & ~LED_MASK;
	uint8_t mode = isr_mode;
	const volatile uint8_t *row = 0;
	uint8_t code = 15;

	if (mode == ISR_FRAMES) {
		uint8_t f = isr_f;
		row = fb[f];
		code = fcode[f];
		if (++f >= vb_nf) f = 0;
		isr_f = f;
		if (alt_n && --alt_cnt == 0) {  /* probe 4: TCNT1 is small here */
			alt_cnt = alt_n;
			alt_sel ^= 1;
			OCR1A = (alt_sel ? alt_b : alt_a) - 1;
		}
	}
	else if (mode == ISR_CAL) {
		/* single-bracket calibration band (workstream A section 5f):
		   all on for floor(T/2) through the very same burst code as a frame
		   (so the chip is halted exactly as long per period as in normal
		   display), all off for ceil(T/2) with a plain 8-word write. OCR1A
		   is not buffered in CTC mode, but TCNT1 has only just restarted. */
		uint16_t p = cal_period;
		uint16_t h = p >> 1;
		if (cal_phase) {
			OCR1A = h - 1;
			row = cal_on;
		}
		else {
			OCR1A = p - h - 1;
#define ALLOFF_(i) 0x00
			MAX_ROWS(base, ALLOFF_);
		}
		cal_phase ^= 1;
	}
	else if (mode == ISR_PROBE) {
		/* awake pr_awake ticks / shutdown pr_dark ticks, alternating
		   every pr_pairs pairs (about 1 s) with a reference phase in which
		   the chip stays awake. One code path after tick_align, so both
		   segment edges are cycle-exact; in the reference phase the
		   "shutdown" write is 0x0C=1. */
		uint8_t v = 1;
		if (!pr_half) {
			OCR1A = pr_dark - 1;
			pr_half = 1;
			v = pr_ref;
		}
		else {
			OCR1A = pr_awake - 1;
			pr_half = 0;
			if (--pr_count == 0) { pr_count = pr_pairs; pr_ref ^= 1; }
		}
		tick_align();
		max_word(base, MAX_SHUTDOWN, v);
		return;
	}

	if (row) {
		/* the burst: identical code for every frame and for the band */
		tick_align();
		max_word(base, MAX_SHUTDOWN, 0);
		max_word(base, MAX_INTENSITY, code);
#define ROW_(i) row[i]
		MAX_ROWS(base, ROW_);
		max_word(base, MAX_SHUTDOWN, 1);
	}
}

/* Start Timer1 in CTC mode, prescale 1, TOP = ocr. All 16-bit registers
   are written inside the atomic block; avr-gcc writes the high byte first
   as the datasheet requires. */
static void timer1_start(uint8_t mode, uint16_t ocr)
{
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		TCCR1B = 0;                 /* stop */
		TCCR1A = 0;
		TCNT1 = 0;
		OCR1A = ocr;
		TIFR1 = (1 << OCF1A);       /* drop a stale compare flag */
		isr_f = 0;
		cal_phase = 0;
		pr_half = 0;
		alt_cnt = alt_n;
		alt_sel = 0;
		isr_mode = mode;
		TIMSK1 |= (1 << OCIE1A);
		TCCR1B = (1 << WGM12) | (1 << CS10);
	}
}

/* After this returns the ISR is not running and will not run again: an
   ISR in flight completes before main resumes, and the flag is cleared. */
static void timer1_stop(void)
{
	ATOMIC_BLOCK(ATOMIC_RESTORESTATE) {
		TIMSK1 &= ~(1 << OCIE1A);
		TCCR1B = 0;
		TIFR1 = (1 << OCF1A);
		isr_mode = ISR_OFF;
	}
}


/* ===================================================================
   level -> frame mapping and intensity
   =================================================================== */
/* T-SD: s of P frames on, spread evenly (first-order delta-sigma) */
static uint8_t spread_mask(uint8_t s, uint8_t P)
{
	uint8_t k, acc = 0, m = 0;
	for (k = 0; k < P; k++) {
		acc += s;
		if (acc >= P) { acc -= P; m |= 1 << k; }
	}
	return m;
}

/* host level 0..15 -> step 0..P: 0 stays off, any nonzero level is at
   least step 1, 15 is P (round(L P / 15), minimax fit to a linear ramp) */
static uint8_t tsd_step(uint8_t L, uint8_t P)
{
	uint8_t s;
	if (!L) return 0;
	s = (uint8_t)((L * P * 2 + 15) / 30);
	return s ? s : 1;
}

static uint8_t tsd_p(void)
{
	if (vb_forcep) return vb_forcep;
	return vb_period <= VB_TSD_P4_MAX ? 4 : 3;
}

/* SD: c' = ((2c+1)(g+1)) >> 5 scales each frame's duty by (g+1)/16 */
static void sd_scale(uint8_t g, uint8_t *c)
{
	uint8_t f;
	for (f = 0; f < vb_nf; f++)
		c[f] = (uint8_t)(((uint16_t)(2 * base_code[f] + 1) * (g + 1)) >> 5);
}

static uint8_t sd_ramp_ok(const uint8_t *c)
{
	uint16_t last = 0, s;
	uint8_t l, f, m;
	for (l = 1; l < 16; l++) {
		m = lmask[l];
		s = 0;
		for (f = 0; f < vb_nf; f++, m >>= 1)
			if (m & 1) s += 2 * c[f] + 1;
		if (s <= last) return 0;
		last = s;
	}
	return 1;
}

/* exact: T-SD shows g as the chip intensity; SD uses the smallest g' >= g
   whose 16-level ramp is still strictly increasing. Not exact (fades):
   plain scaling. */
static void intensity_apply(uint8_t g, uint8_t exact)
{
	uint8_t c[NF_MAX], f;
	if (vb_view == VIEW_NORMAL && !vb_period) { to_led(MAX_INTENSITY, g); return; }
	if (vb_view != VIEW_NORMAL && vb_view != VIEW_PREVIEW) return;
	if (vb_dmode == DM_SD) {
		for (;;) {
			sd_scale(g, c);
			if (!exact || g >= 15 || sd_ramp_ok(c)) break;
			g++;
		}
	}
	else for (f = 0; f < vb_nf; f++) c[f] = g;
	for (f = 0; f < vb_nf; f++) fcode[f] = c[f];   /* byte writes */
}

static void fb_led(uint8_t x, uint8_t y, uint8_t l)
{
	uint8_t bit = 0x80 >> y, m = lmask[l], f;
	for (f = 0; f < vb_nf; f++, m >>= 1) {
		if (m & 1) fb[f][x] |= bit;
		else fb[f][x] &= ~bit;
	}
}

/* rebuild lmask and the frame buffer for the current mode (frame codes
   come from intensity_apply). Timer must be stopped. */
static void vb_configure(void)
{
	uint8_t L, x, y, P;
	if (vb_dmode == DM_SD) {
		const uint8_t *cp = sd6_code, *mp = sd6_mask;
		P = 6;
		if (vb_period > VB_SD6_MAX) { cp = sd5_code; mp = sd5_mask; P = 5; }
		vb_nf = P;
		for (x = 0; x < P; x++) base_code[x] = pgm_read_byte(&cp[x]);
		for (L = 0; L < 16; L++) lmask[L] = pgm_read_byte(&mp[L]);
	}
	else {
		P = tsd_p();
		vb_nf = P;
		for (L = 0; L < 16; L++) lmask[L] = spread_mask(tsd_step(L, P), P);
	}
	for (x = 0; x < 8; x++)
		for (y = 0; y < 8; y++) fb_led(x, y, lvl[x][y]);
}

static void mono_refresh(void)
{
	uint8_t d;
	mono_dirty = 0;
	for (d = 0; d < 8; d++) to_led(MAX_DIGIT0 + d, mono_plane[d]);
}

static uint16_t run_period(void)
{
	return vb_period ? vb_period : VB_DEFAULT_PERIOD;
}

/* probes (workstream A section 5g; numbered low intensity first) */
static void probe_start(uint8_t n)
{
	uint8_t d;
	to_led(MAX_INTENSITY, n == 1 ? 0 : 15);
	for (d = 0; d < 8; d++) to_led(MAX_DIGIT0 + d, 0xFF);
	to_led(MAX_SHUTDOWN, 1);
	if (n == 3) { pr_awake = 6400; pr_dark = 1600; pr_pairs = 2000; }   /* 400/100 us */
	else        { pr_awake = 800;  pr_dark = 800;  pr_pairs = 10000; }  /* 50/50 us */
	pr_count = pr_pairs;
	pr_ref = 1;                         /* reference second first */
	timer1_start(ISR_PROBE, pr_awake - 1);
}

/* start what vb_view / vb_period select (timer must be stopped) */
static void display_start(uint8_t g)
{
	uint16_t p = run_period();
	uint8_t f, d;

	alt_n = 0;
	to_led(MAX_TEST, 0);
	to_led(MAX_SCANLIMIT, 7);
	to_led(MAX_DECODE, 0);
	to_led(MAX_SHUTDOWN, 1);

	switch (vb_view) {
	case VIEW_PATTERN:
		cal_period = p;                 /* timer stopped: plain write is safe */
		timer1_start(ISR_CAL, (p >> 1) - 1);
		return;
	case VIEW_PROBE1:
	case VIEW_PROBE1 + 1:
	case VIEW_PROBE1 + 2:
		probe_start(vb_view - VIEW_PROBE1 + 1);
		return;
	case VIEW_PROBE1 + 3:
		/* write-effect / latch probe: T-SD, P = 4, every LED at step 2,
		   2 s at the calibrated period, 2 s at +0.5 % */
		vb_nf = 4;
		for (f = 0; f < 4; f++) {
			fcode[f] = 15;
			for (d = 0; d < 8; d++) fb[f][d] = ((spread_mask(2, 4) >> f) & 1) ? 0xFF : 0x00;
		}
		alt_a = p;
		alt_b = p + p / 200;
		alt_n = (uint16_t)(32000000UL / p);
		timer1_start(ISR_FRAMES, p - 1);
		return;
	case VIEW_PREVIEW:
		vb_configure();
		intensity_apply(g, 0);
		timer1_start(ISR_FRAMES, p - 1);
		return;
	default:
		if (vb_period) {
			vb_configure();
			intensity_apply(g, 0);
			timer1_start(ISR_FRAMES, vb_period - 1);
		}
		else {
			to_led(MAX_INTENSITY, g);
			mono_refresh();
		}
	}
}


/* ===================================================================
   EEPROM calibration record (avr-libc disables interrupts only around
   the EEMPE/EEPE pair itself; the frame ISR keeps running otherwise)
   =================================================================== */
static uint16_t ee_cal_read(uint8_t *cfg)
{
	uint8_t m = eeprom_read_byte(EE_CAL_ADDR);
	uint8_t c = eeprom_read_byte(EE_CAL_ADDR + 1);
	uint8_t lo = eeprom_read_byte(EE_CAL_ADDR + 2);
	uint8_t hi = eeprom_read_byte(EE_CAL_ADDR + 3);
	uint8_t k = eeprom_read_byte(EE_CAL_ADDR + 4);
	uint16_t p = ((uint16_t)hi << 8) | lo;

	if (m != EE_CAL_MAGIC || k != (uint8_t)(c ^ lo ^ hi ^ EE_CAL_XOR)) return 0;
	if (p < VB_PERIOD_MIN || p > VB_PERIOD_MAX) return 0;
	if (cfg) *cfg = c;
	return p;
}

/* p = 0 invalidates the record (unit returns to mono at next power-up).
   The magic byte is cleared first and written last, so a reset part-way
   leaves an invalid record rather than a wrong one. */
static void ee_cal_write(uint16_t p, uint8_t cfg)
{
	uint8_t lo = p & 0xFF, hi = p >> 8;
	eeprom_update_byte(EE_CAL_ADDR, 0xFF);
	if (!p) return;
	eeprom_update_byte(EE_CAL_ADDR + 1, cfg);
	eeprom_update_byte(EE_CAL_ADDR + 2, lo);
	eeprom_update_byte(EE_CAL_ADDR + 3, hi);
	eeprom_update_byte(EE_CAL_ADDR + 4, cfg ^ lo ^ hi ^ EE_CAL_XOR);
	eeprom_update_byte(EE_CAL_ADDR, EE_CAL_MAGIC);
}

static uint8_t vb_cfg(void)
{
	return vb_dmode | (vb_forcep << 4);
}

static void vb_set_cfg(uint8_t c)
{
	uint8_t fp = c >> 4;
	vb_dmode = c & 1;
	vb_forcep = (fp >= 2 && fp <= NF_MAX) ? fp : 0;
}


/* ===================================================================
   levels. Only main writes lvl and the frame buffer (byte
   read-modify-writes); the ISR only reads, so a frame may show a
   half-applied command, which is gone by the next cycle.
   =================================================================== */
static void set_led(uint8_t x, uint8_t y, uint8_t l)
{
	uint8_t bit;
	if (x > 7 || y > 7) return;
	if (l > 15) l = 15;
	lvl[x][y] = l;
	if (vb_view == VIEW_NORMAL) fb_led(x, y, l);
	bit = 0x80 >> y;
	if (l > 7) mono_plane[x] |= bit;
	else mono_plane[x] &= ~bit;
	mono_dirty = 1;
}

static void set_all(uint8_t l)
{
	uint8_t x, y;
	for (x = 0; x < 8; x++)
		for (y = 0; y < 8; y++) set_led(x, y, l);
}


/* ===================================================================
   output ring. Messages are queued whole or not at all, so the host's
   framing can never be broken by a full buffer.
   =================================================================== */
static uint8_t out_room(uint8_t n)
{
	return (uint8_t)(out_r - out_w - 1) >= n;
}

static void out_put(uint8_t b)
{
	out_buf[out_w++] = b;
}

/* 0A status cfg nframes view run_hi run_lo ee_hi ee_lo */
static void out_vb_report(void)
{
	uint8_t c = 0;
	uint16_t ee = ee_cal_read(&c);
	uint8_t s = 0;
	if (!out_room(9)) return;
	if (vb_period) s |= VBS_ACTIVE;
	if (ee) s |= VBS_EE_VALID;
	if (vb_view == VIEW_PATTERN) s |= VBS_PATTERN;
	if (vb_view >= VIEW_PROBE1) s |= VBS_PROBE;
	out_put(_SYS_VB_REPORT);
	out_put(s);
	out_put(vb_cfg());
	out_put(vb_period ? vb_nf : 0);
	out_put(vb_view);
	out_put(vb_period >> 8);
	out_put(vb_period & 0xFF);
	out_put(ee >> 8);
	out_put(ee & 0xFF);
}

static void out_flush(void)
{
	if (out_r == out_w) return;
	PORTD = 0;
	DDRD = 0xFF;
	while (out_r != out_w) {
#if VB_USE_TXE
		if (PINC & C0_TXE) break;       /* FIFO full: keep the rest */
#endif
		PORTC |= C2_WR;
		PORTD = out_buf[out_r];
		PORTC &= ~C2_WR;                /* FT245 latches on WR falling */
		out_r++;
	}
	DDRD = 0;
}


/* ===================================================================
   keypad (key (x, y) = row select 7 - x, shift position 7 - y, as 64.c)
   =================================================================== */
static uint8_t read_row(uint8_t r)
{
	uint8_t s, v = 0;

	PORTB = r << 4;
	_delay_us(100);                     /* settle: high resistance pull-ups */
	PORTE |= E4_LD;                     /* sbi: atomic against the frame ISR */
	_delay_us(1);
	for (s = 0; s < 8; s++) {
		if (!(PINE & E5_SER1)) v |= (1 << s);
		PORTE |= E3_CLK;
		_delay_us(1);
		PORTE &= ~E3_CLK;
		_delay_us(1);
	}
	PORTE &= ~E4_LD;
	return v;
}

static void cal_key(uint8_t x, uint8_t y, uint8_t down);

static void scan_keys(void)
{
	uint8_t r, s, bit, down;

	for (r = 0; r < 8; r++) {
		button_last[r] = button_current[r];
		button_current[r] = read_row(r);
		for (s = 0; s < 8; s++) {
			buttonCheck(r, s);
			/* buttonCheck overwrites the row's event byte, so move each
			   event out at once (64.c consumes them the same way) */
			bit = 1 << s;
			if (button_event[r] & bit) {
				button_event[r] &= ~bit;
				/* queue full (host not reading): the newest event is dropped */
				if ((uint8_t)(kq_w - kq_r) < KQ_LEN)
					kq[kq_w++ & (KQ_LEN - 1)] = ((button_state[r] & bit) ? 0x80 : 0) | (r << 3) | s;
			}
		}
	}

	/* deliver in order; an event that does not fit waits for the next scan */
	while (kq_r != kq_w) {
		uint8_t e = kq[kq_r & (KQ_LEN - 1)];
		r = (e >> 3) & 7;
		s = e & 7;
		down = e >> 7;
		if (cal_active) cal_key(7 - r, 7 - s, down);
		else {
			if (!out_room(3)) return;
			out_put(down ? _KEY_DOWN : _KEY_UP);
			out_put(7 - r);
			out_put(7 - s);
		}
		kq_r++;
	}
}

static uint8_t any_key_down(void)
{
	uint8_t r, any = 0;
	for (r = 0; r < 8; r++) any |= button_state[r];
	return any;
}


/* ===================================================================
   tilt (mext subsystem 8, as monome/mk tilt firmware): one sensor,
   x = ADC1, y = ADC0, 8-bit reading centred on 0, 8-sample moving
   average per axis, one axis per key tick. Event 0x81 n xL xH yL yH zL zH
   (int16 little endian, z = 0) whenever an average changes, only while
   the host has enabled the sensor.
   =================================================================== */
#if VB_TILT
static void tilt_enable(uint8_t on)
{
	tilt_on = on;
	if (!on) return;
	tilt_axis = 0;
	tilt_index = 0;
	tilt_prime = 3;
	ADMUX = (1 << MUX0);
	ADCSRA |= (1 << ADSC);
}

static void tilt_step(void)
{
	uint8_t ax = tilt_axis, i;
	int8_t a;
	int16_t v;

	if (ADCSRA & (1 << ADSC)) return;   /* conversion still running */
	a = (int8_t)((ADCW >> 2) - 128);

	if (tilt_prime & (1 << ax)) {
		tilt_prime &= ~(1 << ax);
		for (i = 0; i < 8; i++) tilt_bucket[ax][i] = a;
		tilt_accum[ax] = 8 * (int16_t)a;
	}
	tilt_accum[ax] += a - tilt_bucket[ax][tilt_index];
	tilt_bucket[ax][tilt_index] = a;
	v = tilt_accum[ax] >> 3;

	if (ax) { ADMUX = (1 << MUX0); tilt_axis = 0; tilt_index = (tilt_index + 1) & 7; }
	else    { ADMUX = 0;           tilt_axis = 1; }
	ADCSRA |= (1 << ADSC);

	if (v == tilt_val[ax] && !tilt_prime) return;
	tilt_val[ax] = v;
	if (tilt_prime || !out_room(8)) return;
	out_put(_TILT_EVENT);
	out_put(0);
	out_put(tilt_val[0] & 0xFF);
	out_put((uint16_t)tilt_val[0] >> 8);
	out_put(tilt_val[1] & 0xFF);
	out_put((uint16_t)tilt_val[1] >> 8);
	out_put(0);
	out_put(0);
}
#endif


/* ===================================================================
   calibration UI (hold key (0,0) at power-up). See README-varibright.md.
   y = 0: x0 -100, x1 -10, x2 -1, x3 +1, x4 +10, x5 +100 ticks,
          x6 exit without saving, x7 save and exit
   y = 1: x0 mode T-SD, x1 mode SD, x2 P auto, x3 P = 3, x4 P = 4,
          x5 erase calibration (mono) and exit
   y = 2: x0 calibration band, x1 preview (level ramp in the selected
          mode), x4 probe 1 (intensity 0), x5 probe 2, x6 probe 3,
          x7 probe 4 (write-effect / latch)
   Keys are ignored until every key (including (0,0)) has been released.
   =================================================================== */
#define CAL_RUN     0
#define CAL_SAVE    1
#define CAL_DISCARD 2
#define CAL_ERASE   3

static void cal_key(uint8_t x, uint8_t y, uint8_t down)
{
	int16_t step = 0;
	if (!down || !cal_armed || cal_result != CAL_RUN) return;

	if (y == 0) {
		switch (x) {
		case 0: step = -100; break;
		case 1: step = -10; break;
		case 2: step = -1; break;
		case 3: step = 1; break;
		case 4: step = 10; break;
		case 5: step = 100; break;
		case 6: cal_result = CAL_DISCARD; return;
		case 7: cal_result = CAL_SAVE; return;
		}
		if (step) {
			int32_t p = (int32_t)vb_period + step;
			if (p < VB_PERIOD_MIN) p = VB_PERIOD_MIN;
			if (p > VB_PERIOD_MAX) p = VB_PERIOD_MAX;
			vb_period = (uint16_t)p;
			cal_dirty = 1;
		}
	}
	else if (y == 1) {
		switch (x) {
		case 0: vb_dmode = DM_TSD; break;
		case 1: vb_dmode = DM_SD; break;
		case 2: vb_forcep = 0; break;
		case 3: vb_forcep = 3; break;
		case 4: vb_forcep = 4; break;
		case 5: cal_result = CAL_ERASE; return;
		default: return;
		}
		cal_dirty = 1;
	}
	else if (y == 2) {
		switch (x) {
		case 0: vb_view = VIEW_PATTERN; break;
		case 1: vb_view = VIEW_PREVIEW; break;
		case 4: case 5: case 6: case 7: vb_view = VIEW_PROBE1 + x - 4; break;
		default: return;
		}
		cal_dirty = 1;
	}
}

static void blink_all(uint8_t n)
{
	uint8_t d;
	while (n--) {
		for (d = 0; d < 8; d++) to_led(MAX_DIGIT0 + d, 0xFF);
		_delay_ms(150);
		for (d = 0; d < 8; d++) to_led(MAX_DIGIT0 + d, 0x00);
		_delay_ms(150);
	}
}

static void calibrate(void)
{
	uint16_t keep_p = vb_period;
	uint8_t keep_c = vb_cfg(), x, y, d;

	cal_active = 1;
	cal_armed = 0;
	cal_result = CAL_RUN;
	if (!vb_period) vb_period = VB_DEFAULT_PERIOD;
	/* preview image: column x shows levels 2x (top half) and 2x+1 */
	for (x = 0; x < 8; x++)
		for (y = 0; y < 8; y++) lvl[x][y] = 2 * x + (y >= 4);
	vb_view = VIEW_PATTERN;
	cal_dirty = 1;

	/* run until a result is chosen and every key is released again */
	while (cal_result == CAL_RUN || any_key_down()) {
		if (cal_dirty && cal_result == CAL_RUN) {
			cal_dirty = 0;
			timer1_stop();
			display_start(15);
		}
		if (scan_keypads) {
			scan_keypads = 0;
			scan_keys();
			if (!any_key_down()) cal_armed = 1;
		}
	}

	timer1_stop();
	cal_active = 0;
	vb_view = VIEW_NORMAL;
	alt_n = 0;
	for (x = 0; x < 8; x++)
		for (y = 0; y < 8; y++) lvl[x][y] = 0;
	to_led(MAX_SHUTDOWN, 1);
	to_led(MAX_INTENSITY, 15);
	for (d = 0; d < 8; d++) to_led(MAX_DIGIT0 + d, 0);

	if (cal_result == CAL_SAVE) {
		ee_cal_write(vb_period, vb_cfg());
		blink_all(2);
	}
	else if (cal_result == CAL_ERASE) {
		ee_cal_write(0, 0);
		vb_period = 0;
		blink_all(1);
	}
	else {                              /* discard: back to the stored state */
		vb_period = keep_p;
		vb_set_cfg(keep_c);
	}
	buttonInit();
}


/* ===================================================================
   keypad timer
   =================================================================== */
ISR(KEY_TIMER_vect)
{
	scan_keypads = 1;
}


/* ===================================================================
   supply-ripple capture (experiment: find the MAX7219 scan rate with no
   test equipment). The columns in `cols` are lit at full intensity, so
   the chip draws a current pulse once per scan cycle. The ADC runs free
   on channel `mux` (0x1E = internal 1.1 V bandgap) against the same AREF
   reference the tilt code uses, so a supply dip shows as a reading
   change. 16 MHz / 64 / 13 cycles = 19230.77 samples/s, 10 bits.

   Stream: per block, a marker 0xC0 | (block & 0x1F), then 256 samples
   as two bytes each: 0x80 | (v >> 5), then v & 0x1F. End marker 0xFE.
   Sample bytes never fall in 0xC0..0xFF, so the host can resync and
   count dropped bytes. Blocking; host input stays in the FT245 FIFO.

   mux bit 7 (ADC_LIVE): leave the display and frame timer running and
   ignore `cols`, to measure the running display (flicker). mux bit 6
   (ADC_SLOW): ADC clock /128, 9615.38 samples/s. Use it with ADC_LIVE:
   one sample then takes 104 us, longer than the frame ISR (62.1 us), so
   the main loop cannot miss a sample while the ISR runs.
   mux bit 5 (ADC_DEC8): send the sum of each 8 consecutive samples
   instead of every sample (13 bits: 0x80 | (sum >> 7), then sum & 0x7F).
   1/8 the data rate, so the FT245 link keeps up with no gaps.
   =================================================================== */
#define ADC_LIVE 0x80
#define ADC_SLOW 0x40
#define ADC_DEC8 0x20
static void adc_capture(uint8_t cols, uint8_t mux, uint8_t nblk)
{
	uint8_t d, blk, i;
	uint16_t v;

	if (!(mux & ADC_LIVE)) {
		timer1_stop();
		to_led(MAX_TEST, 0);
		to_led(MAX_SCANLIMIT, 7);
		to_led(MAX_DECODE, 0);
		to_led(MAX_INTENSITY, 15);
		for (d = 0; d < 8; d++) to_led(MAX_DIGIT0 + d, (cols >> d) & 1 ? 0xFF : 0x00);
		to_led(MAX_SHUTDOWN, 1);
	}
	out_flush();

	ADCSRA = 0;
	ADMUX = mux & 0x1F;                 /* REFS = 00 (AREF), right adjusted */
	ADCSRB = 0;                         /* free running */
	ADCSRA = (1 << ADEN) | (1 << ADATE) | (1 << ADIF) | (1 << ADPS2) | (1 << ADPS1)
	       | ((mux & ADC_SLOW) ? (1 << ADPS0) : 0);
	ADCSRA |= (1 << ADSC);
	_delay_ms(20);                      /* settle: mux, bandgap, display */

	PORTD = 0;
	DDRD = 0xFF;
	ADCSRA |= (1 << ADIF);              /* drop the pending sample */
	for (blk = 0; blk < nblk; blk++) {
		PORTC |= C2_WR; PORTD = 0xC0 | (blk & 0x1F); PORTC &= ~C2_WR;
		i = 0;
		do {
			if (mux & ADC_DEC8) {
				v = 0;
				for (d = 0; d < 8; d++) {
					while (!(ADCSRA & (1 << ADIF))) ;
					v += ADCW;
					ADCSRA |= (1 << ADIF);
				}
				PORTC |= C2_WR; PORTD = 0x80 | (uint8_t)(v >> 7); PORTC &= ~C2_WR;
				PORTC |= C2_WR; PORTD = (uint8_t)(v & 0x7F);      PORTC &= ~C2_WR;
				continue;
			}
			while (!(ADCSRA & (1 << ADIF))) ;
			v = ADCW;
			ADCSRA |= (1 << ADIF);
			PORTC |= C2_WR; PORTD = 0x80 | (uint8_t)(v >> 5); PORTC &= ~C2_WR;
			PORTC |= C2_WR; PORTD = (uint8_t)(v & 0x1F);      PORTC &= ~C2_WR;
		} while (++i);
	}
	PORTC |= C2_WR; PORTD = 0xFE; PORTC &= ~C2_WR;
	DDRD = 0;

	/* restore the tilt ADC setup and the display */
	ADCSRA = 0;
	ADMUX = (1 << MUX0);
	ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0);
#if VB_TILT
	if (tilt_on) tilt_enable(1);
#endif
	if (mux & ADC_LIVE) return;         /* display was never touched */
	display_start(g_int);
	intensity_apply(g_int, 1);
	mono_dirty = 1;
}


/* ===================================================================
   command handling. Offsets follow monome/mk: an offset selects the
   8x8 quadrant (offset >> 3); this unit only has quadrant 0, other
   quadrants are ignored.
   =================================================================== */
static void handle_packet(const uint8_t *rx)
{
	uint8_t i, j, b;

	switch (rx[0]) {
	case _SYS_QUERY:                    /* (subsystem, count) per subsystem */
		if (!out_room(9)) break;
		out_put(_SYS_QUERY_RESPONSE); out_put(SS_LED_GRID); out_put(GRIDS);
		out_put(_SYS_QUERY_RESPONSE); out_put(SS_KEY_GRID); out_put(GRIDS);
#if VB_TILT
		out_put(_SYS_QUERY_RESPONSE); out_put(SS_TILT); out_put(1);
#endif
		break;
	case _SYS_QUERY_ID:
		if (!out_room(33)) break;
		out_put(_SYS_ID);
		for (i = 0; i < 32; i++) out_put(id[i]);
		break;
	case _SYS_WRITE_ID:
		for (i = 0; i < 32; i++) id[i] = rx[1 + i];
		break;
	case _SYS_GET_GRID_SIZE:
		if (!out_room(3)) break;
		out_put(_SYS_REPORT_GRID_SIZE); out_put(SIZE_X); out_put(SIZE_Y);
		break;

	case _SYS_VB_GET:
		out_vb_report();
		break;
	case _SYS_VB_SET: {                 /* [0xA5, period hi, period lo, flags, cfg] */
		uint16_t p = ((uint16_t)rx[2] << 8) | rx[3];
		uint8_t fl = rx[4], probe = (fl >> 4) & 7;
		if (rx[1] != VB_SET_KEY) break;  /* not for us: consumed, no reply */
		if ((p == 0 || (p >= VB_PERIOD_MIN && p <= VB_PERIOD_MAX)) && probe <= 4) {
			timer1_stop();
			vb_period = p;
			vb_set_cfg(rx[5]);
			if (probe) vb_view = VIEW_PROBE1 + probe - 1;
			else if (p && (fl & 0x02)) vb_view = VIEW_PATTERN;
			else vb_view = VIEW_NORMAL;
			display_start(g_int);
			intensity_apply(g_int, 1);
			if (fl & 0x01) ee_cal_write(p, vb_cfg());
		}
		out_vb_report();
		break;
	}

	case _SYS_ADC_CAPTURE:              /* [0xA5, cols, mux, nblk] */
		if (rx[1] == VB_SET_KEY && rx[4]) adc_capture(rx[2], rx[3], rx[4]);
		break;

	case _LED_SET0:
	case _LED_SET1:                     /* [x, y] */
		set_led(rx[1], rx[2], rx[0] == _LED_SET1 ? 15 : 0);
		break;
	case _LED_ALL0:
	case _LED_ALL1:
		set_all(rx[0] == _LED_ALL1 ? 15 : 0);
		break;
	case _LED_MAP:                      /* [x_off, y_off, 8 rows], bit x of row y */
		if ((rx[1] | rx[2]) & 0xF8) break;
		for (j = 0; j < 8; j++) {
			b = rx[3 + j];
			for (i = 0; i < 8; i++, b >>= 1) set_led(i, j, (b & 1) ? 15 : 0);
		}
		break;
	case _LED_ROW:                      /* [x_off, y, data], bit x */
		if (rx[1] & 0xF8) break;
		b = rx[3];
		for (i = 0; i < 8; i++, b >>= 1) set_led(i, rx[2], (b & 1) ? 15 : 0);
		break;
	case _LED_COL:                      /* [x, y_off, data], bit y */
		if (rx[2] & 0xF8) break;
		b = rx[3];
		for (i = 0; i < 8; i++, b >>= 1) set_led(rx[1], i, (b & 1) ? 15 : 0);
		break;
	case _LED_INT:                      /* [g] */
		g_int = rx[1] & 0x0F;
		intensity_apply(g_int, 1);
		break;

	/* level commands. libmonome pack_nybbles: byte k = (level[2k] << 4) |
	   level[2k+1], i.e. high nybble = the even (left / upper) LED. */
	case _LED_SETX:                     /* [x, y, level] */
		set_led(rx[1], rx[2], rx[3]);
		break;
	case _LED_ALLX:                     /* [level] */
		set_all(rx[1]);
		break;
	case _LED_MAPX:                     /* [x_off, y_off, 32 bytes], row-major */
		if ((rx[1] | rx[2]) & 0xF8) break;
		for (j = 0; j < 8; j++) {
			for (i = 0; i < 4; i++) {
				b = rx[3 + j * 4 + i];
				set_led(2 * i,     j, b >> 4);
				set_led(2 * i + 1, j, b & 0x0F);
			}
		}
		break;
	case _LED_ROWX:                     /* [x_off, y, 4 bytes] */
		if (rx[1] & 0xF8) break;
		for (i = 0; i < 4; i++) {
			b = rx[3 + i];
			set_led(2 * i,     rx[2], b >> 4);
			set_led(2 * i + 1, rx[2], b & 0x0F);
		}
		break;
	case _LED_COLX:                     /* [x, y_off, 4 bytes] */
		if (rx[2] & 0xF8) break;
		for (i = 0; i < 4; i++) {
			b = rx[3 + i];
			set_led(rx[1], 2 * i,     b >> 4);
			set_led(rx[1], 2 * i + 1, b & 0x0F);
		}
		break;

#if VB_TILT
	case _TILT_GET_STATE:
		if (!out_room(2)) break;
		out_put(_TILT_STATES);
		out_put(tilt_on);
		break;
	case _TILT_ENABLE:                  /* [sensor] */
		if (rx[1] == 0) tilt_enable(1);
		break;
	case _TILT_DISABLE:                 /* [sensor] */
		if (rx[1] == 0) tilt_enable(0);
		break;
#endif

	default:                            /* led ring, set offset, ... : consumed, ignored */
		break;
	}
}

static uint8_t cmd_length(uint8_t b)
{
	const uint8_t *t;
	switch (b >> 4) {
	case 0x0: t = len_sys; break;
	case 0x1: t = len_led; break;
	case 0x8: t = len_tilt; break;
	case 0x9: t = len_ring; break;
	default: return 1;
	}
	return pgm_read_byte(&t[b & 0x0F]);
}


/* ===================================================================
   main
   =================================================================== */
int main(void)
{
	uint8_t i1, n, c = 0;
	uint8_t starve;
	uint8_t rx_count = 0, rx_length = 1, rx_timeout = 0;
	uint8_t rx[RX_MAX];
	uint8_t sleep_state = 1;

	/* pin assignments */
	PORTE = E1_LOAD;                    /* LOAD idles high */
	DDRE = ~(E5_SER1);                  /* all output except E5 */
	PORTB = 0;
	DDRB = B4_A0 | B5_A1 | B6_A2;
	PORTC = C3_RD;                      /* RD idles high, WR low */
	DDRC = C2_WR | C3_RD;
	PORTD = 0;
	DDRD = 0;

	/* led driver */
	to_led(MAX_TEST, 0);
	to_led(MAX_SCANLIMIT, 7);
	to_led(MAX_DECODE, 0);
	to_led(MAX_INTENSITY, 15);
	for (i1 = 0; i1 < 8; i1++) to_led(MAX_DIGIT0 + i1, 0);
	to_led(MAX_SHUTDOWN, 1);

	buttonInit();
	vb_period = ee_cal_read(&c);
	vb_set_cfg(vb_period ? c : 0);

	/* ADC for tilt: AREF, ADC1 first, /128 = 125 kHz */
	ADMUX = (1 << MUX0);
	ADCSRA = (1 << ADEN) | (1 << ADPS2) | (1 << ADPS1) | (1 << ADPS0);

	/* keypad timer (calibration mode needs it too) */
	KEY_TIMER_INIT();
	OCR0A = KEY_TICK;
	TIMSK0 |= (1 << OCIE0A);
	sei();

	/* calibration entry: key (0,0) = row 7, shift position 7, 3 reads */
	n = 0;
	for (i1 = 0; i1 < 3; i1++) {
		if (read_row(7) & 0x80) n++;
		_delay_ms(10);
	}
	if (n == 3) calibrate();
	set_all(0);

	/* startup sequence (as 64.c) */
	to_led(1, 0x60);
	_delay_ms(64);
	to_led(MAX_INTENSITY, 7);
	to_led(1, 0x90); to_led(2, 0x60);
	_delay_ms(64);
	to_led(MAX_INTENSITY, 3);
	to_led(1, 0x08); to_led(2, 0x90); to_led(3, 0x60);
	_delay_ms(64);
	to_led(MAX_INTENSITY, 0);
	to_led(1, 0x08); to_led(2, 0x08); to_led(3, 0x10); to_led(4, 0xE0);
	_delay_ms(64);
	for (i1 = 0; i1 < 8; i1++) to_led(MAX_DIGIT0 + i1, 0);
	to_led(MAX_INTENSITY, 15);
	for (i1 = 0; i1 < 255; i1++) _delay_ms(8);

	while (1) {
		/* ========================= ASLEEP */
		if (sleep_state) {
			if (!(PINC & C4_PWREN)) {
				sleep_state = 0;
				display_start(0);           /* timer is off here */
				for (i1 = 0; i1 < 64; i1++) {   /* fade in */
					intensity_apply((uint8_t)((i1 * (g_int + 1)) >> 6), 0);
					_delay_ms(8);
				}
				intensity_apply(g_int, 1);
				rx_count = 0;
				scan_keypads = 0;
			}
			else {
				for (i1 = 0; i1 < 64; i1++) _delay_ms(8);
			}
			continue;
		}

		/* ========================= AWAKE */

		/* read incoming serial */
		PORTD = 0;
		DDRD = 0;
		starve = 0;
		/* leave host bytes in the FT245 FIFO while the output ring could not take
		   the largest reply (33 bytes), so replies are never dropped */
		while ((PINC & C1_RXF) == 0 && starve < RX_STARVE && out_room(RX_REPLY_ROOM)) {
			uint8_t b;
			starve++;
			PORTC &= ~C3_RD;
			_delay_us(1);                   /* wait for valid data */
			b = PIND;
			PORTC |= C3_RD;
			_delay_us(1);                   /* RD precharge, RXF update */

			if (rx_count == 0) rx_length = cmd_length(b);
			rx[rx_count++] = b;
			rx_timeout = 0;
			if (rx_count >= rx_length) {
				rx_count = 0;
				handle_packet(rx);
			}
		}

		/* mono: show changed LEDs directly, once per batch */
		if (mono_dirty && isr_mode == ISR_OFF && vb_view == VIEW_NORMAL) mono_refresh();

		/* keypad and tilt */
		if (scan_keypads) {
			scan_keypads = 0;
			scan_keys();
#if VB_TILT
			if (tilt_on) tilt_step();
#endif
			/* only silence counts: bytes held back by the ring check are not lost */
			if (rx_count && (PINC & C1_RXF) && ++rx_timeout > RX_TIMEOUT_TICKS) rx_count = 0;
		}

		out_flush();

		/* usb suspend / unplug */
		if (PINC & C4_PWREN) {
			sleep_state = 1;
			for (i1 = 0; i1 < 16; i1++) {   /* fade out */
				intensity_apply((uint8_t)(((15 - i1) * g_int) / 15), 0);
				_delay_ms(32);
			}
			timer1_stop();
			to_led(MAX_SHUTDOWN, 0);
			out_r = out_w;                  /* drop unsent output */
			kq_r = kq_w;                    /* drop undelivered key events */
		}
	}

	return 0;
}
