## Firmware integration tests (full run, simulation only)

135 checks, 0 unexpected results, 326 s. EXPECTED-FAIL = a case outside the window that the synthetic sweeps predict for that wake / write model (for example the latch-held next-slot model at any mismatch); it is reported, not hidden.

| group | check | result | detail |
|---|---|---|---|
| robust | b1 garbage: device output parses into whole messages | PASS | 575 bytes, 76 messages |
| robust | b1 garbage: handshake answered exactly after resync | PASS | 5 handshake messages after resync |
| robust | b1 garbage: display correct after resync (T-SD, model) | PASS | worst LED error 0.01 % of stock |
| robust | b1 garbage: EEPROM calibration record untouched | PASS | b6 00 cf 50 c5 |
| robust | b2 all libmonome opcodes: stream stays in sync | PASS | 93 opcodes sent, 96 grid-size replies (expected 96) |
| robust | b2 all opcodes: display correct afterwards | PASS | worst LED error 0.10 % of stock |
| robust | b2 0x0B with a wrong key byte: no reply, no change, next command parsed | PASS | 03 08 08 |
| robust | b3 67 handshake queries: every reply complete | PASS | 67 query, 67 id, 67 size replies |
| robust | b4 TXE held high: nothing written while the FIFO is full | PASS | 0 bytes |
| robust | b4 output blocked for 300 ms: every reply delivered whole afterwards, key events in order | PASS | 1356 bytes, 30 query / 30 id replies, keys [(33, 5, 4), (32, 5, 4)] |
| robust | b4 level map sent while input was held back: applied intact | PASS | worst LED error 0.10 % of stock |
| flicker | c SD f_s 500 Hz, frozen-hold, rate +0.00 % | PASS | pp 0.56 % rms 0.17 % band 0.13 % FS, gain 97.9 % |
| flicker | c SD f_s 500 Hz, frozen-hold, rate +0.05 % | EXPECTED-FAIL | pp 77.18 % rms 4.58 % band 0.13 % FS, gain 97.9 % (outside the synthetic window / model variant) |
| flicker | c SD f_s 500 Hz, frozen-imm, rate -0.10 % | PASS | pp 2.69 % rms 0.21 % band 0.15 % FS, gain 97.9 % |
| flicker | c SD f_s 500 Hz, frozen-imm, rate -0.05 % | PASS | pp 1.30 % rms 0.18 % band 0.14 % FS, gain 97.9 % |
| flicker | c SD f_s 500 Hz, frozen-imm, rate +0.00 % | PASS | pp 0.56 % rms 0.17 % band 0.14 % FS, gain 97.9 % |
| flicker | c SD f_s 500 Hz, frozen-imm, rate +0.05 % | PASS | pp 1.23 % rms 0.18 % band 0.09 % FS, gain 97.9 % |
| flicker | c SD f_s 500 Hz, frozen-imm, rate +0.10 % | PASS | pp 2.00 % rms 0.21 % band 0.13 % FS, gain 97.9 % |
| flicker | c SD f_s 500 Hz, frozen-lat, rate +0.00 % | PASS | pp 0.56 % rms 0.17 % band 0.14 % FS, gain 97.9 % |
| flicker | c SD f_s 500 Hz, frozen-lat, rate +0.05 % | PASS | pp 1.23 % rms 0.18 % band 0.09 % FS, gain 97.9 % |
| flicker | c SD f_s 500 Hz, restart0, rate -0.50 % | PASS | pp 0.56 % rms 0.17 % band 0.62 % FS, gain 98.3 % |
| flicker | c SD f_s 500 Hz, restart0, rate +0.00 % | PASS | pp 0.56 % rms 0.17 % band 0.14 % FS, gain 97.9 % |
| flicker | c SD f_s 500 Hz, restart0, rate +0.20 % | PASS | pp 0.56 % rms 0.17 % band 2.02 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, frozen-hold, rate +0.00 % | PASS | pp 0.03 % rms 0.01 % band 0.07 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, frozen-hold, rate +0.10 % | EXPECTED-FAIL | pp 37.77 % rms 2.26 % band 0.08 % FS, gain 97.9 % (outside the synthetic window / model variant) |
| flicker | c TSD f_s 500 Hz, frozen-imm, rate -1.00 % | PASS | pp 2.91 % rms 0.31 % band 0.06 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, frozen-imm, rate -0.50 % | PASS | pp 1.20 % rms 0.11 % band 0.03 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, frozen-imm, rate +0.00 % | PASS | pp 0.03 % rms 0.01 % band 0.07 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, frozen-imm, rate +0.50 % | PASS | pp 1.16 % rms 0.11 % band 0.07 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, frozen-imm, rate +1.00 % | PASS | pp 2.82 % rms 0.32 % band 0.07 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, frozen-lat, rate -1.00 % | PASS | pp 2.91 % rms 0.31 % band 0.06 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, frozen-lat, rate +0.00 % | PASS | pp 0.03 % rms 0.01 % band 0.07 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, frozen-lat, rate +1.00 % | PASS | pp 2.82 % rms 0.32 % band 0.07 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, restart0, rate -0.50 % | PASS | pp 0.03 % rms 0.01 % band 0.80 % FS, gain 98.3 % |
| flicker | c TSD f_s 500 Hz, restart0, rate +0.00 % | PASS | pp 0.03 % rms 0.01 % band 0.07 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, restart0, rate +0.25 % | PASS | pp 0.03 % rms 0.01 % band 1.82 % FS, gain 97.9 % |
| flicker | c TSD f_s 500 Hz, restart0-lat, rate -0.50 % | PASS | pp 0.03 % rms 0.01 % band 0.80 % FS, gain 98.3 % |
| flicker | c TSD f_s 500 Hz, restart0-lat, rate +0.25 % | PASS | pp 0.03 % rms 0.01 % band 1.82 % FS, gain 97.9 % |
| flicker | c SD f_s 800 Hz, frozen-hold, rate +0.00 % | PASS | pp 0.18 % rms 0.04 % band 0.06 % FS, gain 96.7 % |
| flicker | c SD f_s 800 Hz, frozen-hold, rate +0.05 % | EXPECTED-FAIL | pp 59.56 % rms 3.57 % band 0.09 % FS, gain 96.7 % (outside the synthetic window / model variant) |
| flicker | c SD f_s 800 Hz, frozen-imm, rate -0.10 % | PASS | pp 0.88 % rms 0.08 % band 0.07 % FS, gain 96.7 % |
| flicker | c SD f_s 800 Hz, frozen-imm, rate -0.05 % | PASS | pp 0.44 % rms 0.05 % band 0.05 % FS, gain 96.7 % |
| flicker | c SD f_s 800 Hz, frozen-imm, rate +0.00 % | PASS | pp 0.18 % rms 0.04 % band 0.05 % FS, gain 96.7 % |
| flicker | c SD f_s 800 Hz, frozen-imm, rate +0.05 % | PASS | pp 0.41 % rms 0.04 % band 0.05 % FS, gain 96.7 % |
| flicker | c SD f_s 800 Hz, frozen-imm, rate +0.10 % | PASS | pp 0.90 % rms 0.07 % band 0.05 % FS, gain 96.7 % |
| flicker | c SD f_s 800 Hz, frozen-lat, rate +0.00 % | PASS | pp 0.18 % rms 0.04 % band 0.05 % FS, gain 96.7 % |
| flicker | c SD f_s 800 Hz, frozen-lat, rate +0.05 % | PASS | pp 0.41 % rms 0.04 % band 0.05 % FS, gain 96.7 % |
| flicker | c SD f_s 800 Hz, restart0, rate -0.50 % | PASS | pp 0.18 % rms 0.04 % band 0.70 % FS, gain 97.1 % |
| flicker | c SD f_s 800 Hz, restart0, rate +0.00 % | PASS | pp 0.18 % rms 0.04 % band 0.05 % FS, gain 96.7 % |
| flicker | c SD f_s 800 Hz, restart0, rate +0.20 % | PASS | pp 0.18 % rms 0.04 % band 1.75 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, frozen-hold, rate +0.00 % | PASS | pp 0.02 % rms 0.00 % band 0.06 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, frozen-hold, rate +0.10 % | EXPECTED-FAIL | pp 37.27 % rms 2.25 % band 0.09 % FS, gain 96.7 % (outside the synthetic window / model variant) |
| flicker | c TSD f_s 800 Hz, frozen-imm, rate -1.00 % | PASS | pp 2.78 % rms 0.36 % band 0.05 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, frozen-imm, rate -0.50 % | PASS | pp 1.15 % rms 0.13 % band 0.05 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, frozen-imm, rate +0.00 % | PASS | pp 0.01 % rms 0.00 % band 0.06 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, frozen-imm, rate +0.50 % | PASS | pp 1.10 % rms 0.13 % band 0.04 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, frozen-imm, rate +1.00 % | PASS | pp 2.74 % rms 0.35 % band 0.05 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, frozen-lat, rate -1.00 % | PASS | pp 2.78 % rms 0.36 % band 0.05 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, frozen-lat, rate +0.00 % | PASS | pp 0.01 % rms 0.00 % band 0.06 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, frozen-lat, rate +1.00 % | PASS | pp 2.74 % rms 0.35 % band 0.05 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, restart0, rate -0.50 % | PASS | pp 0.01 % rms 0.00 % band 0.92 % FS, gain 97.1 % |
| flicker | c TSD f_s 800 Hz, restart0, rate +0.00 % | PASS | pp 0.01 % rms 0.00 % band 0.04 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, restart0, rate +0.25 % | PASS | pp 0.02 % rms 0.00 % band 1.86 % FS, gain 96.7 % |
| flicker | c TSD f_s 800 Hz, restart0-lat, rate -0.50 % | PASS | pp 0.01 % rms 0.00 % band 0.92 % FS, gain 97.1 % |
| flicker | c TSD f_s 800 Hz, restart0-lat, rate +0.25 % | PASS | pp 0.02 % rms 0.00 % band 1.86 % FS, gain 96.7 % |
| flicker | c SD f_s 1300 Hz, frozen-hold, rate +0.00 % | PASS | pp 0.04 % rms 0.01 % band 0.05 % FS, gain 94.7 % |
| flicker | c SD f_s 1300 Hz, frozen-hold, rate +0.05 % | EXPECTED-FAIL | pp 37.07 % rms 2.28 % band 0.05 % FS, gain 94.7 % (outside the synthetic window / model variant) |
| flicker | c SD f_s 1300 Hz, frozen-imm, rate -0.10 % | PASS | pp 0.59 % rms 0.05 % band 0.04 % FS, gain 94.7 % |
| flicker | c SD f_s 1300 Hz, frozen-imm, rate -0.05 % | PASS | pp 0.27 % rms 0.02 % band 0.04 % FS, gain 94.7 % |
| flicker | c SD f_s 1300 Hz, frozen-imm, rate +0.00 % | PASS | pp 0.05 % rms 0.02 % band 0.04 % FS, gain 94.7 % |
| flicker | c SD f_s 1300 Hz, frozen-imm, rate +0.05 % | PASS | pp 0.28 % rms 0.02 % band 0.03 % FS, gain 94.7 % |
| flicker | c SD f_s 1300 Hz, frozen-imm, rate +0.10 % | PASS | pp 0.56 % rms 0.05 % band 0.04 % FS, gain 94.7 % |
| flicker | c SD f_s 1300 Hz, frozen-lat, rate +0.00 % | PASS | pp 0.05 % rms 0.02 % band 0.04 % FS, gain 94.7 % |
| flicker | c SD f_s 1300 Hz, frozen-lat, rate +0.05 % | PASS | pp 0.28 % rms 0.02 % band 0.03 % FS, gain 94.7 % |
| flicker | c SD f_s 1300 Hz, restart0, rate -0.50 % | PASS | pp 0.04 % rms 0.01 % band 0.78 % FS, gain 95.1 % |
| flicker | c SD f_s 1300 Hz, restart0, rate +0.00 % | PASS | pp 0.04 % rms 0.01 % band 0.04 % FS, gain 94.7 % |
| flicker | c SD f_s 1300 Hz, restart0, rate +0.20 % | PASS | pp 0.04 % rms 0.01 % band 1.77 % FS, gain 94.8 % |
| flicker | c TSD f_s 1300 Hz, frozen-hold, rate +0.00 % | PASS | pp 0.05 % rms 0.01 % band 0.04 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, frozen-hold, rate +0.10 % | EXPECTED-FAIL | pp 23.30 % rms 1.48 % band 0.03 % FS, gain 94.7 % (outside the synthetic window / model variant) |
| flicker | c TSD f_s 1300 Hz, frozen-imm, rate -1.00 % | PASS | pp 1.48 % rms 0.26 % band 0.04 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, frozen-imm, rate -0.50 % | PASS | pp 0.81 % rms 0.12 % band 0.04 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, frozen-imm, rate +0.00 % | PASS | pp 0.05 % rms 0.01 % band 0.04 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, frozen-imm, rate +0.50 % | PASS | pp 0.79 % rms 0.13 % band 0.04 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, frozen-imm, rate +1.00 % | PASS | pp 1.44 % rms 0.26 % band 0.03 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, frozen-lat, rate -1.00 % | PASS | pp 1.48 % rms 0.26 % band 0.04 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, frozen-lat, rate +0.00 % | PASS | pp 0.05 % rms 0.01 % band 0.04 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, frozen-lat, rate +1.00 % | PASS | pp 1.44 % rms 0.26 % band 0.03 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, restart0, rate -0.50 % | PASS | pp 0.03 % rms 0.01 % band 0.99 % FS, gain 95.1 % |
| flicker | c TSD f_s 1300 Hz, restart0, rate +0.00 % | PASS | pp 0.03 % rms 0.01 % band 0.04 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, restart0, rate +0.25 % | PASS | pp 0.03 % rms 0.01 % band 1.90 % FS, gain 94.7 % |
| flicker | c TSD f_s 1300 Hz, restart0-lat, rate -0.50 % | PASS | pp 0.03 % rms 0.01 % band 0.99 % FS, gain 95.1 % |
| flicker | c TSD f_s 1300 Hz, restart0-lat, rate +0.25 % | PASS | pp 0.03 % rms 0.01 % band 1.90 % FS, gain 94.7 % |
| calib | d1 key (0,0) at power-up starts the bracketed calibration band | PASS | bracket spacing 20687..20687 cycles (default 20687) |
| calib | d1 band: digits all 0xFF in the bracket, all 0x00 plain at half period | PASS | 5448 digit writes |
| calib | d1 keys +100 +100 -1 change the period to default + 199 | PASS | 20886..20886 |
| calib | d1 mode SD + preview: 6-frame codes 15/15/6/15/11/15 | PASS | codes [6, 11, 15] |
| calib | d1 probe 1 from the keypad: intensity 0, 50/50 us shutdown toggling | PASS | 17000 shutdown writes, spacing 800..800, intensity [0] |
| calib | d1 save: EEPROM record v2 written (mode SD, period) | PASS | b6 01 96 51 9c |
| calib | d1 after save: SD frames at the saved period | PASS | 268 bursts, spacing 20886 |
| calib | d2 reset with that EEPROM: SD at the saved period, 0x0A report | PASS | report 0a 03 01 06 00 51 96 51 96 |
| calib | d3 no calibration: no frame timer (no shutdown toggling) | PASS | 8 words |
| calib | d3 mono: digit registers show levels > 7 | PASS | [0, 7, 63, 254, 240, 128, 3, 31] |
| calib | d3 mono display (model) | PASS | worst LED error 0.00 % of stock |
| calib | d3 revision-2 record 0xB5 ignored (mono) | PASS | 0a 00 00 00 00 00 00 00 00 |
| calib | d4 0x0B T-SD: 4 frames at code 15, level 7 = 2 of 4 frames | PASS | 154 bursts |
| calib | d4 0x0B SD + save: 6-frame codes, EEPROM written | PASS | codes [6, 11, 15] |
| calib | d4 0x0B forced P = 3 (cfg 0x30): level 7 = step 1 of 3 (round(7*3/15)) | PASS | on-frames per cycle [1, 1, 1, 1, 1, 1, 1, 1, 1, 1] |
| calib | d4 0x0B replies: 0A status cfg nframes view period ee | PASS | 0a 01 00 04 00 50 cf 00 00; 0a 03 01 06 00 50 cf 50 cf; 0a 03 30 03 00 50 cf 50 cf; 0a 02 00 00 00 00 00 50 cf; 0a 02 00 00 00 00 00 50 cf |
| calib | d4 0x0B period 0: back to mono (timer off) | PASS |  |
| calib | d5 probe 1: 50 us awake / 50 us shutdown, reference second first, intensity [0] | PASS | first shutdown after 1.000 s, segment jitter 0 cycles (tick_align) |
| calib | d5 probe 2: 50 us awake / 50 us shutdown, reference second first, intensity [15] | PASS | first shutdown after 1.000 s, segment jitter 0 cycles (tick_align) |
| calib | d5 probe 3: 400 us awake / 100 us shutdown, reference second first, intensity [15] | PASS | first shutdown after 1.000 s, segment jitter 0 cycles (tick_align) |
| calib | d5 probe 4: T-SD P=4 mid level, period alternates p / p + 0.5 % every 2 s | PASS | periods [np.int64(20687), np.int64(20790)] |
| calib | d6 USB suspend: fade, frame timer stopped, MAX7219 shut down | PASS | last word 0xc=0, 0 words while asleep |
| calib | d6 wake: frames resume, LED state preserved (model) | PASS | worst LED error 0.04 % of stock |
| isr | e tick period under host traffic + key scan, TSD 500 Hz lo | PASS | 0x0C=0 spacing 32687..32687 cycles (period 32687), ISR entry..exit 963..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, TSD 500 Hz hi | PASS | 0x0C=0 spacing 32687..32687 cycles (period 32687), ISR entry..exit 960..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, SD 500 Hz lo | PASS | 0x0C=0 spacing 32687..32687 cycles (period 32687), ISR entry..exit 958..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, SD 500 Hz hi | PASS | 0x0C=0 spacing 32687..32687 cycles (period 32687), ISR entry..exit 958..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, TSD 800 Hz lo | PASS | 0x0C=0 spacing 20687..20687 cycles (period 20687), ISR entry..exit 962..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, TSD 800 Hz hi | PASS | 0x0C=0 spacing 20687..20687 cycles (period 20687), ISR entry..exit 961..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, SD 800 Hz lo | PASS | 0x0C=0 spacing 20687..20687 cycles (period 20687), ISR entry..exit 970..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, SD 800 Hz hi | PASS | 0x0C=0 spacing 20687..20687 cycles (period 20687), ISR entry..exit 971..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, TSD 1300 Hz lo | PASS | 0x0C=0 spacing 12995..12995 cycles (period 12995), ISR entry..exit 965..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, TSD 1300 Hz hi | PASS | 0x0C=0 spacing 12995..12995 cycles (period 12995), ISR entry..exit 967..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, SD 1300 Hz lo | PASS | 0x0C=0 spacing 12995..12995 cycles (period 12995), ISR entry..exit 983..987 cycles, 3414 device bytes |
| isr | e tick period under host traffic + key scan, SD 1300 Hz hi | PASS | 0x0C=0 spacing 12995..12995 cycles (period 12995), ISR entry..exit 982..987 cycles, 3414 device bytes |
| isr | e ISR within the 120 us budget: T-SD frames | PASS | max 62.1 us |
| isr | e cycle-exact tick: T-SD frames | PASS | spacing 20687..20687 |
| isr | e ISR within the 120 us budget: SD frames | PASS | max 62.1 us |
| isr | e cycle-exact tick: SD frames | PASS | spacing 20687..20687 |
| isr | e ISR within the 120 us budget: calibration band | PASS | max 62.1 us |
| isr | e ISR within the 120 us budget: probe 1 (50/50 us) | PASS | max 18.9 us |
| isr | e ISR within the 120 us budget: probe 3 (400/100 us) | PASS | max 18.9 us |
| isr | e ISR within the 120 us budget: probe 4 | PASS | max 62.1 us |

### Probe predictions from the firmware traces (model, f_s 800 Hz)

Row brightness in % of a stock row at intensity 15 (rows = digits 1..8 = LED x 0..7).
Probes 1..3: reference second / probe second. Probe 4: calibrated period / +0.5 %, with worst filtered pp % of own mean.

| probe (wake model) | first phase | second phase |
|---|---|---|
| probe 1 (restart0) | rows 3 3 3 3 3 3 3 3 % | rows 40 0 0 0 0 0 0 0 % |
| probe 1 (frozen-imm) | rows 3 3 3 3 3 3 3 3 % | rows 2 2 2 2 2 2 2 2 % |
| probe 1 (same-digit) | rows 3 3 3 3 3 3 3 3 % | rows 0 0 0 40 0 0 0 0 % |
| probe 1 (next-digit) | rows 3 3 3 3 3 3 3 3 % | rows 5 5 5 5 5 5 5 5 % |
| probe 2 (restart0) | rows 100 100 100 100 100 100 100 100 % | rows 413 0 0 0 0 0 0 0 % |
| probe 2 (frozen-imm) | rows 100 100 100 100 100 100 100 100 % | rows 50 50 50 50 50 50 50 50 % |
| probe 2 (same-digit) | rows 100 100 100 100 100 100 100 100 % | rows 0 0 0 413 0 0 0 0 % |
| probe 2 (next-digit) | rows 100 100 100 100 100 100 100 100 % | rows 52 52 52 52 52 52 52 52 % |
| probe 3 (restart0) | rows 100 100 100 100 100 100 100 100 % | rows 250 250 145 0 0 0 0 0 % |
| probe 3 (frozen-imm) | rows 100 100 100 100 100 100 100 100 % | rows 80 80 80 80 80 80 80 80 % |
| probe 3 (same-digit) | rows 100 100 100 100 100 100 100 100 % | rows 99 62 99 62 99 62 99 62 % |
| probe 3 (next-digit) | rows 100 100 100 100 100 100 100 100 % | rows 81 80 81 81 81 81 81 81 % |
| probe 4 (frozen-imm) | rows 48 48 48 48 48 48 48 48 %, pp 0 % | rows 48 48 48 48 48 48 48 48 %, pp 0 % |
| probe 4 (frozen-hold) | rows 48 48 48 48 48 48 48 48 %, pp 0 % | rows 49 48 48 48 48 48 48 49 %, pp 19 % |
| probe 4 (restart0) | rows 48 48 48 48 48 48 48 48 %, pp 0 % | rows 50 48 48 48 48 48 48 48 %, pp 0 % |
| probe 4 (same-digit) | rows 48 48 48 48 48 48 48 48 %, pp 0 % | rows 48 48 48 48 48 50 48 48 %, pp 0 % |
| probe 4 (next-digit) | rows 48 48 48 48 48 48 48 48 %, pp 0 % | rows 49 48 49 48 49 48 49 48 %, pp 0 % |

### ISR duration in simavr (cycles from the first ISR instruction to after reti; add 7 for interrupt response and the vector jmp)

| mode | ISR passes | min | max | max incl. response, us | burst 0x0C=0 .. 0x0C=1 LOAD, cycles | tick spacing min..max |
|---|---|---|---|---|---|---|
| T-SD frames | 1431 | 963 | 987 | 62.1 | 687..687 | 20687..20687 |
| SD frames | 1431 | 972 | 987 | 62.1 | 687..687 | 20687..20687 |
| calibration band | 1315 | 663 | 987 | 62.1 | 687..687 | 20687..20687 |
| probe 1 (50/50 us) | 46999 | 290 | 296 | 18.9 | - | 1600..1600 |
| probe 3 (400/100 us) | 9400 | 292 | 296 | 18.9 | - | 8000..8000 |
| probe 4 | 1815 | 959 | 987 | 62.1 | - | 20687..20790 |
