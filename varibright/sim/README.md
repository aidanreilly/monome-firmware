# sim/: MAX7219 varibright simulation and simavr harness (workstream A)

All of this is simulation. No hardware was available, so every number below comes from a
behavioural model of the MAX7219 that I wrote from the datasheet plus stated assumptions.
The numbers are only as good as those assumptions. Section 9 lists what hardware has to
confirm.

## 1. Headline findings

1. **FLIP as written in PLAN.md section 2 fails in this model, whichever write-effect
   variant is assumed.** The killer is the mixed state during the register burst, not the
   rate mismatch. Suppose the digit being scanned shows the *new* intensity code together
   with its *old* row, for example the level-1 frame (code 1) rows shown at code 15. That
   digit then gets several times its intended light. At the exactly calibrated rate this
   is a static error of 23..58 % of full scale (immediate model) or up to 103 %
   (latched model), and the size depends on the scan phase, which is random at power-up.
   With any mismatch at all (0.02 %) the error rolls through the rows as flicker of
   14..65 % of full scale. No write order (intensity first, last, middle,
   "dark-mixing", AND-bridge, skipping unchanged rows) and no burst length in 5..350 us
   fixes this. A 5 us burst would need 0.6 us per word, while the real shifter takes 5 us
   per word, and even that still gives 2.3..9.7 % FS (immediate) or 42..102 % FS
   (latched) at a 0.05 % mismatch.
2. **What works in the model: FLIP with a shutdown-bracketed burst ("FLIP-SD").** Each tick
   writes `0x0C=0, 0x0A=code, digits 1..8, 0x0C=1` (11 words). The datasheet says the scan
   oscillator is halted in shutdown, so the chip never displays a mixed state. At the
   calibrated rate this gives 0.13..0.19 % pp (relative to each LED's own mean) for every
   level, phase, f_s and write-effect model. The cost is the dark time: 4 % of brightness at
   800 Hz and 7 % at 1300 Hz with a 50 us burst. That rises to 20 % if leaving shutdown
   really takes the datasheet's "typically < 250 us".
3. **The rate tolerance is about 10..20 times tighter than PLAN.md predicted.** If the chip
   resumes its scan where it stopped (the "frozen" model), the window that passes the PLAN
   thresholds is -0.08..+0.08 % at 500 Hz, -0.13..+0.14 % at 800 Hz and -0.17..+0.15 % at
   1300 Hz (15/7/3/1). PLAN.md predicted 2..3 %. There are no isolated bad ratios: nothing
   passes anywhere in 0.6..1.6 outside the window (0 of 99 points beyond +-5 %), so the
   predicted 4n/(4n +- 1) zones do not stand out from their neighbours. If the chip
   instead restarts at digit 0 when it leaves shutdown, it re-synchronises every tick.
   There is then no flicker at any ratio, only a static band on the first or last row,
   with a window of -1.00..+0.22 %.
4. **Brightness: use a non-binary table, not 15/7/3/1.** `15/15/15/15/11/6` (6 frames,
   shown in the order 15,15,6,15,11,15) reaches 86 % of stock (82 % simulated with the
   shutdown dark time at 800 Hz), against 45 % for 15/7/3/1. Its ramp error is 1.5 % FS,
   it passes the PLAN thresholds at all f_s, and its tolerance window is as wide as or
   wider than the 4-plane table's. `15/15/15/7/3` (72 % simulated, ramp error 0.9 %)
   passes the strict thresholds everywhere. The recommendation is the 6-frame table, with
   a fall back to the 5-frame one when the calibrated f_s is below 600 Hz.
5. **ISR timing jitter is as important as the rate.** With FLIP-SD (frozen model), random
   ISR entry latency of 0..2 us already gives 1.8 % FS of flicker, and 0..5 us gives
   4.4 % FS. The tick must be cycle-stable. The firmware build I ran in the harness has
   +-3 cycles of jitter, which is fine.

## 2. How to run

```
make            # model library, gs64sim harness (+ libgs64sim.a, api_test), test firmware
make test       # model unit tests, harness tests (CLI + C API), quick versions of all
                # experiments into results/quick/  (about 70 s on 2 cores)
make sweep      # full experiments into results/*.md + .json (about 7 min on 2 cores)
python3 experiments.py [--quick] [--jobs N] [--out DIR] naive exact sweep burst tables calib probe intensity
python3 trace_eval.py TRACE --fs 800 --phase 0.3 [--effect lat] [--t0 S --t1 S]
```
You need Python 3 with numpy and scipy, gcc, libsimavr (1.6) and avr-gcc.

Files:

| file | content |
|---|---|
| `max7219.c`, `maxmodel.py` | behavioural model (C, exact piecewise integration) and its ctypes wrapper, trace reader |
| `flicker.py` | perceptual flicker metric and thresholds |
| `schemes.py` | plane tables, optimal 16-level lookup (exact minimax DP), frame ordering |
| `gen.py` | synthetic write generators: naive BCM/PWM, FLIP with all write orders, shutdown bracket, jitter, calibration pattern |
| `evalflip.py` | generate, simulate, score |
| `experiments.py` | experiments (a)..(h); `results/*.md` are the tables quoted below |
| `trace_eval.py` | run a harness trace through model and metric |
| `harness/` | simavr harness: `gs64sim.[ch]` library, `main.c` CLI, `api_test.c` |
| `testfw/testfw.c` | harness self-test firmware (atmega1281) |
| `tests/` | `test_model.py`, `test_harness.py`, `harness_test.script` |

## 3. MAX7219 model and assumptions

Input: time-stamped 16-bit words (time = LOAD rising edge; the datasheet says the data is
latched on that edge). Output: the fraction of time each LED is lit, integrated exactly
into 50 us bins (the integration is exact, so means are exact; the bins only limit
bandwidth to 10 kHz).

* **Scan:** digit slots of length 1/(8 f_s), digits 0..scan-limit in order. The slot length
  does not depend on the scan limit (the datasheet gives the scan rate as 8 f_OSC / N).
  Parameters: `fs`, `phase` (frame fraction already elapsed at t = 0), optional per-slot
  oscillator jitter `osc_jitter` and linear drift `drift`.
* **Intensity PWM inside the slot:** on-time = (2n+1)/32 of the slot. The minimum 1/32 off
  time is the datasheet's "minimum interdigit blanking of 1/32 of a cycle". `pwm_pos`
  places the window inside the slot (0 = starting at the slot start, which is the
  default and my assumption; 1 = ending at the slot end). `blank` adds extra blanking.
  A mid-slot intensity change acts like a comparator: light is on wherever the time lies
  inside the window of the code that is current at that instant.
* **Write effect** (`digit_effect`, `int_effect`): 0 = a write changes the output
  immediately, even mid-slot; 1 = the register is sampled at each slot start. The
  datasheet's dual-port digit SRAM and its 2.25 ms data-to-segment delay fit either.
* **Shutdown** (0x0C bit 0 = 0): display dark and oscillator halted. On wake
  (`restart_mode`): 0 restart at digit 0, 1 frozen (resume mid-slot), 2 same digit with
  the slot restarted, 3 next digit. Optionally a dark `wake_delay` with `wake_jitter`.
  The datasheet only says "the scan oscillator is halted" and "typically it takes less
  than 250 us to leave shutdown mode".
* **Display test** (0x0F) lights all 64 LEDs at 31/32 duty, overriding shutdown. **Decode
  mode** (0x09) uses the Code-B font. **Scan limit** (0x0B) takes effect at the next slot.
* The state at power-up is shutdown with all registers 0 (`POWERUP_REGS`); the synthetic
  runs start from a running chip (`RUNNING_REGS`).
* Not modelled: segment current settling, LED rise and fall times (sub-microsecond, they
  do not matter at these time scales), ghosting, the analogue PWM edge shape,
  temperature.

## 4. Flicker metric

Each LED's luminance passes through a 6th-order Butterworth low-pass at 32 Hz. Its gain
is 0.99 @ 20 Hz, 0.83 @ 30, 0.25 @ 40, 0.069 @ 50, 0.023 @ 60, 0.009 @ 70 and
0.004 @ 80 Hz. After 0.25 s of settling:
(a) pp and rms of the filtered signal, relative to the LED's own mean (worst LED);
(b) banding, meaning each LED's mean error against its commanded level in % of full
scale, after removing a global brightness factor. That factor is reported separately as
`gain`, so a uniform dimming such as shutdown dark time is not counted as banding;
(c) ramp monotonicity and linearity, both from the exact lookup weights and from the
simulated means.

Thresholds and their justification:

* The temporal contrast sensitivity of large, bright fields peaks at 10..20 Hz, where the
  threshold is about 0.3..0.5 % Michelson. It falls steeply above 30 Hz and reaches
  100 % modulation (the critical flicker frequency) at roughly 60..80 Hz
  ([de Lange 1958; Kelly 1961, JOSA 51:422](https://www.doi.org/10.1364/JOSA.51.000422)).
  The filter is placed on that flank and is somewhat more sensitive than the curve.
* **PLAN thresholds** (pass): rms < 1 %, pp < 3 %, band < 3 % FS. Together with the
  filter they imply a CFF of 64 Hz for 100 % sinusoidal modulation.
  **Strict thresholds** (margin): rms < 0.35 %, pp < 1 %, which is the peak-sensitivity
  threshold (0.5 % Michelson). They imply a CFF of 77 Hz.
* The metric is relative to each LED's own mean. That is conservative for dim levels,
  because sensitivity falls at low luminance (Ferry-Porter) and for small fields.
* Not covered: stroboscopic and phantom-array effects during eye movements, which stay
  visible far above the CFF
  ([IEEE 1789-2015 summary](https://www.energy.gov/eere/ssl/articles/flicker-understanding-new-ieee-recommended-practice)).
  The stock display is already modulated 100 % at f_s (1/8 duty). FLIP adds components
  at f_s/P, which is 133 Hz for 6 frames at 800 Hz and 83 Hz at 500 Hz. Dim levels that
  are lit in one frame only pulse at that rate, which could make the phantom array more
  visible than on the stock firmware. This cannot be judged in simulation.

## 5. Results (from `make sweep`; full tables in `results/*.md`)

Unless stated otherwise: table 15/7/3/1, 50 us burst for 9 words (5.5 us per word, close
to the 5.0 us per word measured from the firmware build, section 7), test patterns that
put every level 0..15 in every row, and the worst LED. "pp % FS" is the filtered
peak-to-peak in % of full scale.

### (a) Naive time-domain BCM / PWM (intensity fixed at 15): fails

Every naive case fails (`results/naive.md`). Two failure modes appear. When the PWM period
and the scan period are commensurate, the result is static aliasing, for example BCM
tau 100 us at 500 Hz: pp 0.0 %, band 31.2 % FS. Otherwise the beat shows as flicker, for
example BCM tau 100 us at 1300 Hz: pp 237 % (81.8 % FS), and BCM tau 1 ms at 1300 Hz:
pp 82 %. The stock static display passes with 0.0 / 0.0 / 0.0.

### (b) Exactly calibrated rate (T_u = T_cal), 12 phases, all 16 levels in every row

| variant | model | f_s 500 / 800 / 1300: band % FS | worst level error % | PLAN |
|---|---|---|---|---|
| FLIP int_first (as PLAN.md) | immediate | 22.7 / 36.4 / 57.6 | up to 480 | FAIL |
| FLIP int_first | latched | 101.8 / 102.8 / 102.4 | up to 857 | FAIL |
| FLIP int_mid | immediate | 11.4 / 18.2 / 28.6 | up to 239 | FAIL |
| FLIP int_last | latched | 86.0 / 86.0 / 86.0 | 105 | FAIL |
| **FLIP-SD frozen** | both | 0.4 / 0.2 / 0.2 (pp 0.18 / 0.13 / 0.18 %) | 0.7 | pass (strict too) |
| FLIP-SD restart-at-0 | both | 0.4 / 0.2 / 0.2 (pp 0.19 / 0.13 / 0.18 %) | 0.7 | pass (strict too) |

With plain FLIP the filtered pp at the exact rate is small (0.01..0.21 %), but the means
are wrong. How wrong depends on where the burst falls inside a digit slot, so it varies
from unit to unit and from power-up to power-up. The global brightness factor for
FLIP-SD is 97.2 / 95.8 / 93.2 %.

### (c) Rate-ratio sweep (288 ratios, 0.60..1.60; 0.1 % steps within +-5 %, 0.01 % steps within +-0.5 %)

| variant | f_s 500 | 650 | 800 | 1000 | 1300 |
|---|---|---|---|---|---|
| FLIP int_first, immediate | none | none | none | none | none |
| FLIP int_first, latched | only exactly 1.0 (at this phase) | same | same | same | same |
| FLIP-SD frozen, PLAN window % | -0.08..+0.08 | -0.13..+0.10 | -0.13..+0.14 | -0.15..+0.16 | -0.17..+0.15 |
| FLIP-SD frozen, strict window % | -0.03..+0.03 | -0.03..+0.04 | -0.05..+0.06 | -0.05..+0.06 | -0.07..+0.06 |
| FLIP-SD restart-at-0, PLAN window % | -1.00..+0.22 | -1.00..+0.22 | -1.00..+0.22 | -1.00..+0.22 | -1.00..+0.22 |

Detail at 800 Hz for FLIP-SD frozen, as pp % of own mean / pp % FS: 0.9 / 0.1 at -0.05 %,
2.4 / 0.2 at +-0.1 %, 2.4 / 0.3 at +0.2 %, 11.8 / 0.9 at +0.5 %, 12.6 / 2.3 at +1 %.
Plain FLIP int_first (immediate) gives 72..231 % of own mean (14.0..19.3 % FS) at every
mismatch from 0.02 % to 1 %.

PLAN.md predicted bad ratios, FLIP-SD frozen at 800 Hz, pp % FS at the ratio against the
median of its neighbours: 0.8000 30.0 (12.5), 0.8889 35.8 (33.3), 0.9231 21.4 (19.6),
0.9412 17.4 (17.8), 1.0667 19.7 (13.1), 1.0909 21.6 (24.4), 1.1429 23.6 (25.4),
1.3333 24.6 (21.8). **Refuted as distinct zones:** the whole range outside about +-0.15 %
fails at 10..36 % FS, and the predicted ratios are no worse than their neighbours.

The FLIP-SD same-digit and next-digit wake models are self-synchronising as well. They pass
from -1.00 % to -0.01 % but flicker exactly at 1.0, where the halt lands on a slot boundary.

### (d) Burst length, write order, effect model, jitter, wake behaviour (800 Hz)

pp % FS / band % FS, at ratio 1.0 (worst of 8 phases) and at a +0.05 % mismatch.
`results/burst.md` also has 5 us and 20 us bursts and the -0.05 % side. At 5 us and
+0.05 %, plain FLIP still reaches 2.3 (int_mid) .. 9.7 (bridge) % FS immediate and
49..102 % FS latched.

| strategy | effect | 50 us | 100 us | 200 us | 350 us |
|---|---|---|---|---|---|
| FLIP int_first (+-skip identical) | imm | 0.0/36.4, 36.8/3.8 | 0.0/69.6, 71.8/7.7 | 0.0/102.8, 107.2/15.2 | 0.0/102.2, 103.1/25.6 |
| FLIP int_mid | imm | 0.0/18.2, 18.9/1.5 | 0.0/34.6, 36.6/3.0 | 0.0/59.4, 71.2/6.0 | 0.0/96.1, 106.1/11.1 |
| FLIP dark-mixing order | imm | 0.0/33.9, 37.6/1.0 | 0.0/45.4, 49.8/2.1 | 0.0/46.9, 59.7/4.1 | 0.0/49.1, 63.8/7.6 |
| FLIP AND-bridge + skip | imm | 0.0/28.0, 32.8/2.3 | 0.0/36.5, 49.1/4.6 | 0.0/48.3, 61.3/8.7 | 0.0/53.7, 60.2/13.3 |
| FLIP int_mid | lat | 0.0/86.0, 144.9/1.5 | 0.0/0.0, 143.6/3.1 | 0.0/102.8, 141.1/6.0 | 0.0/102.8, 136.2/15.6 |
| **FLIP-SD frozen** (+-skip identical) | both | 0.0/0.2, 0.2/0.0 | 0.1/0.2, 0.3/0.0 | 0.1/0.4, 0.4/0.1 | 0.1/0.4, 0.6/0.1 |
| FLIP-SD restart-at-0 | both | 0.0/0.2, 0.0/1.4 | 0.1/0.2, 0.1/1.5 | 0.1/0.4, 0.1/1.6 | 0.1/0.4, 0.1/1.8 |

* Skipping unchanged rows made no measurable difference with the dense test patterns.
  With FLIP-SD the burst length costs brightness but nothing else.
* ISR entry jitter of 0..j us ("late"), pp % FS for FLIP-SD frozen: 1 us 0.9, 2 us 1.8,
  5 us 4.4, 20 us 8.6, 100 us 39.2. A symmetric +-j is twice as bad: +-2 us gives 3.5.
  Restart-at-0 also bands: 5 us gives 4.1 / 1.8, 20 us gives 16.0 / 7.4. Plain FLIP under
  the latched model tolerates up to 50 us of jitter but fails anyway (see (b)).
* Wake delay and wake jitter (FLIP-SD): a fixed delay only costs brightness (gain 96 % at
  0 us, 92 % at 50 us, 80 % at 250 us). A wake time that is not repeatable is as bad as
  ISR jitter: +-2 us gives 1.2..2.9 % FS, +-10 us gives 12..16 % FS (frozen); restart-at-0
  gives 2.7..5.6 and 13..21 % FS.

### (e) Plane tables

Static properties (exact). Peak is level 15 against the stock display at intensity 15
(PLAN.md normalises by /32; that value is in brackets). The lookups come from an exact
minimax DP towards a linear ramp; masks have frame 0 first.

| table (frame order) | peak % stock | lin err % FS | step max/min | lookup masks L1..L15 |
|---|---|---|---|---|
| 15/7/3/1 (PLAN default) | 45.2 (43.8) | 2.14 | 2.00 | binary |
| 15/15/7/3/1 (PLAN) | 56.1 (54.4) | 2.30 | 3.00 | 00010 00011 00101 00110 10000 10001 10011 10100 10110 10111 11001 11010 11100 11101 11111 |
| 15/15/15/7/3/1 (PLAN) | 63.4 (61.5) | 1.19 | 1.67 | see results/tables.md |
| **15/15/7/15/3** (new, spread order) | 74.2 (71.9) | 0.87 | 1.29 | 00001 00100 00101 10000 10001 10100 10101 10010 10011 10110 10111 11010 11011 11110 11111 |
| **15/15/6/15/11/15** (new, spread order) | 86.0 (83.3) | 1.46 | 1.62 | 001000 000010 100000 101000 100010 100100 101100 100110 101110 111100 110110 111110 111101 110111 111111 |

To find the new tables I searched every code multiset of 4..7 frames for the brightest
one whose best lookup stays within 2.5 % FS of linear (`schemes.search_tables`). More
frames buy brightness, but each one lowers the cycle rate f_s/P.

Simulated with FLIP-SD frozen. Cells are pp % of own mean / pp % FS: at the exact rate
(worst of 6 phases), then at a mismatch of +-0.1 %, then the measured level-15 brightness
in % of stock:

| table | 500 Hz | 800 Hz | 1300 Hz | +-0.1 % @500 / 800 / 1300 | peak % stock @500 / 800 / 1300 |
|---|---|---|---|---|---|
| 15/7/3/1 | 0.18 / 0.10 | 0.13 / 0.02 | 0.18 / 0.06 | 3.7 / 2.5 / 1.5 | 43.9 / 43.3 / 42.1 |
| 15/15/7/3/1 | 0.53 / 0.40 | 0.08 / 0.04 | 0.06 / 0.02 | 2.7 / 1.3 / 1.0 | 54.6 / 53.7 / 52.4 |
| 15/15/15/7/3/1 | 1.58 / 0.84 | 0.17 / 0.06 | 0.11 / 0.03 | 4.0 / 1.5 / 1.1 | 61.6 / 60.9 / 59.1 |
| 15/15/7/15/3 | 0.53 / 0.33 | 0.08 / 0.03 | 0.06 / 0.02 | 2.4 / 1.1 / 1.0 | 72.2 / 71.0 / 69.2 |
| 15/15/6/15/11/15 | 1.54 / 0.63 | 0.14 / 0.04 | 0.09 / 0.03 | 2.7 / 0.9 / 0.6 | 83.7 / 82.4 / 80.3 |

All tables are monotonic. The simulated ramp error matches the static one to within
0.1 % FS. Tolerance windows (PLAN thresholds, % deviation) at 500 / 650 / 800 / 1300 Hz:

| table | 500 | 650 | 800 | 1300 |
|---|---|---|---|---|
| 15/7/3/1 | -0.08..+0.08 | -0.12..+0.12 | -0.12..+0.14 | -0.16..+0.14 |
| 15/15/7/3/1 | -0.14..+0.12 | -0.16..+0.16 | -0.16..+0.24 | -0.28..+0.26 |
| 15/15/15/7/3/1 | -0.06..+0.06 | -0.12..+0.12 | -0.18..+0.18 | -0.22..+0.22 |
| 15/15/7/15/3 | -0.12..+0.14 | -0.16..+0.20 | -0.22..+0.24 | -0.28..+0.28 |
| 15/15/6/15/11/15 | -0.12..+0.10 | -0.28..+0.30 | -0.30..+0.30 (scan limit) | -0.30..+0.30 (scan limit) |

The 6-frame table fails the strict thresholds at 500 Hz at the exact rate, with 1.54 %
pp on single-frame levels pulsing at 83 Hz. Over 6 phases the same table gives 1.54 % at 500 Hz, 0.72 % at 575 Hz, 0.42 % at 650 Hz
and 0.30 % at 725 Hz, so it passes the strict thresholds from 575 Hz up. These are the
'between 500 and 800 Hz' rows of `results/tables.md`. The 5-frame table gives 0.53 % at
500 Hz, 0.24 % at 575 Hz and 0.18 % at 650 Hz. Spreading the
bright frames apart lowers the mean (over levels) steady-state harmonic content by 7 %
(4 frames) to 32 % (6 frames), according to `schemes.best_order`.
It cannot help single-frame levels, and the simulated differences are within a few
hundredths of a percent.

### (f) Calibration pattern

All rows are on for half of T_u and off for the other half. The roll frequency is
f_s x mismatch: at 800 Hz, 0.01 % gives 0.08 Hz (12.5 s per cycle), 0.1 % gives 0.8 Hz
(1.25 s) and 1 % gives 7.9 Hz. The filtered row contrast stays at 96..122 % FS up to a
2 % mismatch (roll up to 16..25 Hz). At 5 % it drops to 42 % at 800 Hz and 3..6 % at
1300 Hz, where the band dissolves into flicker; at 500 Hz it is still 120 %. So a user can see the band as soon as
the setting is within about 2 % and can null it by eye.

* **Realistic precision.** One timer tick is 0.0031 % (500 Hz) to 0.0081 % (1300 Hz) of
  T_u. A user who waits until the band moves less than one row (1/8 of a cycle) in 10 s
  has the mismatch below 1/(80 s x f_s), which is better than one tick. Hitting the
  frozen-model PLAN window (+-0.08 % at 500 Hz) only needs a roll period above 2.5 s;
  the strict window (+-0.03 %) needs about 7 s. Calibration precision is therefore not
  the limit. **Drift is:** a 0.1 % change of the MAX7219's RC oscillator, whether from
  temperature or supply, uses up the whole window.
* **The calibration must use the same shutdown bracket as the display.** The 'on' write
  is bracketed (11 words, identical to a FLIP-SD burst) and the mid-period 'off' write is
  plain (rows only), so the chip is awake for the same time per T_u in both modes.
  PLAN.md's version, an ISR at 2/T_u, would bracket twice per period. Simulated, that
  calibrates T_u 2.70 / 4.26 / 6.74 % too long at 500 / 800 / 1300 Hz, and the display
  then flickers at 6.9 / 12.7 / 8.0 % FS.
* If the chip restarts at digit 0 on wake, the band never rolls (row swing 0 at every
  mismatch), so rolling calibration is impossible in that case. Probe P1 identifies it.

### (g) Hardware probes for the wake behaviour (model predictions)

With all LEDs on, the shutdown register is toggled at a fixed pattern. Predicted row
brightness in % of a stock row:

| probe | restart at 0 | frozen | same digit | next digit |
|---|---|---|---|---|
| P1: 50 us awake / 50 us shutdown, int 15 | 413 0 0 0 0 0 0 0 | 50 x 8 | one random row 413 | 52 x 8 |
| P3: same, int 0 | 40 0 ... | 2 x 8 | one row 40 | 5 x 8 |
| P2: 400 us awake / 100 us shutdown | 250 250 145 0 ... | 80 x 8 | 99 62 alternating | 81 x 8 |

Run P3 first, at intensity 0. In the single-row cases, P1 keeps one digit driver on for
50 % of the time. The datasheet warns that scanning 3 digits or fewer overloads the
digit drivers.

### (h) Global intensity (0x17) by scaling the frame codes

code' = round(((2c+1)(g+1)/16 - 1)/2) with the lookup unchanged. For 15/15/15/7/3 this
stays monotonic for g = 2..15, with ramp error up to 4 % FS at g = 3; g = 0 and 1 are not
monotonic. For 15/7/3/1 it is monotonic only for g >= 5 (`results/intensity.md`). For low
g, re-run `design_lut` on the scaled codes, or use fewer levels.

## 6. Recommendations for the firmware (all conditional on section 9)

1. **Bracket every ISR burst with shutdown:** `0x0C=0, 0x0A=code, 0x01..0x08 rows,
   0x0C=1`. Skipping unchanged rows is allowed but gains nothing measurable. The write
   order inside the bracket does not matter. Keep the unrolled shifter: 5 us per word,
   55..60 us per tick.
2. **Default table: 15/15/6/15/11/15** (frame order as written) with lookup
   `{0x00,0x04,0x10,0x01,0x05,0x11,0x09,0x0d,0x19,0x1d,0x0f,0x1b,0x1f,0x2f,0x3b,0x3f}`
   (bit k = frame k), giving 82 % of stock at 800 Hz in simulation. When the calibrated
   T_u is above 26700 ticks (f_s < 600 Hz), switch to **15/15/7/15/3** with
   `{0x00,0x10,0x04,0x14,0x01,0x11,0x05,0x15,0x09,0x19,0x0d,0x1d,0x0b,0x1b,0x0f,0x1f}`
   (72 %). Do not use 15/7/3/1 (45 %).
3. **Tolerance to design for:** +-0.08 % at 500 Hz up to +-0.15 % at 1300 Hz (PLAN
   thresholds). The fine calibration step is one tick. A coarse step of about 0.25 % of
   T_u (50 ticks at 800 Hz) changes the roll by about 2 Hz, which is easy to see.
   Calibrate with the bracketed pattern described in (f).
4. **Make the tick cycle-stable.** In the ISR, spin until TCNT1 reaches a fixed offset
   (larger than the worst entry latency) before the first LOAD edge, so the shutdown and
   wake edges are cycle-exact. The budget is under 1 us of entry jitter, which gives
   under 1 % FS.
5. Ship a hardware probe mode (P1..P3) and a "plain FLIP" fallback flag. If the probe
   shows restart-at-0, the display needs no rate calibration for flicker. The firmware
   should then trim T_u for equal row brightness instead of nulling a roll.

## 7. simavr harness (PLAN.md section 6 contract)

`build/gs64sim [-T ms] [-s script] [-t trace] [-o out] [-e ee.bin] [-E ee.bin] [-p] fw.elf`
loads an ATmega1281 ELF at 16 MHz (`-m`, `-f` to change).

* **MAX7219:** watches PORTE writes. DIN (E2) is sampled on each E0 CLK rising edge and
  the last 16 bits are latched on the E1 LOAD rising edge. The trace has one line per
  word: `cycle addr data start_cycle nbits`. The first three columns are what
  `maxmodel.read_trace` reads. `start_cycle` is the first CLK edge of the word, and
  `nbits` should always be 16 (anything else counts as a warning).
* **FT245:** C1 RXF is low while host bytes are queued. When C3 RD falls the next byte
  goes onto PORTD, and it is popped when RD rises. A byte is captured from PORTD on the
  C2 WR falling edge (a warning if DDRD != 0xFF). C0 TXE and C4 PWREN default low and
  can be scripted.
* **Keypad:** PORTB bits 4..6 select the row. While E4 LD is low the register loads
  continuously; LD rising freezes it; each E3 CLK rising edge shifts. E5 is active low.
  Key (row, col) means row = PORTB[6:4] and col = shift index, where 0 is the bit present
  right after LD rises. In 64.c's convention the reported key is ((7-row) << 4) | (7-col).
* **EEPROM:** preload with `-e file` or the script `ee` command, read back with `-E` or
  `eedump`, or use the C API at any time.
* **ADC:** `adc CH MV` (AVCC = AREF = 5 V), for tilt.
* **Script** (`@ms verb ...`): `host HH..`, `key R C down|up`, `pwren 0|1`, `txe 0|1`,
  `adc CH MV`, `ee ADDR HH..`, `eedump ADDR N`, `mark TEXT`. Device bytes go to `-o` as
  `cycle 0xNN`.
* **Host-byte interface for libmonome:**
  (1) C API in `harness/gs64sim.h`, linked as `build/libgs64sim.a -lsimavr`. A stub
  platform layer maps `monome_platform_write` to `gs64sim_host_write`,
  `monome_platform_wait_for_input(ms)` to `gs64sim_run_until_tx(s, 1, ms*1000)` and
  `monome_platform_read` to `gs64sim_host_read`, with keys via `gs64sim_key`.
  `api_test.c` is a worked example.
  (2) `-p` creates a raw pty, prints its path and runs paced to wall-clock time, so any
  serial client can talk to it. I tested it with `00 01 05` echoed through the self-test
  firmware.
* **Proof:** `tests/test_harness.py` and `build/api_test` run `testfw/testfw.c`. They
  check echo, key down/up events, EEPROM preload and readback (including a write by the
  firmware), the decoded init sequence, ISR writes every 19998 cycles with a spread of 17
  cycles while key scanning runs, and the model fed from the trace. Everything passes.
* **Smoke run of the firmware build** in `../gs64rec10-vb` (commit e7a0f1d, VB_TABLE 4,
  calibration record 0xB5 / 20000 ticks in EEPROM at 0x10). It answers the `00 01 05`
  handshake. Its FLIP bursts are 9 words of 49.7..49.9 us (5.0 us per word), int_first,
  with the tick period at 19997..20003 cycles. Through `trace_eval.py` with three LEDs
  at levels 15/7/1, it gives a worst pp of 0.12..0.54 % at exactly 800 Hz. At 800.4 Hz
  (0.05 % off) it gives 147 % of own mean on the level-1 LED, which is 5.8 % of a stock
  LED. This agrees with (c). simavr prints "avr_timer_write_ocr-1 mode 0 UNSUPPORTED"
  once when OCR1A is written before the timer mode is set; it is harmless.

## 8. Deviations from PLAN.md

* FLIP as specified is replaced by FLIP-SD (shutdown bracket), because plain FLIP fails
  in every write-effect variant (sections 1 and 5b-5d).
* The tolerance is about +-0.1 %, not 2..3 %, and there are no isolated bad ratios.
* The calibration pattern must be bracketed exactly like the display burst (one bracket
  per T_u), not two writes per period.
* The plane tables and lookups are new. Brightness is quoted against the stock display
  (/31) as well as PLAN's /32.
* The metric removes a global brightness factor before banding and adds strict
  thresholds. The thresholds themselves are PLAN's.
* The harness trace has two extra columns. The host interface is a C API plus a script
  plus a pty.
* The repository: `/home/claude/monome/work` is not a git repository. The firmware agent
  and the repository are at `/root/monome/work`, so `sim/` is developed in
  `/home/claude/monome/work/sim` and mirrored into `/root/monome/work/sim` for the commit.

## 9. What cannot be verified without hardware

1. **What the chip does when it leaves shutdown:** frozen, restart at digit 0, same
   digit, or next digit. Also the wake delay (datasheet: typically < 250 us) and how
   repeatable it is (it must be within about +-1 us). FLIP-SD depends on all of this.
   Probes P1..P3 decide it in minutes.
2. Whether the digit and intensity registers act immediately or at the next slot, and
   where the PWM on-window sits inside the slot. Plain FLIP fails under both write-effect
   models; FLIP-SD is insensitive to them.
3. The real scan rate of the unit, and its **drift with temperature, supply voltage and
   time**. The window is about +-0.1 %. Nothing about this is known, and it is the main
   risk.
4. Oscillator jitter from slot to slot. It is modelled (`osc_jitter`) but its real value
   is unknown.
5. Whether the residual effects are visible to people: phantom arrays at f_s/P, dim-level
   flicker, the visibility of a 0.1 Hz roll. The metric is a model of perception, not a
   measurement.
6. LED and driver analogue behaviour: ghosting, current settling after shutdown, and how
   linear brightness is in duty.

---

# Workstream C additions (Mode T evaluation, firmware integration)

Everything below is again simulation of the same behavioural model. Two model changes were
made. (1) `hold_latch` (default 0, so all results above are unchanged): under the
next-slot write model, a slot that resumes after a frozen-wake shutdown either re-samples the
registers at the wake (0, as before) or keeps the values latched at its real start (1).
Neither is documented, so both are reported. (2) The harness now models the FT245 RD/WR level
as the PORT bit; masking with DDRC had produced a phantom 0x00 byte before the first host
byte (section 11).

## 10. Mode T and T-SD (PLAN.md section 8)

Scripts: `modet.py`, `modet_sweep.py`, `modet_sd.py` (planner), `modet_extra.py` (this
workstream). Tables: `results/modet.md`, `modet_sd.md`, `modet_extra_*.md`. Level step s of P
is shown as s on-frames spread evenly (first-order delta-sigma) over a P-frame cycle,
intensity constant. "T" writes only the 8 digit registers each tick; "T-SD" brackets them with
shutdown (`0x0C=0, 0x0A, digits, 0x0C=1`). Same metric and thresholds as sections 4..5.

### 10.1 Mode T without the shutdown bracket: fails under the next-slot write model

Worst filtered pp % of own mean (all 16 host levels), P = 3 / 4, from `results/modet.md`:

| f_s | exact rate | within +-1 % (immediate) | within +-1 % (next slot) |
|---|---|---|---|
| 500 | 0.02 / 0.11 | 2.80 / 4.02 | 44.1 / 59.5 |
| 800 | 0.00 / 0.01 | 1.74 / 1.96 | 27.3 / 36.4 |
| 1300 | 0.01 / 0.02 | 0.78 / 1.06 | 16.6 / 22.2 |

Immediate writes give the linear cross-fade PLAN.md hoped for. Next-slot writes drop or repeat
a whole frame for a digit each time the write instant crosses that digit's slot start, so
any mismatch gives a 17..60 % pulse once per 1/(f_s x mismatch) seconds. At the exact rate
both models pass. Larger P only lowers the cycle rate: P >= 8 fails at 500 Hz even when exact.
**Plain Mode T is not acceptable as a default, because it depends on an undocumented chip behaviour.**

### 10.2 T-SD: contiguous rate windows (`results/modet_extra_windows.md`)

Worst of 2 scan phases, grid 0.05 % within +-0.5 %, 0.1 % to +-5 %. "Frozen" covers both the
immediate model and the next-slot model with re-latch on wake (they are identical here). The
planner's `modet_sd.md` gave min..max of all passing points, which overstated the windows
(at 800 Hz, P = 3 gave "+-3.75 %" although +-1.5 % already fails); the table below is contiguous.

| P | levels | f_s 500 | 650 | 800 | 1000 | 1300 |
|---|---|---|---|---|---|---|
| 3 | 4 | +-1.10 | -1.40..+1.20 | +-1.40 | +-2.10 | +-2.20 |
| 4 | 5 | +-0.80 | +-0.90 | -1.40..+1.50 | +-1.50 | +-1.50 |
| 5 | 6 | +-0.50 | -0.60..+0.70 | +-0.90 | -1.20..+1.10 | +-1.20 |
| 6 | 7 | -0.25..+0.20 | +-0.50 | +-0.80 | +-0.90 | +-1.00 |
| any P <= 6, restart at 0 | | -0.70..+0.35 | -0.70..+0.40 | -0.70..+0.35 | -0.70..+0.40 | -0.70..+0.35 |
| any P, frozen + latch held | | exact only | exact only | exact only | exact only | exact only |

Spot check (0.1 % steps): P = 4 at 750 Hz +-1.10 %, at 700 Hz -0.90..+1.10 %; P = 3 at
700 / 750 Hz +-1.40 %. **Rule used by the firmware: P = 4 for f_s >= 750 Hz, P = 3 below**,
which keeps every window at +-1.1 % or more (simulated). Under "restart at 0" the flicker stays
below 0.2 % at every ratio; the window is set by a static band on the first or last row.
Same-digit and next-digit wake models fail (4..27 % pp, `modet_sd.md`).

Largest P that passes the PLAN thresholds at the exact rate, with no tolerance required
(`results/modet.md`, P up to 15): 6 at 500 Hz (1.27 % pp; P = 8 gives 7.2 %), 10 at 800 Hz
(1.64 %; P = 12 gives 4.9 %), and 15 at 1300 Hz (1.06 %). These P values are not usable,
because their windows with the bracket are only +-0.2..1.0 % for P = 6 and narrower above.

**Latch held across the wake** (`results/modet_extra_holdsd.md`, 800 Hz, pp % of own mean):

| scheme | -0.5 % | -0.1 % | -0.01 % | 0 | +0.01 % | +0.1 % | +0.5 % |
|---|---|---|---|---|---|---|---|
| SD 15/15/6/15/11/15, frozen immediate | 4.0 | 0.9 | 0.2 | 0.1 | 0.2 | 0.9 | 3.5 |
| SD, frozen + latch held | 62.0 | 60.9 | 60.7 | 0.1 | 60.2 | 60.2 | 59.5 |
| T-SD P4, frozen immediate | 0.8 | 0.2 | 0.0 | 0.0 | 0.0 | 0.2 | 0.7 |
| T-SD P4, frozen + latch held | 38.2 | 18.6 | 35.9 | 0.0 | 12.1 | 18.6 | 18.7 |

If the chip latches a digit at the true slot start and keeps it through a frozen halt,
**every temporal scheme fails at any mismatch**, Mode SD worse than T-SD. Only the exact rate
passes. Probe 4 detects this case (section 10.6).

### 10.3 ISR jitter and wake timing (`modet_extra_jitter.md`, `modet_extra_wake.md`, 800 Hz)

| ISR entry delay 0..j ("late") | 1 us | 2 us | 5 us | 10 us | 20 us |
|---|---|---|---|---|---|
| T-SD P4 frozen, pp % own, exact / +0.5 % | 0.73 / 0.93 | 1.45 / 1.27 | 3.61 / 2.96 | 7.2 / 5.8 | 14.5 / 12.0 |
| T-SD P4 restart0, pp % own, exact | 0.41 | 0.81 | 2.02 | 4.0 | 8.0 |
| Mode SD frozen (section 5d), pp % FS | 0.9 | 1.8 | 4.4 | - | 8.6 |

T-SD needs the cycle-exact tick as much as Mode SD does: each us of jitter costs about 0.7 %
pp on the dimmest step. A fixed wake delay (0..250 us) only costs brightness (gain 96 % at 0,
81 % at 250 us), because the calibration includes it. Wake jitter of +-2 us passes
(1.8..2.8 % pp, frozen), and +-10 us fails (6.6..10 %). In that table the "PLAN" column for restart
at 0 fails only because +0.5 % lies outside that model's static-band window.

### 10.4 Lower global intensity codes (`modet_extra_intensity.md`)

Worst over -1..+1 % (frozen) or -0.5..+0.25 % (restart at 0), pp % own / band % FS:

| P, f_s | code 15 | 11 | 7 | 3 | 1 | 0 |
|---|---|---|---|---|---|---|
| 3, 800 frozen | 1.68 | 2.08 | 2.80 | 4.93 FAIL | 20.5 FAIL | 28.3 FAIL |
| 4, 800 frozen | 2.48 | 2.77 | 4.62 FAIL | 12.1 FAIL | 28.6 FAIL | 35.6 FAIL |
| 4, 1300 frozen | 1.55 | 1.69 | 4.09 FAIL | 9.4 FAIL | 21.6 FAIL | 23.9 FAIL |
| 3/4, restart at 0 (band) | 1.8..2.1 | 2.4..2.7 | 3.8..4.1 FAIL | 8 FAIL | 19 FAIL | 53..55 FAIL |

A shorter pulse narrows the window: with code c only (2c+1)/32 of each slot carries the blend.
Code 15 (the default and full LED_INT) and 11 keep +-1 %; at 7 the window shrinks to about
+-0.5 % (P = 4) and below 3 it is only usable close to the exact rate. The firmware passes LED_INT
straight to the chip in T-SD, so the README warns that dimming with /grid/led/intensity
costs rate tolerance.

### 10.5 Phase offsets and level mapping

Per-row offsets (row mod P) and per-LED offsets ((row + 2 col) mod P) of the dither pattern
change the worst single-LED pp by less than 0.3 % at every ratio (`modet_extra_offsets.md`).
The large-area flicker is lowest with **no** offsets (0.0..0.3 % of the average over all LEDs
of one level, against up to 1.7 % with offsets), because the residual comes from the digit
slot that straddles the halt, not from the dither pattern. The firmware uses none.

Host level L -> step: 0 for L = 0, else max(1, round(L P / 15)) (`modet_extra_mapping.md`).
This is the minimax monotonic fit to a linear ramp with 0 off and 15 full:
P = 3: `0 1 1 1 1 1 1 1 2 2 2 2 2 3 3 3` (max error 26.7 % FS), P = 4:
`0 1 1 1 1 1 2 2 2 2 3 3 3 3 4 4` (18.3 % FS).

### 10.6 Comparison and decision

| | T (no bracket) | **T-SD** (default) | SD (16 levels, opt-in) |
|---|---|---|---|
| levels | P + 1 | 4 (f_s < 750) / 5 | 16 |
| brightness, level 15 vs stock | 100 % | 94.7..97.9 % (dark 687 cycles per tick) | 72.6 % (5-frame, 500 Hz) .. 83 % (800 Hz) |
| window, frozen, immediate | +-0.8..2 % | **+-1.1..2.2 %** | +-0.08..0.30 % |
| window, frozen, next slot re-latch | exact only | +-1.1..2.2 % | +-0.1..0.3 % (sec. 5) |
| window, frozen, latch held | exact only | exact only | exact only |
| window, restart at 0 | (no shutdown) as above | -0.7..+0.35 % (static band) | -1.0..+0.22 % |
| same / next digit wake | n/a | fail | fail at 1.0 |
| needs cycle-exact tick | no | yes | yes |

T-SD is the default. It is 5..15 times more tolerant of rate mismatch than SD under the
frozen wake models, and no worse under any other model. The MAX7219 RC oscillator will drift
by more than +-0.1 %, but plausibly by less than +-1 %.

## 11. Firmware integration (step 3): harness additions and results

* `harness/gs64sim.[ch]`: ISR watch (`gs64sim_watch_isr`, CLI `-i LO:HI:FILE`) logs the entry and
  exit cycle of each pass through a PC range. The FT245 RD/WR fix is described above.
* `tests/monome_stub.c`: libmonome platform layer on the harness. Unchanged libmonome
  `libmonome.c`, `proto/mext.c` and `rotation.c` are built on top of it. Reads have posix.c
  semantics. Device bytes are delivered the way the FTDI chip does it, in USB packets of up to 62
  bytes or after the 16 ms latency timer. Without that, libmonome's `mext_read_msg` reads a
  header byte before its payload has arrived and fails, which could not happen with a real
  FTDI chip.
* `tests/e2e_libmonome.c` (step 3a) and `tests/test_fw.py` (3b..3e). Results:
  `results/e2e_*.log`, `results/fw_tests.md`. They run in `make test` (quick variants) and
  `make fwtest` (full).

The probe predictions from firmware traces are in `results/fw_tests.md`, and the interpretation
guide is in `../gs64rec10-vb/README-varibright.md`.
