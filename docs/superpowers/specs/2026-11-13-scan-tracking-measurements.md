# Scan tracking measurements (plan Task 2)

These are the measurements the scan tracking design depends on, taken on the real gs64rec10 unit on 2026-11-13 with the `0x0C` ADC capture and `varibright/tools/campaign.py`.
Raw results are in `varibright/sim/results/hw-2026-11-13/`.
The gate verdict is open: it needs the cold-start thermal run, which requires an owner power cycle.

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

## Gate status

- Steady state: the load model lands inside the window with margin.
- After a content change: the window moves out of reach for 20 to 60 s or more. Steadiness from the first frame requires the firmware to predict the thermal offset from load history to within about ±8 ticks, or to track it with the in-window position faster than it moves.
- Still to measure: the cold-start run (30 minutes unplugged, then `campaign.py thermal 40`), which gives the heating and cooling time constants and the power-up period.
