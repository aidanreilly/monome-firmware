# Scan tracking implementation plan

**Status (2026-11-13): stopped at the Task 2 gate. The project failed and was scrapped.** See [the measurements](../specs/2026-11-13-scan-tracking-measurements.md).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the gs64rec10 varibright display locked to the MAX7219 scan under changing content, warm-up and dark stretches, so 4 levels (or the 3-level fallback) are steady from the first frame.

**Architecture:** Per-frame feed-forward period computed from each frame's LED load, plus a thermal term driven by load history, plus a slow trim from an in-firmware ADC scan-position sensor. Host-side Python tools measure creep, wraps and position on the real unit and act as the test suite.

**Tech Stack:** C (avr-gcc 15, `-std=gnu11`, ATmega325) built in the `gs64-avr` podman image; Python 3 stdlib `unittest` plus numpy and pyserial for host tools; avrdude with the AVR ISP mkII.

**Spec:** `docs/superpowers/specs/2026-11-13-scan-tracking-design.md`

## Global Constraints

- Steady from the first frame in every situation, including after long dark stretches and at power-up. No settling period.
- Pass criterion for "steady": scan creep within about ±0.0005 frames per cycle and zero wrap-arounds across a capture, for every test pattern.
- 4 levels = T-SD with P forced to 3 (host levels 1..7, 8..12, 13..15 map to steps 1, 2, 3). Fallback: P = 2. If P = 2 also fails, stop and report; the owner scraps the effort.
- No hardware changes. No changes to serialosc, libmonome or host apps. mext protocol unchanged for every opcode libmonome sends.
- No added key or LED latency a player could notice. No dropped host bytes or replies.
- No visible start-up calibration and no visible probe pattern in normal use.
- Tilt behaviour unchanged on units that have it: readings, rate and the `0x00` reply (`00 01 01 00 02 01 00 08 01` with `VB_TILT=1`).
- Frame ISR stays cycle exact: ISR entry must reach the `tick_align()` poll before `TCNT1L = 160` (`VB_ALIGN_T0`).
- Build: `podman run --rm -v "$PWD":/src:Z gs64-avr make vb-clean vb VBFLAGS="-std=gnu11"` from `varibright/gs64rec10-vb`. Flash: `avrdude -c avrispmkII -P usb -p m325 -e -U flash:w:64vb.hex:i` (erases EEPROM).
- Measurement is mechanical. The owner's visual check comes only after mechanical checks pass. Owner actions (power cycles, cold soaks) are batched and announced with instructions.
- Markdown in this repo: one sentence per line, no hard wraps, no dashes.

## Review Focus

- **Host intensity changes (`0x17`) while content is steady.** Intensity barely moves the scan rate (measured), but it scales pulse size, so the position sensor must not misread a dimmer screen as a phase change. Test in Task 5.
- **Full-screen redraws mid-cycle (`0x1A` level map, `0x12`/`0x13` all off/on).** The per-frame period table must change atomically with the frame buffer, or one frame runs with the wrong period. Test in Task 3.
- **USB suspend and resume (PWREN).** The timer stops and restarts. Tracking state must survive, and the first frame after resume must be locked. Test in Task 6.
- **serialosc connect sequence.** libmonome sends `led_all(0)` then the app's first frame, possibly after a long dark stretch. The first lit frame must be locked. Test in Task 6.
- **Mono fallback and the calibration UI still work.** With tracking disabled or no model, the unit must behave as `64vb.c` does today. Test in Task 7.

---

### Task 1: Measurement tools in the repo, committed with the capture firmware

**Files:**
- Create: `varibright/tools/gs64/__init__.py`, `varibright/tools/gs64/link.py`, `varibright/tools/gs64/capture.py`, `varibright/tools/gs64/analysis.py`
- Create: `varibright/tools/gs64meter.py` (CLI)
- Create: `varibright/tools/tests/test_capture.py`, `varibright/tools/tests/test_analysis.py`
- Create: `varibright/tools/README.md`
- Commit: `varibright/gs64rec10-vb/64vb.c` (the existing `0x0C` capture with `ADC_LIVE`, `ADC_SLOW`, `ADC_DEC8`)
- Source material: `/tmp/gs64/*.py` (prototypes: `q.py`, `vbset.py`, `levels.py`, `flick.py`, `drift.py`, `phase.py`, `frames.py`, `fsload.py`, `ripple.py`, `light.py`)

**Interfaces:**
- Produces, `gs64.link`:
  - `class Grid(port='/dev/ttyUSB0')` with `vbset(period:int, flags:int, cfg:int) -> dict` (parsed `0x0A` report: `status, cfg, nframes, view, period, ee_period`), `state() -> dict`, `level(x, y, l)`, `level_all(l)`, `intensity(g)`, `pattern(levels: list[list[int]])` (8x8, `[x][y]`), `capture(nblk:int, flags:int, mux:int=0x1E, cols:int=0) -> bytes`.
- Produces, `gs64.capture`:
  - `parse_blocks(raw: bytes, decimated: bool=False) -> list[tuple[int, numpy.ndarray]]` (true block index recovered from the 5-bit counter, complete blocks only).
  - `TPS_FAST = 64*13`, `TPS_SLOW = 128*13`, `TPS_DEC8 = 128*13*8` (timer ticks per output sample).
- Produces, `gs64.analysis`:
  - `scan_rate(blocks, tps) -> float` (Hz, refined peak, as `ripple.py`/`fsload.py`; for all-equal columns use the 8x digit line).
  - `creep(blocks, tps, cycle_ticks, nf) -> dict` with keys `creep` (mean of steps with |step| < 0.15 frames, in frames per cycle), `jumps` (count of |step| ≥ 0.15), `steps` (int).
  - `position(blocks, tps, cycle_ticks, nf) -> dict` with keys `mean` (frames), `spread` (rms about trend, frames), `drift` (frames/s).
  - `steady(c: dict) -> bool` returns `abs(c['creep']) <= 0.0005 and c['jumps'] == 0`.
- CLI: `gs64meter.py state | fs [--cols N] | creep PERIOD CFG LEVEL | position PERIOD CFG LEVEL | sweep START STOP STEP CFG LEVEL`.

- [ ] **Step 1: Write failing tests for parsing and analysis**

`test_capture.py`:
- `test_parse_roundtrip`: encode 3 blocks of known 10-bit values with markers `0xC0|k`, sample bytes `0x80|(v>>5)`, `v&0x1F`, end `0xFE`; `parse_blocks` returns indices `[0,1,2]` and the values.
- `test_parse_drops_incomplete_and_keeps_index`: delete 2 bytes inside block 1 and the whole marker of block 3 out of 5; result contains only blocks `0` and `4`, with indices `0` and `4` (block 1 is short, block 3 without its marker merges into block 2 and both are dropped as incomplete, and block 4 keeps index 4 through the counter).
- `test_parse_decimated`: 13-bit sums encoded `0x80|(v>>7)`, `v&0x7F`; values round-trip up to 8184.

`test_analysis.py` (synthetic signals, no hardware):
- `test_creep_zero_for_locked_pulse`: pulse train with one pulse per cycle at fixed phase 0.38 frames, nf=3, 1300 cycles; `creep` within ±1e-4, `jumps == 0`.
- `test_creep_measures_known_slide`: pulse phase advancing 0.0175 frames per cycle with wraps; `creep` within 0.0175 ± 0.001, `jumps >= 1`.
- `test_scan_rate_finds_884_52`: pulse train at 884.52 Hz sampled at `16e6/TPS_FAST` with gaps; result within ±0.01 Hz.
- `test_steady`: `{'creep':0.0004,'jumps':0}` → True; `{'creep':0.0006,'jumps':0}` → False; `{'creep':0,'jumps':1}` → False.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd varibright/tools && python3 -m unittest discover -s tests -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'gs64'`.

- [ ] **Step 3: Implement `gs64.link`, `gs64.capture`, `gs64.analysis` and `gs64meter.py`**

Port the logic from the `/tmp/gs64` prototypes; `creep` and `position` follow `drift.py` and `phase.py` (circular centroid of the positive lobe per cycle).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd varibright/tools && python3 -m unittest discover -s tests -v`
Expected: all PASS.

- [ ] **Step 5: Hardware smoke test**

Run: `python3 varibright/tools/gs64meter.py fs --cols 1`
Expected: a rate between 878 and 887 Hz.
Run: `python3 varibright/tools/gs64meter.py creep 18750 0x30 1`
Expected: prints `creep`, `jumps`, `steps` (values depend on drift).

- [ ] **Step 6: Commit**

```bash
git add varibright/tools varibright/gs64rec10-vb/64vb.c
git commit -m "Add ADC capture extension and scan measurement tools"
```

---

### Task 2: Measurement campaign and go/no-go gate

**Files:**
- Create: `varibright/tools/campaign.py` (scripted measurements below, results as JSON)
- Create: `varibright/sim/results/hw-2026-11-13/` (JSON results)
- Create: `docs/superpowers/specs/2026-11-13-scan-tracking-measurements.md` (findings, fitted model, gate decision)

**Interfaces:**
- Consumes: `gs64.link.Grid`, `gs64.analysis.scan_rate`, `creep`, `position`.
- Produces: model coefficients used by Task 3 and Task 6, written in the findings doc as a table: `D` (per-wake loss, ticks), load model form and coefficients, response speed verdict (per frame or averaged), thermal model form, time constants and coefficients, target position verdict.

Mono mode plus `ADC_LIVE` capture shows any host pattern on a free-running chip, so free-running rate measurements need no new firmware.

- [ ] **Step 1: Load model.** In mono, measure `scan_rate` for: 1..8 full columns; 1..8 full rows; 8, 16, 32, 64 LEDs spread evenly; the same LED count concentrated in one column versus spread. Repeat the 1-column reference between each to subtract drift. Fit rate against candidate load measures (lit LEDs, lit columns, max LEDs per digit, sum over digits of LEDs squared). Record the best fit and its residual in ticks.
- [ ] **Step 2: Per-wake loss.** In T-SD P=3 with static content of 1, 4 and 8 lit columns (all steps full so every frame has the same load), find the zero-creep period with a `creep` sweep and line fit, and compare with `16e6/scan_rate + D` from Step 1 to get `D` per load.
- [ ] **Step 3: Response speed.** In T-SD P=3, show content whose frames differ in load (step-1 LEDs on 7 columns, so frame 0 is heavy and frames 1 and 2 are light, plus one fixed step-3 column as the position marker). Find the zero-creep period. Compare with the period predicted from (a) the average load and (b) the sum of per-frame periods. Record which matches.
- [ ] **Step 4: Target position.** At a locked period, shift the scan position by setting the period off by a known amount for a known number of cycles and back. Measure position before and after. Then hold each of 8 positions across one digit slot for 60 s, with `creep` and `position` spread at each, to see whether stability depends on the halt point within a slot.
- [ ] **Step 5: Thermal (owner action).** Ask the owner to unplug the grid for 30 minutes, then plug it in. Log the 1-column `scan_rate` every 30 s for 40 minutes under a fixed load (4 full columns at full intensity), then 10 minutes all dark with a 1-column measurement every 60 s, then back to load. Fit a first-order heating model: rate = r_cold + k * filtered load, with heating and cooling time constants.
- [ ] **Step 6: Gate.** Using the fitted models, predict the zero-creep period for the Step 5 timeline and compare with measured creep zero points. The required prediction accuracy is the period error that keeps creep within ±0.0005 frames/cycle: 0.0005 / 1.635e-4 ≈ **3 ticks**. Write the verdict in the findings doc: GO if the model predicts within 3 ticks across the timeline, including the first measurement after the dark stretch; otherwise NO-GO for P=3, and repeat the gate for P=2 (measure the P=2 creep slope first). On NO-GO for both, stop and report to the owner.
- [ ] **Step 7: Commit**

```bash
git add varibright/tools/campaign.py varibright/sim/results/hw-2026-11-13 docs/superpowers/specs/2026-11-13-scan-tracking-measurements.md
git commit -m "Measure MAX7219 load, wake and thermal behaviour on the real unit"
```

**Stop here and report the gate result to the owner before Task 3.**

---

### Task 3: Per-frame feed-forward period

**Files:**
- Create: `varibright/gs64rec10-vb/track.h`, `varibright/gs64rec10-vb/track.c` (model, load computation, period table)
- Modify: `varibright/gs64rec10-vb/64vb.c` (ISR loads per-frame OCR1A; `fb_led`/`vb_configure`/`set_all` update load; new extension `0x0D`)
- Modify: `varibright/gs64rec10-vb/Makefile` (`track.c` in the `vb` and `sim` builds)
- Modify: `varibright/tools/gs64/link.py` (`track_get()`, `track_set(...)`)
- Test: `varibright/tools/tests/test_track_model.py`, `varibright/tools/hwtest_feedforward.py`

**Interfaces:**
- Consumes: model form and coefficients from Task 2's findings doc.
- Produces, firmware:
  - `void track_frame_load(uint8_t f)` recomputes `frame_period[f]` from `fb[f]` (call after any change to `fb[f]`).
  - `volatile uint16_t frame_period[NF_MAX]` (ticks; the ISR writes `OCR1A = frame_period[next] - 1` before `tick_align()`).
  - `int16_t track_offset` (ticks, the trim Task 5 adjusts) and `int16_t track_thermal` (ticks, Task 6).
  - Extension `0x0D` (length 8): `0D A5 op b0 b1 b2 b3 b4`. `op=0` get, `op=1` set model params, `op=2` set offset, `op=3` enable/disable tracking. Reply `0D` + 12 bytes: `enabled, offset_hi, offset_lo, thermal_hi, thermal_lo, pos_hi, pos_lo, conf, late_count, frame_period[0]_hi, _lo, flags`. Add `0x0D` to `len_sys` (8). libmonome never sends it.
- Produces, host: `Grid.track_get() -> dict`, `Grid.track_set(op:int, payload:bytes) -> dict`.
- A Python mirror `varibright/tools/gs64/model.py: frame_period(fb_frame: list[int], params: dict) -> int` used to check the firmware table.

- [ ] **Step 1: Write the failing tests.**
  - `test_track_model.py`: `frame_period` matches hand-computed values from the Task 2 coefficients for empty, 1-column, 8-column and mixed frames.
  - `hwtest_feedforward.py`: for each of (static 1-column ramp, static 6-column ramp, Task 2 Step 3 heavy/light content, and a `0x1A` full redraw between two of these every 2 s), enable tracking with offset 0 and the thermal term frozen, read `0x0D` and check `frame_period[0]` equals `model.frame_period` for the current frame 0, then run `creep` and assert `steady()`.
- [ ] **Step 2: Run to verify they fail.** `python3 -m unittest varibright/tools/tests/test_track_model.py` fails with `ModuleNotFoundError`; `hwtest_feedforward.py` fails because `0x0D` gets no reply.
- [ ] **Step 3: Implement** `track.c`/`track.h`, the ISR change, the load updates and `0x0D`, and `gs64/model.py`. The frame buffer and `frame_period` must change together: update both while the frame being changed is not the one the ISR loads next, or inside one `ATOMIC_BLOCK`. Add a `late_count` that the ISR increments when `TCNT1L` is already ≥ `VB_ALIGN_T0` at the poll.
- [ ] **Step 4: Run to verify they pass.** Unit test passes. `hwtest_feedforward.py` reports `steady` for every case and `late_count` stays 0. The `0x00`, `0x01`, `0x05` replies are unchanged (`gs64meter.py state`).
- [ ] **Step 5: Commit**

```bash
git add varibright/gs64rec10-vb varibright/tools
git commit -m "Add per-frame feed-forward period from frame load"
```

---

### Task 4: In-firmware scan position sensor

**Files:**
- Modify: `varibright/gs64rec10-vb/track.c`, `track.h`, `64vb.c`
- Test: `varibright/tools/hwtest_sensor.py`

**Interfaces:**
- Consumes: `fb[f]` (expected per-digit load), Timer1, the ADC.
- Produces: `int16_t track_pos` (scan position in 1/256 frame units, relative to the frame tick), `uint8_t track_conf` (0 = no information, 255 = strong), both reported by `0x0D`.

Scheduling must keep every ADC conversion and any ADC interrupt out of the window where it could delay `TIMER1_COMPA_vect` entry. The builder chooses the mechanism (Timer1 compare B auto trigger, scheduled conversions, or polling). When a host has tilt enabled, tilt conversions interleave and keep their current rate.

- [ ] **Step 1: Write the failing test.** `hwtest_sensor.py`: for static contents (1 column, 3 columns, ramp), compare `track_pos` from `0x0D` (average of 20 reads) with the host `position()` measured from a live capture at the same time. Assert agreement within 0.02 frames and `track_conf > 0`. For all-dark and all-equal content assert `track_conf == 0`. Then shift the position (Task 2 Step 4 method) and assert `track_pos` follows within 1 s. Assert `late_count` stays 0 throughout, and with tilt enabled (`81 00`) assert tilt events still arrive at the same rate as before the change (measure both with `gs64meter.py`, owner unit gives floating readings but the rate and format are testable).
- [ ] **Step 2: Run to verify it fails.** `track_pos` reads 0 and `track_conf` 0 for all content.
- [ ] **Step 3: Implement the sensor.** Accumulate ADC samples by frame and phase bin, correlate against the waveform expected from each frame's per-digit LED counts, and update `track_pos` and `track_conf` a few times per second.
- [ ] **Step 4: Run to verify it passes.** All assertions in `hwtest_sensor.py` pass.
- [ ] **Step 5: Commit**

```bash
git add varibright/gs64rec10-vb varibright/tools
git commit -m "Add ADC scan position sensor"
```

---

### Task 5: Trim loop

**Files:**
- Modify: `varibright/gs64rec10-vb/track.c`
- Create: `varibright/tools/patterns.py` (dynamic test content)
- Test: `varibright/tools/hwtest_loop.py`

**Interfaces:**
- Consumes: `track_pos`, `track_conf`, `track_offset`.
- Produces: `void track_update(void)` called from the main loop; adjusts `track_offset` only when `track_conf` is above a threshold; holds otherwise. Target position from Task 2 Step 4 (or the first locked position if position does not matter).
- `patterns.py` produces generators: `ramp()`, `playhead(rate_hz)`, `random_steps(changes_per_s)`, `all_lit()`, `all_dark()`, `intensity_sweep()` (host `0x17` 15 → 3 → 15 every 5 s).

- [ ] **Step 1: Write the failing test.** `hwtest_loop.py`: start with `track_offset` deliberately 10 ticks off, run each pattern for 5 minutes (`playhead` at 2, 8, 16 Hz, `random_steps` at 2 and 16 per second, `intensity_sweep`), take a live capture every 30 s, and assert `steady()` on every capture after the first 10 s, `late_count == 0`, and that `track_pos` stays within the target band.
- [ ] **Step 2: Run to verify it fails.** With the loop absent, the 10-tick offset produces creep about 0.0016 frames/cycle and wraps.
- [ ] **Step 3: Implement `track_update()`.** A slow integrator on position error; gain small enough that one update cannot move the period by more than 1 tick.
- [ ] **Step 4: Run to verify it passes.** All captures steady after the first 10 s. The 10 s allowance applies only to this deliberately wrong start, never to normal operation (Task 6 removes it).
- [ ] **Step 5: Commit**

```bash
git add varibright/gs64rec10-vb varibright/tools
git commit -m "Add scan position trim loop"
```

---

### Task 6: Thermal prediction, power-up and blind stretches

**Files:**
- Modify: `varibright/gs64rec10-vb/track.c` (thermal state driven by load history), `64vb.c` (power-up and resume paths)
- Test: `varibright/tools/hwtest_blind.py`

**Interfaces:**
- Consumes: Task 2 thermal model and coefficients, per-frame load from Task 3.
- Produces: `track_thermal` updated every frame cycle from a first-order filter of load with separate heating and cooling time constants; initial state at power-up from the cold-start fit; state kept across USB suspend.

- [ ] **Step 1: Write the failing test.** `hwtest_blind.py`, steady from the first frame (no allowance):
  - Dark stretches of 1, 5 and 15 minutes after 10 minutes of heavy load, then `ramp()`: the first capture (started before the content is sent, so it covers the first frames) shows `jumps == 0`, and creep over the first 2 s is within ±0.0005.
  - serialosc-style sequence: `0x12` (all off), 60 s dark, then a level map: same assertions.
  - USB suspend/resume: owner action, unplug for 10 s and replug with content already set by a script that runs on reconnect; same assertions.
  - Cold start: owner action, unplug for 30 minutes, plug in, the script sends `ramp()` as soon as the port appears; same assertions, then `steady()` on captures every minute for 30 minutes.
- [ ] **Step 2: Run to verify it fails.** Without the thermal term, the 15-minute dark stretch case shows wraps in the first capture.
- [ ] **Step 3: Implement the thermal term and the power-up/resume initial state.**
- [ ] **Step 4: Run to verify it passes.** All cases pass. If the cold-start or 15-minute dark case cannot pass, run the same test with P=2. If that also fails, stop and report to the owner (scrap decision).
- [ ] **Step 5: Commit**

```bash
git add varibright/gs64rec10-vb varibright/tools
git commit -m "Add thermal prediction for dark stretches and power-up"
```

---

### Task 7: Defaults, compatibility and documentation

**Files:**
- Modify: `varibright/gs64rec10-vb/64vb.c` (tracking on by default; P forced to 3 by default, or P = 2 if Task 6 fell back; EEPROM record optional)
- Modify: `varibright/gs64rec10-vb/README.md` (how tracking works, `0x0C`/`0x0D` extensions, measured numbers), `varibright/BRINGUP.md` (tools replace the eyeball steps), `varibright/tools/README.md`
- Test: `varibright/tools/hwtest_compat.py`

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: Write the failing test.** `hwtest_compat.py`: after a fresh flash (EEPROM erased) and replug, `state()` shows varibright active with `nframes == 3` (or 2) and no calibration needed; `0x00`, `0x01`, `0x05` replies byte-identical to today; tilt enable/disable (`81 00`, `82 00`) works and tilt events have the existing format; `0x0D op=3` disable returns the unit to mono behaviour; the calibration UI entry (key (0,0) at power-up) still works (owner action, optional).
- [ ] **Step 2: Run to verify it fails.** On a fresh flash today the unit starts in mono (`nframes == 0`).
- [ ] **Step 3: Implement defaults and update the docs.**
- [ ] **Step 4: Run to verify it passes.** All assertions pass. Then run `hwtest_loop.py` and `hwtest_blind.py` once more on the final build.
- [ ] **Step 5: Owner visual check.** Start serialosc (`systemctl --user start serialosc`), run a norns or Max sequencer patch with dim and bright keys for at least 15 minutes from a cold start. Pass: the owner sees no flicker at all.
- [ ] **Step 6: Commit**

```bash
git add varibright docs
git commit -m "Enable scan tracking by default and document it"
```

---

### Task 8 (stretch): 16 levels

Only after Task 7 passes with P = 3. Repeat the Task 5 and Task 6 hardware tests with `cfg = 0x01` (SD). If every case passes, offer SD to the owner as an option; never make it the default unless the owner asks. If any case fails, record the result in the findings doc and stop.
