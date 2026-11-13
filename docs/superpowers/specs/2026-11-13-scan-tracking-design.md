# Scan tracking for the gs64rec10 varibright firmware

**Status (2026-11-13): failed and scrapped.** See [the measurements](2026-11-13-scan-tracking-measurements.md) for the verdict.

## Intent

The gs64rec10 monome 64 runs live music apps (Max/MSP patches, norns scripts and similar) through serialosc as a varibright grid.
These apps redraw constantly: playheads sweep, steps toggle, highlights move, often several times per second.
The owner's success criterion, in their words: keys look only dim or bright, with no annoying or even barely perceptible flicker.
A brief shimmer when the pattern changes counts as a failure.
The display must be steady from the first frame in every situation, including the first lit frame after a long dark or idle stretch and the first frame after power-up (owner: "it has to be steady from the first frame or it's not worth it").
A settling period after content returns is not acceptable.

The firmware in `varibright/gs64rec10-vb/64vb.c` gets brightness levels out of a MAX7219 by time multiplexing whole scan frames (T-SD mode).
This only works while the Timer1 frame period stays locked to the MAX7219's own scan.
Measurements on the real unit (below) show that no fixed period can hold that lock, because the chip's scan rate moves with the displayed content and with temperature.
This project makes the firmware keep the lock by itself: predict the scan rate from what is about to be shown, and correct slowly from the measured scan position.

## Goals

- 4 brightness levels (off plus 3 steps, T-SD with P = 3) with no visible flicker under constantly changing content, from cold start through warm operation.
- Host levels 0..15 keep mapping onto the available steps as `64vb.c` does today.
- No user calibration ritual. The band, the calibration UI and the stored period become fallbacks, not the normal path.
- Every behaviour verified mechanically on the real unit with the ADC capture tools, not by eye.

## Fallback

- If 4 levels cannot meet the flicker bar (steady from the first frame, under changing content and across warm-up), ship 3 levels: T-SD with P = 2 (off, dim, bright), held to the same bar and the same tracking. Owner's choice.
- If even 3 levels cannot meet the bar, the varibright effort is scrapped (owner's decision). Nothing that flickers ships. The builder stops, reports the measurements, and the owner chooses how to restore the unit (the stock firmware and FTDI EEPROM backups are in `varibright/backup/`).

## Stretch goal

- 16 levels (SD mode) if tracking proves tight enough, never at the cost of flicker.
  If SD cannot meet the flicker bar, 4 levels is the shipped result.

## Non-goals

- Hardware changes of any kind, including a sync wire, test equipment or component swaps.
- Changes to serialosc, libmonome or the host apps.
- Supporting other MAX7219 boards or clones beyond keeping the code generic where it is free.

## Anti-goals

These make it a failure even if the display is steady:

- Added latency on key events or LED updates that a player could notice.
- Anything that breaks serialosc or libmonome compatibility (the mext protocol in `64vb.c` README section 6).
- A visible start-up calibration step, or a visible probe pattern during normal use.
- Dropped host bytes or replies (the existing flow-control guarantee in README section 6).

## Constraints

- ATmega325 at 16 MHz. 32 KB flash (about 10 KB used), 2 KB RAM (661 B used today plus the capture code).
- The frame ISR (`TIMER1_COMPA_vect`) is cycle exact: `tick_align()` spins to `TCNT1L = VB_ALIGN_T0` (160) and the burst lasts 687 cycles between the two shutdown LOAD edges.
  Any other interrupt that is executing at compare match delays ISR entry.
  The README (section 7) measures about 88 cycles from compare match to the poll, plus up to about 40 when the key ISR runs, against the 160 budget.
  New interrupt work must keep ISR entry within that budget, or be scheduled so it can never be in flight at compare match.
- OCR1A is unbuffered in CTC mode. It can be rewritten early in the ISR (TCNT1 has just restarted), which the calibration band already does. So a per-frame period is possible.
- The FT245 output path has no TXE check by default (`VB_USE_TXE=0`).
- **Tilt must keep working on units that have it.** The owner's unit has no tilt sensor, but the firmware must not change tilt behaviour on other units. Tilt is off until a host sends `0x81 00`, so tracking can own the ADC while tilt is off. When a host enables tilt, tilt readings, rate and the `0x00` system query reply must stay as they are today, and tracking shares the ADC (for example by interleaving conversions, accepting a slower tracking update while tilt is on). Tilt must be a compatibility test item.
- Flashing uses the AVR ISP mkII on the unit. A chip erase clears EEPROM (hfuse 0x99, EESAVE unprogrammed).
- Build: `podman run --rm -v "$PWD":/src:Z gs64-avr make vb-clean vb VBFLAGS="-std=gnu11"` (see `varibright/Containerfile`).

## What is known from the real unit (2026-11-13)

Capture tool: the `0x0C` extension in `64vb.c` streams the ADC reading of the internal 1.1 V bandgap against AREF.
A supply dip from LED current raises the reading, so each MAX7219 digit slot that has lit LEDs shows as a pulse.
Options: `ADC_LIVE` (leave the display running), `ADC_SLOW` (9615.38 samples/s, safe alongside the frame ISR), `ADC_DEC8` (sums of 8 samples, gap free).

- **Pulse shape.** One full column at intensity 15 gives a bipolar response about 500 µs long: a dip of about 10 LSB, then a peak of about 14 LSB decaying over about 350 µs. Dark noise is 0.2 LSB rms. The response settles within one scan (1131 µs). Because it is bipolar, the average (DC) reading barely moves with light, so brightness cannot be read from a low-passed signal.
- **Scan rate.** 884.52 Hz with one column lit, early in the session. Harmonics at exactly 2x, 3x, 4x.
- **Load dependence.** Free-running scan rate with N full columns lit at intensity 15: 1 column 883.6..884.1 Hz, 4 columns 882.6 Hz, 6 columns 881.3..881.5 Hz, 8 columns 879.9 Hz. Global intensity barely matters (6 columns at intensity 3: 881.3 Hz). About 11.7 ticks of lock period per lit column.
- **Thermal drift.** The single-column rate fell from 884.52 Hz to about 883.6 Hz over the session. The lock moved by tens of ticks within about 10 minutes.
- **Wake behaviour.** Probes 1..3 say "frozen": the scan halts in shutdown and resumes. The chip keeps its scan position across wakes, so any rate error integrates into a steadily moving position.
- **Lock relation.** Zero scan creep was found at period 18747 with one dim column lit, which gives a per-wake loss of about 659 ticks: lock period = 16e6 / f_s + 659 (the firmware constant `VB_DARK_TICKS` is 687).
- **Creep is linear in period.** -1.635e-4 frames per 3-frame cycle per tick of period error (residual 0.0009 over 18560..18800). A few ticks of error already makes the scan wrap through the frame every few seconds.
- **Visual result.** Locked (measured zero creep): the owner saw 4 steady levels. Unlocked by drift or content change: flicker on the dim steps. The owner cannot tell 295 Hz (P = 3) from 442 Hz (P = 2) alternation when locked, so frame-rate alternation itself is not the problem.
- **Earlier measurement mistakes to avoid.** Averaging pulse energy over 26 ms blocks hid the wraps. Per-frame energy windows mix in the response tail of a pulse near a frame edge, so "light in dark frames" counts are partly artefacts. Position and creep (from the pulse centroid within the frame cycle) are the trustworthy metrics.

Host scripts that produced these numbers live in `/tmp/gs64/` and must be moved into `varibright/tools/` (see "Verification").

## Decided approach

1. **Feed-forward per frame.** When a frame's content is built, the firmware computes that frame's load and the matching period, and the ISR loads it into OCR1A for that frame. This is the only way to follow music-app redraws without a correction lag.
2. **Feedback from scan position.** The ADC measures where the scan sits relative to the frame ticks during normal display. A slow loop trims the feed-forward model (an offset, and possibly a gain) so the measured position stays at a target. This absorbs thermal drift and model error.
3. **Content-aware phase estimation.** The firmware knows the lit LEDs per digit in every frame, so it knows what current waveform to expect. The phase estimate correlates the ADC samples against that expectation.
4. **Prediction through blind stretches.** When the content gives no phase information (everything dark, or all digits equal), the firmware cannot measure, but the chip keeps drifting as it cools or warms. Because the owner requires steadiness from the first frame, the feed-forward must predict that drift: a thermal model driven by the recent load history (the ATmega325 has no temperature sensor), trained from cold-start and warm-up measurements. The same model sets the period at power-up. If prediction cannot hold the lock to within the creep criterion after realistic dark stretches, that is a stop-and-report point, not something to paper over.
5. **Build on `64vb.c`.** Same protocol, same T-SD and SD frame machinery, same burst code. The `0x0C` capture stays as a diagnostic.

## Open measurements (first tasks of the plan)

The approach depends on facts not yet measured. The plan must measure these first, with the capture tools, and adapt the design if they disagree:

- **Load model.** Is the scan rate a function of lit LEDs per digit, lit columns, total lit LEDs, or something else? Is it linear? Measure with row and column patterns.
- **Response speed.** Does the scan rate follow the content of each frame (fast, supply voltage) or the average over many frames (slow, temperature)? This decides whether the feed-forward is per frame or per content change.
- **Target position.** Does the steady result depend on where the halt point sits within a digit slot (for example, at a slot boundary versus mid-slot)? If yes, the loop should hold the halt point at the best spot, not just stop the creep.
- **Per-wake loss.** Confirm the 659-tick relation across loads, or find what it depends on.
- **Thermal behaviour.** The scan rate from a cold start through at least 30 minutes, and its response to load history (time constants for heating under load and cooling when dark). This decides whether blind-stretch prediction is feasible at all, so it is a gate for the rest of the work.

Hardware access: the builder flashes over ISP and runs all captures over the FT245 serial port. The owner performs power cycles and cold soaks when a test needs them, so those steps must be batched and announced with clear instructions.

## Verification

- Move the measurement scripts (`flick.py`, `drift.py`, `phase.py`, `frames.py`, `fsload.py`, `ripple.py`, `light.py`, and the helpers they use) from `/tmp/gs64/` into `varibright/tools/`, clean them up, and commit them with the capture firmware before the tracking work starts.
- Pass criterion for a steady display: scan creep within measurement noise (about ±0.0005 frames per cycle) and zero wrap-arounds across a capture, under each test pattern.
- Test patterns must include a static ramp, a moving playhead column, random step toggling at musical rates (2..16 changes per second), all-dark and all-lit screens, and a cold start followed by at least 30 minutes of warm-up.
- The owner's visual check comes last, after the mechanical checks pass. The owner has asked for mechanical verification rather than repeated visual judgements.

## Calls made by the designer

- P is forced to 3 for the 4-level goal (host levels 1..7, 8..12, 13..15 map to steps 1, 2, 3), instead of the automatic rule, which would pick P = 4 at this scan rate.

## Left to the builder

- How the ADC samples are scheduled alongside the cycle-exact ISR (Timer1 compare B auto trigger, scheduled conversions, or polling), as long as the ISR entry budget holds.
- The phase estimator's maths, update rate and loop gains.
- How the model and trim are stored (RAM only, or EEPROM for a faster warm start).
- What happens to the existing calibration UI, band and probes: keep them as diagnostics unless they get in the way.
- Whether SD (16 levels) is attempted, after 4 levels passes.
