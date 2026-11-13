# Scan tracking measurements (plan Task 2)

These are the measurements the scan tracking design depends on, taken on the real gs64rec10 unit on 2026-11-13 with the `0x0C` ADC capture and `varibright/tools/campaign.py`.
Raw results are in `varibright/sim/results/hw-2026-11-13/`.
The project failed its gate and was scrapped (see "Verdict").

## Capture range (pull-in)

The MAX7219 scan pulls in to the frame ticks.
Within a window of periods the scan holds still: creep is 0 and the position spread is below 0.05 frames.
Outside the window the scan slides at about 0.005 frames per cycle, almost independent of the period error.
This replaces the design's "creep is linear in period" relation, which was fitted to points inside and outside the window.

The following table lists the measured windows for T-SD with P = 3 (`range.json`, `response.json`, `response_uneven.json`).

| Content | Average lit LEDs per frame | Held window (ticks) | Centre |
|---|---|---|---|
| Marker only (`marker_load(0)`) | 2.7 | 18765..18781 | about 18775 |
| Marker plus 2 columns | 18.7 | 18808..18820 | about 18814 |
| 4 columns at step 2 (frames uneven) | 21.3 | 18815..18827 | about 18821 |
| Marker plus 3 columns | 26.7 | 18830..18838 | about 18834 |
| Marker plus 6 columns | 50.7 | 18895..18911 | about 18903 |

- The window is 8 to 20 ticks wide. Entering from below holds less of the window than leaving from inside (hysteresis).
- **Load model:** centre = 18775 + 2.7 × (average lit LEDs − 2.7) ticks, warm unit. It predicts the 18.7 and 21.3 LED windows within 4 ticks.
- **Response:** the window follows the cycle-average load, not each frame's load. Uneven frames with the same average sit where the average predicts. Per-frame periods are not needed.
- **Position inside the window:** the held position moves smoothly with the period (load 0: 0.59, 0.82 and 0.90 frames at 18781, 18773 and 18765). This is a feedback signal for where the firmware sits in the window. It replaces the planned `target` sweep.
- **P = 2** (`range_p2.json`): the windows are no wider (load 0 held only at 18775 on an 8-tick grid, load 6 at 18895..18911). The 3-level fallback does not add margin.

## Content switch (`switch.json`)

Content and the load-model period were changed together after 60 s on the previous content.

| Switch | Period | 0.7 s after | 20 s after | 60 s after |
|---|---|---|---|---|
| Heavy (6 columns) to light | 18775 | sliding, +0.008 | sliding, +0.005 | held |
| Light to heavy (6 columns) | 18905 | sliding | sliding | sliding |

The load model alone does not hold the scan after a content change.
Self-heating moves the window by tens of ticks over the following minute, against a half-width of about 8 ticks.
This agrees with the free-running `step.json` result: about 3 Hz moves instantly with the load and a further 2.5 Hz follows over tens of seconds (2.5 Hz is about 50 ticks of period).

## Estimator notes

Per-block positions alternated under load because of timer-locked content (the shutdown dip and a sub-sample spike) leaking into the cycle fundamental.
Positions now come from windows of whole cycles that also span a near-whole number of samples (15 cycles at period 18821).
Content that fills most of one frame (for example 7 of 8 columns lit in one frame only) carries no usable position, and the meter reports it as held at every period.

## Cold start (partial)

The cold-start run was stopped after 2 points when the project ended.
After 30 minutes unplugged, the 1-column free-running rate was 884.81 Hz at 0.1 min and 883.09 Hz at 0.7 min under a 4-column load.
That is a drop of 1.7 Hz (about 35 ticks of lock period) in the first 40 s after power-up.

## Verdict: failed, varibright scrapped

The owner ended the project on 2026-11-13, before the thermal model was fitted.
The decisive findings:

- The lock window is about ±8 ticks of 18,800 (±0.04%). The MAX7219 scan comes from an internal RC oscillator, and 0.04% is in the range of a degree or two of die temperature or a small supply change, so open-loop prediction cannot hold it.
- After every content change, and in the first minute after power-up, the window moves by 35 to 50 ticks. That breaks the owner's requirement of a steady display from the first frame unless feedback can correct faster than the chip heats or cools, which no measurement here supports.
- The 3-level fallback (P = 2) has windows no wider than P = 3, so it does not rescue the bar.
- Scaling is poor even if one unit could be made to work. The constants are per chip, clone drivers might not pull in at all, and the 128 and 256 editions drive 2 or 4 MAX7219s with independent oscillators from one frame timer.

The unit was restored to its stock firmware, stock EEPROM and stock FTDI EEPROM from `varibright/backup/` (not committed).
