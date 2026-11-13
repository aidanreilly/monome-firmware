## (b) FLIP at exactly calibrated rate, table 15/7/3/1

12 scan phases, patterns lo+hi (all 16 levels in every row), burst 50 us. 'level err' = worst LED mean error relative to its own commanded level; 'gain' = global brightness factor (shutdown dark time).

| variant | effect | f_s | rms % | pp % | band %FS | level err % | gain % | PLAN | strict |
|---|---|---|---|---|---|---|---|---|---|
| FLIP/int_first | imm | 500 | 0.04 | 0.11 | 22.7 | 187.5 | 98.8 | FAIL | fail |
| FLIP/int_first | imm | 800 | 0.00 | 0.01 | 36.4 | 303.4 | 98.9 | FAIL | fail |
| FLIP/int_first | imm | 1300 | 0.07 | 0.21 | 57.6 | 479.6 | 98.5 | FAIL | fail |
| FLIP/int_first | lat | 500 | 0.04 | 0.11 | 101.8 | 848.1 | 97.2 | FAIL | fail |
| FLIP/int_first | lat | 800 | 0.00 | 0.01 | 102.8 | 856.8 | 97.7 | FAIL | fail |
| FLIP/int_first | lat | 1300 | 0.07 | 0.20 | 102.4 | 853.4 | 97.5 | FAIL | fail |
| FLIP/int_mid | imm | 500 | 0.04 | 0.11 | 11.4 | 93.6 | 99.1 | FAIL | fail |
| FLIP/int_mid | imm | 800 | 0.00 | 0.01 | 18.2 | 151.7 | 99.3 | FAIL | fail |
| FLIP/int_mid | imm | 1300 | 0.07 | 0.20 | 28.6 | 238.7 | 98.8 | FAIL | fail |
| FLIP/int_mid | lat | 500 | 0.04 | 0.11 | 0.6 | 1.0 | 99.5 | pass | pass |
| FLIP/int_mid | lat | 800 | 0.00 | 0.01 | 86.0 | 104.7 | 96.0 | FAIL | fail |
| FLIP/int_mid | lat | 1300 | 0.07 | 0.20 | 102.4 | 853.4 | 95.8 | FAIL | fail |
| FLIP/int_last | imm | 500 | 0.04 | 0.11 | 21.4 | 91.2 | 98.7 | FAIL | fail |
| FLIP/int_last | imm | 800 | 0.00 | 0.01 | 31.0 | 126.5 | 98.7 | FAIL | fail |
| FLIP/int_last | imm | 1300 | 0.07 | 0.20 | 49.0 | 127.0 | 97.7 | FAIL | fail |
| FLIP/int_last | lat | 500 | 0.04 | 0.12 | 86.0 | 104.7 | 95.6 | FAIL | fail |
| FLIP/int_last | lat | 800 | 0.00 | 0.01 | 86.0 | 104.7 | 96.0 | FAIL | fail |
| FLIP/int_last | lat | 1300 | 0.07 | 0.20 | 86.0 | 104.7 | 95.8 | FAIL | fail |
| SD/frozen | imm | 500 | 0.05 | 0.18 | 0.4 | 0.7 | 97.2 | pass | pass |
| SD/frozen | imm | 800 | 0.04 | 0.13 | 0.2 | 0.5 | 95.8 | pass | pass |
| SD/frozen | imm | 1300 | 0.05 | 0.18 | 0.2 | 0.4 | 93.2 | pass | pass |
| SD/frozen | lat | 500 | 0.05 | 0.18 | 0.4 | 0.7 | 97.2 | pass | pass |
| SD/frozen | lat | 800 | 0.04 | 0.13 | 0.2 | 0.5 | 95.8 | pass | pass |
| SD/frozen | lat | 1300 | 0.05 | 0.18 | 0.2 | 0.4 | 93.2 | pass | pass |
| SD/restart0 | imm | 500 | 0.05 | 0.19 | 0.4 | 0.7 | 97.2 | pass | pass |
| SD/restart0 | imm | 800 | 0.04 | 0.13 | 0.2 | 0.5 | 95.8 | pass | pass |
| SD/restart0 | imm | 1300 | 0.05 | 0.18 | 0.2 | 0.4 | 93.2 | pass | pass |
| SD/restart0 | lat | 500 | 0.05 | 0.19 | 0.4 | 0.7 | 97.2 | pass | pass |
| SD/restart0 | lat | 800 | 0.04 | 0.13 | 0.2 | 0.5 | 95.8 | pass | pass |
| SD/restart0 | lat | 1300 | 0.05 | 0.18 | 0.2 | 0.4 | 93.2 | pass | pass |
