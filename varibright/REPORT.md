# gs64rec10 varibright: report

**Everything here is simulation.** There was no hardware. The MAX7219 is a behavioural model
written from the datasheet plus stated assumptions (`sim/README.md`). The firmware ran in simavr
on an atmega1281 core with a register-name shim. No number below is a hardware measurement.

## 1. What was planned

PLAN.md sections 2..7 planned "FLIP": frame-locked bit planes, where the intensity register is
changed per frame and the chip's own PWM weights the planes. That scheme was meant to give 16
levels with a predicted rate tolerance of +-2..3 %. Calibration would be a rolling band nulled
by eye, and the protocol would be mext, so that stock serialosc/libmonome see a varibright grid.

## 2. What simulation refuted

1. **Plain FLIP** (workstream A): the chip shows mixed intensity and row states during
   the register burst. That gives 23..100 % FS errors at the exact rate and 14..65 % FS rolling
   flicker at any mismatch, whatever the write order or burst length.
2. **FLIP-SD** (shutdown bracket, 16 levels) works, but only within about +-0.1..0.3 %
   rate mismatch under a "frozen" wake. That is 10..20 times tighter than predicted.
3. **Mode T without a bracket** (this workstream, PLAN 8): it passes with immediate register
   writes, at +-1 % with 0.8..2.8 % p-p. Under next-slot writes any mismatch gives a whole-frame
   drop or repeat per digit, 17..60 % p-p (`sim/README.md` 10.1). It was dropped.
4. The planner's T-SD window figures were non-contiguous spans (for example "+-3.75 %" at
   800 Hz). The contiguous windows are smaller, shown below. The planner's `modet.run(code=...)`
   also never set the chip intensity.
5. A further model case was found: if the chip keeps the pre-halt latched value through a frozen
   wake, **every** temporal scheme fails at any mismatch. The exact rate still passes.

## 3. Mode T / T-SD evaluation (synthetic writes, same metric and thresholds)

Contiguous PLAN-threshold windows, % rate mismatch, worst of 2 phases:

| scheme | 500 Hz | 650 | 800 | 1000 | 1300 |
|---|---|---|---|---|---|
| T-SD P=3 (4 levels), frozen wake, immediate or re-latch | +-1.10 | -1.4..+1.2 | +-1.40 | +-2.10 | +-2.20 |
| T-SD P=4 (5 levels), same | +-0.80 | +-0.90 | -1.4..+1.5 | +-1.50 | +-1.50 |
| T-SD P=5 / P=6 | +-0.5 / -0.25..+0.2 | +-0.65 / +-0.5 | +-0.9 / +-0.8 | +-1.15 / +-0.9 | +-1.2 / +-1.0 |
| T-SD any P <= 6, restart-at-0 wake | -0.7..+0.35 | -0.7..+0.4 | -0.7..+0.35 | -0.7..+0.4 | -0.7..+0.35 |
| T-SD, frozen with latch held | exact only | | | | exact only |
| Mode SD (workstream A) 15/7/3/1, frozen | +-0.08 | -0.13..+0.10 | -0.13..+0.14 | +-0.16 | -0.17..+0.15 |
| Mode SD 15/15/6/15/11/15 | -0.12..+0.10 | +-0.28..0.30 | +-0.30 | | +-0.30 |
| Mode SD, frozen with latch held | exact only (60 % pp at 0.01 %) | | | | |

Other results, all at 800 Hz unless stated:

* Exact rate: every level below 0.2 % pp for P <= 5.
* ISR jitter: 0..1 us gives 0.73 % pp, 2 us 1.45 %, 5 us 3.6 % (FAIL). The cycle-exact tick is
  therefore mandatory for T-SD, as for SD.
* Wake delay of 0..250 us costs only brightness (calibrated out). Wake jitter of +-2 us passes,
  +-10 us fails.
* Burst length matters for brightness only: dark 687 cycles per tick gives 94.7..97.9 %.
* Lower intensity codes narrow the window: code 15 and 11 keep +-1 %, code 7 gives about
  +-0.5 % (P=4), codes 3..0 fail at +-1 %.
* Per-row or per-LED pattern phase offsets give no benefit, and the unshifted pattern has the
  lowest large-area flicker.
* Largest P passing at the exact rate: 6 / 10 / 15 at 500 / 800 / 1300 Hz. Their windows are
  useless.
* Same-digit and next-digit wake models fail for all schemes.
* Most robust: T-SD with P = 3..4. Tables: `sim/results/modet*.md`.

## 4. What the final firmware does (`gs64rec10-vb/64vb.c`, revision 3)

* **Default T-SD:** one shutdown-bracketed 11-word burst per tick at constant intensity. It
  starts at a fixed TCNT1 count and is constant-time (687 cycles dark). P = 4 for
  f_s >= 750 Hz, otherwise 3, which gives every simulated window +-1.1 % or wider. That means
  **5 steps (0/25/50/75/100 %) at typical 800 Hz, 4 steps (0/33/67/100 %) below 750 Hz**.
  Brightness is 96.7 % of stock at 800 Hz (97.9 % at 500 Hz, 94.7 % at 1300 Hz). Host levels
  map round(L·P/15), with 0 off and 1 at least the dimmest step.
* **Opt-in Mode SD:** 16 levels, with A's tables (6-frame for f_s >= 600 Hz, else 5-frame),
  the same burst and the same calibration. Brightness is 83 % at 800 Hz and 72.6 % at 500 Hz.
* **Mono fallback** when uncalibrated (levels > 7 on, full brightness). The old 0xB5 record is
  rejected.
* **Calibration UI** (hold key (0,0)): a single-bracket rolling band, steps of +-1/10/100
  ticks, mode and P selection, preview, save, erase. EEPROM record v2:
  `B6 cfg lo hi chk` at 0x10.
* **Probes 1..4:** P1 at intensity 0 first, with a reference second. P4 is a new write-effect
  and latch probe. They are reachable from the keypad and with 0x0B. Reading guide:
  README-varibright.md section 5.
* **Extension commands:** `0A` (9-byte report) and `0B A5 hi lo flags cfg`. The key byte guards
  against stray bytes.
* **Kept from workstream B:** handshake, opcode lengths, tilt, sleep/wake, SIM shim and
  concurrency rules.
* **Size:** flash 9828 B (30 %), RAM 661 B. Both builds compile without warnings.
* **ISR worst case (simavr, with host traffic and key scan):** frames, band and probe 4 take
  987 + 7 cycles = 62.1 us. Probes 1..3 take 18.9 us. The budget is 120 us. Tick spacing was
  exact to the cycle in every run.

## 5. Tests (`cd sim && make test` quick, `make fwtest` full; results in `sim/results/`)

| test | result |
|---|---|
| model, harness, API self-tests (workstream A) | PASS |
| 3a libmonome e2e T-SD 800 Hz: real libmonome.c + mext.c + rotation.c, mext_open handshake in 1 round, all monome_led_* and level_* calls (set/all/map/row/col/intensity 7, 3, 15), rotations 0/90/180/270, 64 keys down+up, rotation of keys, tilt enable/disable | PASS 54/54 |
| 3a same, Mode SD 800 Hz / T-SD 500 Hz (P=3) / SD 1300 Hz | PASS 54/54 each |
| 3a same, mono (uncalibrated) | PASS 40/40 |
| 3b garbage stream, resync, EEPROM untouched; every libmonome opcode with random payload; 67 repeated handshakes; output blocked 300 ms with TXE (all replies whole, key order kept, map applied) | PASS 11/11 |
| 3c flicker on firmware traces, 16 host levels, f_s 500/800/1300, host traffic + key scanning, T-SD: frozen imm/next-slot +-1 %, restart-at-0 -0.5..+0.25 %, latched-hold exact | PASS (worst 2.91 % pp at 500 Hz -1 %) |
| 3c same, SD: frozen +-0.1 %, restart-at-0 -0.5..+0.2 %, latch-hold exact | PASS (worst 2.69 % pp at 500 Hz -0.1 %) |
| 3c latch-hold model at a mismatch (T-SD +0.1 %, SD +0.05 %) | EXPECTED-FAIL, as predicted: 23..38 % / 37..77 % pp |
| 3d calibration keypad UI, adjust, mode, preview, probe, save; EEPROM persistence across reset; mono fallback; 0x0B mode switching / forced P / report; probes 1..4 timing; sleep/wake | PASS 23/23 |
| 3e ISR duration per mode, cycle-exact tick under load | PASS 20/20 |
| total `fw_tests.md` | 135 checks, 0 unexpected |

serialosc check (source): the detector accepts any usb-serial tty. libmonome chooses mext
from the FTDI serial `m%d` and runs the 0x00/0x01/0x05 handshake. serialosc then sets
rotation and `led_all(0)`. Nothing beyond the FTDI serial string and the handshake is
needed.

## 6. Defects found and fixed

Firmware:

1. The burst length depended on the frame data. The compiler branched on the last data bit,
   and the digit address was a loop variable. That moved the wake edge by up to 21 cycles and
   gave 36..60 % pp under the latch-hold model at the exact rate. Fixed with an asm shifter and
   unrolled constant addresses.
2. The calibration band burst compiled differently from the frame burst (687 against 673
   dark cycles). Fixed with one shared code path.
3. Probe segments carried 24..35 cycles of entry jitter. Fixed: they are now aligned too.
4. A key press and release while output was blocked delivered only the "up". Fixed with an
   ordered event queue.
5. Queued handshakes overflowed the ring and id replies were dropped. Fixed: host bytes are
   held in the FT245 FIFO, and the partial-packet timeout counts only real silence.
6. VB_ALIGN_T0 = 120 was below the worst-case entry estimate of about 128 cycles. It is now
   160.
7. 0x0B was unguarded against stray bytes. It now needs the key byte 0xA5.

Harness and tests:

1. FT245 RD was masked by DDRC, which created a phantom 0x00 before the first host byte.
2. The libmonome stub needed FTDI USB-packet delivery. Without it, libmonome reads a header
   before its payload has arrived.
3. Several of my own test expectation bugs, all corrected against the specification, with no
   thresholds loosened.

## 7. What remains unverified without hardware, and what to check first

1. **Run probe 1 (intensity 0), then 4, then 2 and 3** (README-varibright.md section 5). They
   decide which wake model the chip follows:
   * restart-at-0: SD becomes preferable, with no rate sensitivity;
   * frozen: T-SD as shipped;
   * latch held: only exact calibration works, otherwise mono;
   * same or next digit: use mono.
2. **Rate drift:** after calibrating warm, watch the T-SD preview while the unit warms or the
   USB supply changes. The simulated window is +-1.1..2 %, and the real drift of the RC
   oscillator is unknown.
3. **Wake time and its repeatability:** leaving shutdown is "typically < 250 us" per the
   datasheet. Its jitter must stay under about +-2 us.
4. Whether flicker or the f_s/P phantom array (200 Hz) is visible to people. The metric is
   only a perception model.
5. MAX7219 clones, PWM window position, LED current settling after shutdown, and ghosting.
6. **Electrical:** the 1-cycle CLK edges (use VB_SHIFT_NOPS=1 if rows are corrupt), TXE
   wiring, tilt axis orientation, and FTDI serial rewrite and serialosc detection on a real
   host.
7. **Flashing:** this needs ISP or JTAG (there is no bootloader). mk-boot.c is untested here.
