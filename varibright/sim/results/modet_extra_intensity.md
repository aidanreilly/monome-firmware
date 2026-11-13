## T-SD at lower global intensity codes (0x17 / MAX7219 0x0A)

Worst over ratios -1, -0.5, 0, +0.5, +1 % (frozen) or -0.5, -0.25, 0, +0.1, +0.25 % (restart at 0, inside its static-band window at code 15): pp % own / band % FS. Code c lights (2c+1)/32 of each slot.

| P | f_s | wake | code 15 | code 11 | code 7 | code 3 | code 1 | code 0 |
|---|---|---|---|---|---|---|---|---|
| 3 | 500 | restart0 | 0.04 / 1.85  | 0.06 / 2.49  | 0.07 / 3.81 FAIL | 0.07 / 8.11 FAIL | 0.30 / 18.62 FAIL | 0.44 / 53.05 FAIL |
| 3 | 500 | frozen-imm | 2.67 / 0.57  | 3.72 / 0.58 FAIL | 5.09 / 0.61 FAIL | 8.41 / 0.63 FAIL | 39.61 / 0.72 FAIL | 45.19 / 1.33 FAIL |
| 3 | 800 | restart0 | 0.01 / 1.95  | 0.05 / 2.60  | 0.09 / 3.95 FAIL | 0.17 / 8.31 FAIL | 0.36 / 18.99 FAIL | 0.43 / 53.93 FAIL |
| 3 | 800 | frozen-imm | 1.68 / 0.40  | 2.08 / 0.41  | 2.80 / 0.42  | 4.93 / 0.46 FAIL | 20.52 / 0.45 FAIL | 28.27 / 0.35 FAIL |
| 3 | 1300 | restart0 | 0.03 / 2.05  | 0.06 / 2.70  | 0.05 / 4.07 FAIL | 0.20 / 8.52 FAIL | 0.37 / 19.41 FAIL | 0.45 / 54.97 FAIL |
| 3 | 1300 | frozen-imm | 1.06 / 0.22  | 1.35 / 0.30  | 1.82 / 0.33  | 3.27 / 0.25 FAIL | 16.07 / 0.29 FAIL | 17.75 / 0.32 FAIL |
| 4 | 500 | restart0 | 0.15 / 1.80  | 0.17 / 2.44  | 0.19 / 3.77 FAIL | 0.18 / 8.08 FAIL | 0.43 / 18.65 FAIL | 0.58 / 53.19 FAIL |
| 4 | 500 | frozen-imm | 4.23 / 0.69 FAIL | 5.48 / 0.70 FAIL | 8.07 / 0.67 FAIL | 24.91 / 0.67 FAIL | 53.42 / 0.67 FAIL | 60.86 / 0.73 FAIL |
| 4 | 800 | restart0 | 0.02 / 1.96  | 0.05 / 2.62  | 0.10 / 3.97 FAIL | 0.17 / 8.33 FAIL | 0.37 / 19.00 FAIL | 0.46 / 53.90 FAIL |
| 4 | 800 | frozen-imm | 2.48 / 0.33  | 2.77 / 0.34  | 4.62 / 0.47 FAIL | 12.08 / 0.46 FAIL | 28.60 / 1.20 FAIL | 35.55 / 1.29 FAIL |
| 4 | 1300 | restart0 | 0.02 / 2.08  | 0.02 / 2.74  | 0.02 / 4.11 FAIL | 0.04 / 8.57 FAIL | 0.18 / 19.47 FAIL | 0.22 / 55.07 FAIL |
| 4 | 1300 | frozen-imm | 1.55 / 0.23  | 1.69 / 0.24  | 4.09 / 0.27 FAIL | 9.37 / 0.28 FAIL | 21.59 / 0.63 FAIL | 23.86 / 0.97 FAIL |
