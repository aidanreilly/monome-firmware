# Varibright on gs64rec10 (MAX7219): plan and shared spec

Target: `gs64rec10-vb/` (copy of tehn/monome-firmware `gs64rec10`, baseline commit in this repo).
Hardware: ATmega325 @ 16 MHz, one MAX7219 bit-banged on PORTE (E0 CLK, E1 LOAD, E2 DIN),
keypad shift registers on PORTE (E3 CLK, E4 LD, E5 data in) with row select on PORTB 4..6,
FT245 parallel FIFO on PORTD data and PORTC (C0 TXE, C1 RXF, C2 WR, C3 RD, C4 PWREN).
No hardware is available. Everything is validated in simulation and must be labelled as such.

## 1. Why naive approaches flicker

The MAX7219 scans 8 digits from its own RC oscillator (f_s typ 800 Hz, datasheet range
500..1300 Hz). Each digit is lit for 1/8 of a scan frame (about 156 us at 800 Hz). There is
no sync output. LED light = register bit m(t) multiplied by the slot window w(t). Any
spectral content of m(t) within about 70 Hz of n * f_s (n = 1..10) folds down to visible
flicker or slowly rolling row bands. The MCU cannot rewrite 8 digit registers fast enough to
run many PWM periods inside one 156 us slot, so software PWM or BCM in the time domain beats
against the scan.

## 2. Scheme: frame-locked intensity-weighted bit planes (FLIP)

1. Store 4-bit levels as 4 bit planes: `plane[p][digit]`, p = 3 (MSB) .. 0.
2. A Timer1 compare ISR fires once per MAX7219 scan frame (period T_u, target T_u = 1/f_s).
   Each tick shows the next plane: write the intensity register (0x0A) with the plane's
   intensity code and rewrite digit registers 1..8 with that plane's bits.
3. Default intensity codes per plane: 15, 7, 3, 1 (MAX7219 duty = (2n+1)/32, so weights
   31, 15, 7, 3). The weighting is done by the chip's own in-slot PWM, which is synchronous
   with its scan by construction. A full cycle is 4 frames: 200 Hz at f_s = 800 Hz, 125 Hz at
   500 Hz. Peak brightness is 56/128 of stock.
4. Because m(t) is piecewise constant over frames of length T_u close to 1/f_s, its spectrum
   has zero-order-hold nulls at multiples of 1/T_u. A slot that straddles a frame boundary
   shows a blend of two consecutive planes and the long-run average is preserved, so phase is
   irrelevant. A rate mismatch produces a slow cross-fade "slip" whose net effect is a small
   static brightness offset. Predicted tolerance: |T_u * f_s - 1| under roughly 2 to 3 %.
   Predicted bad zones outside that: ratios near 4n/(4n +- 1) (0.80, 0.89, 0.92, 0.94, 1.07,
   1.09, 1.14, 1.33). Simulation must confirm or correct these numbers.
5. Burst hazard: during the register burst the chip briefly holds a mixed state (new
   intensity with old rows or the reverse). The burst must be short. Replace the stock
   `to_led` (1 us delay per bit) with an unrolled delay-free shifter, target under 10 us per
   16-bit write and about 100 us per 9-write burst. Write order and "skip unchanged rows" are
   open choices for the simulation to settle.

## 3. Rate calibration (the chip gives no feedback)

T_u is stored in EEPROM as a uint16 Timer1 tick count (prescale 1, 62.5 ns ticks, valid range
12000..33000) with a magic byte and checksum.

* Uncalibrated EEPROM: firmware behaves exactly like the legacy mono firmware and level
  messages threshold at > 7.
* Calibration mode: hold key (0,0) at power-up. The ISR runs at 2 / T_u and alternates all
  LEDs on and all LEDs off, so half of the rows appear lit and the lit band rolls at
  |1/T_u - f_s| Hz. Keys in the top row adjust T_u (coarse down, fine down, fine up, coarse
  up), another key saves and exits. The user nulls the roll by eye.
* Drift of the MAX7219 oscillator with temperature is unknown and cannot be simulated.
  Document it as the main hardware risk.

## 4. Protocol

Build on the mext variant (`64int.c`), since hosts (serialosc, libmonome) send level
messages only in mext: add 0x18 LED_SETX, 0x19 LED_ALLX, 0x1A LED_MAPX, 0x1B LED_ROWX,
0x1C LED_COLX with the packet lengths used in monome/mk (4, 2, 35, 7, 7). Mono commands map
to level 15 and 0. 0x17 LED_INT (global intensity g) scales the plane intensity codes.
`64int.c` looks unfinished (display refresh is commented out) and it is not in the Makefile,
so first make it a working mono mext firmware, then add varibright. Leave `64.c` (series
protocol) building unchanged. Note for docs: serialosc picks the protocol from the FTDI
serial string, so a unit flashed with the mext build may need its FTDI serial changed.

### 4a. serialosc compatibility (hard requirement)

Stock serialosc/libmonome must accept the unit as a varibright grid with no host changes.
Host sources are cloned at `/home/claude/monome/libmonome` and `/home/claude/monome/serialosc`;
`src/proto/mext.c`, `src/proto/mext.h` and `src/private/devices.h` are the reference and the
firmware must be byte-exact with them. serialosc has no varibright capability flag: a grid is
varibright when it is opened with the mext protocol and honours 0x18..0x1C.

* Protocol selection is by FTDI serial string (devices.h): `m64-%d` maps to series, plain
  `m%d` maps to mext. The unit's FTDI EEPROM serial must be rewritten to `m` + digits (for
  example m0000064) with FT_Prog or ftdi_eeprom. Firmware cannot do this. Document it.
* Handshake (mext_open): the host sends 0x00, 0x01, 0x05 and repeats them every 250 ms until
  it has all three replies: query response (0x00, subsystem, count), id (0x01 + 32 bytes),
  grid size (0x03, x, y). Answer every repeat, report led-grid and key-grid, size 8x8, and
  never overflow the output buffer.
* Level commands as libmonome encodes them: 0x18 (x, y, level), 0x19 (level), 0x1A (x off,
  y off, 32 bytes nybble-packed), 0x1B / 0x1C (x, y, 4 bytes nybble-packed, high nybble
  first). Key events 0x21 down / 0x20 up + x, y. LED and key coordinates must agree.
* Never emit unsolicited or non-standard messages (libmonome sizes messages from its own
  tables). Calibration get/set opcodes reply only when asked and use opcodes libmonome never
  sends.
* Consume every opcode libmonome can send (led ring, tilt, set id, ...) with the correct
  length so the stream never desynchronises.
* Tilt: the gs64 has an accelerometer that 64.c supports. Support the mext tilt subsystem
  if practical (reference: `/home/claude/monome/mk/firmware/tilt/mk.c`).
* Integration test: build libmonome's mext protocol code on the host with a stub platform
  layer, run `mext_open` and every `monome_led_*` / `monome_led_level_*` call against the
  simulated firmware, and check the resulting LED levels and the key events decoded by
  libmonome.

## 5. Concurrency rules for the firmware

* Only the Timer1 ISR touches E0..E2 once the main loop is running. Main loop code uses
  single-bit `PORTE |= bit` / `PORTE &= ~bit` on E3/E4 (compiles to sbi/cbi, atomic).
* The ISR must not disturb E3..E5 and must not exceed about 120 us.
* Main updates `plane[][]` without long critical sections (tearing for one frame is benign).
* Stop the frame timer during USB sleep and shutdown, restore on wake.
* Keypad scanning and its 100 us settle delays must keep working with the ISR running.

## 6. Simulation contract (shared by both workstreams)

simavr (installed, `/usr/include/simavr`, `libsimavr`) has no ATmega325 core. The firmware
therefore has two build targets from the same source:

* `make` : real target, `-mmcu=atmega325`, produces `64vb.hex` (must fit 32 KB flash, 2 KB RAM).
* `make sim` : `-mmcu=atmega1281 -DSIM`, produces `64vb-sim.elf`. Same ports, pins, 16 MHz
  clock, Timer0/Timer1/EEPROM/ADC usage. A small `#ifdef SIM` shim covers register and vector
  name differences only (for example TIMER0_COMP_vect vs TIMER0_COMPA_vect). No logic
  differences.

Harness side (`sim/`): loads `64vb-sim.elf` in libsimavr, and
* decodes the MAX7219 serial stream from PORTE bits 0..2 into `(cycle, addr, data)` writes;
* emulates the FT245: drives C1 RXF low when host bytes are queued, presents a byte on
  PORTD when C3 RD goes low, captures bytes on the C2 WR falling edge, keeps C4 PWREN low;
* emulates the keypad: PORTB 4..6 selects a row, E4 LD latches, E3 CLK shifts, E5 returns
  data (active low);
* preloads EEPROM with a calibration value when a test needs it;
* feeds register writes into a MAX7219 behavioural model with parameters f_s, scan phase,
  inter-digit blanking, and two variants for when a register write takes effect (immediately,
  or at the next digit slot);
* computes per-LED luminance over time and a flicker metric (below).

Flicker metric: low-pass each LED's luminance with a temporal filter approximating flicker
fusion (for example a cascade giving about -3 dB near 20 Hz and steep roll-off above 60 Hz,
or weighting by a temporal contrast sensitivity curve), then report
(a) peak-to-peak and RMS modulation relative to the LED's mean after settling,
(b) per-row mean brightness error versus the commanded level (banding),
(c) monotonicity and linearity of the 16-level ramp.
Pass thresholds to start from: filtered modulation under 1 % RMS and 3 % peak-to-peak,
banding under 3 % of full scale. Adjust with justification if the literature suggests
different values.

## 7. Workstreams

A. Model and harness (dir `sim/`): build the MAX7219 model, metric and simavr harness. Before
   any firmware exists, drive the model with a synthetic write generator to (1) show that
   naive time-domain BCM flickers under the metric, (2) verify FLIP, (3) map the tolerance to
   rate mismatch over ratio 0.6..1.6 and f_s 500..1300 Hz, (4) compare write orders, burst
   lengths 50..350 us and plane tables (for example 15/7/3/1 vs a 5-plane brighter table),
   (5) recommend defaults. Deliver `sim/README.md` with results and a `make test` entry.
B. Firmware (dir `gs64rec10-vb/`): implement sections 2..6 firmware side. Must compile clean
   for both targets with avr-gcc 7.3.
C. Integration (after A and B): run the real firmware ELF in the harness, test every mext LED
   command, levels, intensity scaling, keypad events under ISR load, ISR duration, calibration
   mode and EEPROM persistence, legacy fallback, and the flicker metric across the calibrated
   and miscalibrated range. Fix what fails. Write `REPORT.md`.

## 8. Revision 2 (after Workstream A results, commit 6a62777)

Workstream A refuted section 2 point 4. The MAX7219 intensity pulse sits inside the digit
slot, so a frame boundary that lands inside a slot does not blend two planes linearly when
the intensity code changes with the plane. Plain FLIP gives 23..100 % FS errors on the
affected row, and the row moves with any rate mismatch. See `sim/README.md`.

Two candidate schemes replace it:

**Mode T (temporal, constant intensity).** Intensity stays at the global code (default 15,
duty 31/32, pulse nearly fills the slot). Each frame tick rewrites only the 8 digit registers.
A level k of P is shown as k "on" frames spread evenly over a P-frame cycle (first-order
delta-sigma / Bresenham order, per-LED phase offsets optional). No shutdown, no intensity
writes. With a near-full pulse a straddled slot blends consecutive frames linearly, which is
the property the original argument needed. Levels available: P + 1. Choose P from the
calibrated scan rate so the cycle fundamental f_s / P stays above the flicker limit
(about 80 Hz): P = 6 at 500 Hz, 10 at 800 Hz, 15 at 1200 Hz and above. Peak brightness
equals stock. Host levels 0..15 map to the nearest of the P + 1 steps (0 stays 0, any
nonzero level shows at least step 1). To be evaluated before it is trusted: tolerance to rate
mismatch under both write-effect models, ISR jitter, lower global intensity codes (shorter
pulse), and level count versus f_s.

**Mode SD (FLIP-SD, 16 levels).** As recommended by Workstream A: shutdown bracket around
each burst, cycle-exact tick, plane tables 15/15/6/15/11/15 and 15/15/7/15/3. Passes only
within about +-0.1 % rate match unless the chip restarts its scan on wake, which is
undocumented. Opt-in until a hardware probe says which wake behaviour the chip has.

Default mode is the more robust of the two according to simulation. Probe modes from
Workstream A recommendation 6 are included so a hardware owner can settle the open
questions. Calibration follows Workstream A recommendation 4.

### 8a. Mode T sweep results (planner's runs: `sim/modet.py`, `modet_sweep.py`, `modet_sd.py`)

Tables: `sim/results/modet.md` (no shutdown bracket) and `sim/results/modet_sd.md` (with it).

* Mode T without a shutdown bracket depends on the write-effect model. With immediate writes
  P = 3 stays under 3 % p-p within about +-1 % rate mismatch. With next-slot writes any
  mismatch gives 17..44 % p-p. Not acceptable as a default.
* Mode T with the shutdown bracket ("T-SD") is identical under both write models. Wake model
  "frozen": P = 3 passes within +-1.0 % at 500 Hz, +-3.75 % at 800 Hz, +-4 % at 1300 Hz;
  P = 4 within +-0.75 / +-1.0 / +-2.75 %; P = 5 within +-0.5 / +-0.75 / +-2.25 %. Wake model
  "restart at 0": flicker under 0.2 % p-p at every ratio tested for P <= 5, with a static
  band limit of -0.75..+0.25 %. Wake models "same digit" and "next digit" fail (4..27 % p-p).
  Brightness 93..97 % of stock.
* Consequence: default = T-SD with P = 3 (4 levels) or P = 4 (5 levels), chosen from the
  calibrated rate. Mode SD (16 levels) stays opt-in and becomes the recommendation only if a
  hardware probe shows the chip restarts its scan at digit 0 on wake. Every scheme depends on
  the undocumented wake behaviour, so the probe modes are essential.
