## (a) Naive time-domain modulation (intensity fixed at 15)

Patterns lo+hi (levels 0..15 in every row), phases [0.03, 0.6480339887000001, 0.2660679774000001], burst 50 us per 9 words, unchanged rows skipped. pp/rms relative to each LED's own mean, worst LED; pp_abs and band in % of full scale.

| scheme | tau us | period | f_s | rms % | pp % | pp_abs %FS | band %FS | PLAN |
|---|---|---|---|---|---|---|---|---|
| BCM | 100 | 1.50 ms | 500 | 0.0 | 0.0 | 0.0 | 31.2 | FAIL |
| BCM | 100 | 1.50 ms | 800 | 0.0 | 0.1 | 0.1 | 12.3 | FAIL |
| BCM | 100 | 1.50 ms | 1300 | 84.0 | 237.5 | 81.8 | 1.0 | FAIL |
| BCM | 200 | 3.00 ms | 500 | 0.0 | 0.0 | 0.0 | 58.5 | FAIL |
| BCM | 200 | 3.00 ms | 800 | 1.7 | 4.9 | 1.3 | 6.5 | FAIL |
| BCM | 200 | 3.00 ms | 1300 | 77.4 | 219.5 | 41.0 | 0.9 | FAIL |
| BCM | 500 | 7.50 ms | 500 | 88.2 | 249.5 | 47.1 | 0.5 | FAIL |
| BCM | 500 | 7.50 ms | 800 | 0.0 | 0.1 | 0.1 | 35.7 | FAIL |
| BCM | 500 | 7.50 ms | 1300 | 50.1 | 141.7 | 32.2 | 2.5 | FAIL |
| BCM | 1000 | 15.00 ms | 500 | 87.9 | 249.5 | 35.3 | 0.4 | FAIL |
| BCM | 1000 | 15.00 ms | 800 | 1.7 | 4.9 | 3.4 | 18.1 | FAIL |
| BCM | 1000 | 15.00 ms | 1300 | 28.9 | 82.0 | 19.7 | 4.8 | FAIL |
| PWM | 100 | 1.50 ms | 500 | 0.0 | 0.0 | 0.0 | 29.8 | FAIL |
| PWM | 100 | 1.50 ms | 800 | 0.0 | 0.1 | 0.1 | 12.7 | FAIL |
| PWM | 100 | 1.50 ms | 1300 | 83.8 | 237.6 | 81.8 | 1.0 | FAIL |
| PWM | 200 | 3.00 ms | 500 | 0.0 | 0.0 | 0.0 | 42.9 | FAIL |
| PWM | 200 | 3.00 ms | 800 | 1.7 | 4.9 | 0.9 | 6.3 | FAIL |
| PWM | 200 | 3.00 ms | 1300 | 77.7 | 219.6 | 41.1 | 0.9 | FAIL |
| PWM | 500 | 7.50 ms | 500 | 88.2 | 249.5 | 47.1 | 0.5 | FAIL |
| PWM | 500 | 7.50 ms | 800 | 0.0 | 0.1 | 0.1 | 29.4 | FAIL |
| PWM | 500 | 7.50 ms | 1300 | 43.8 | 123.6 | 17.9 | 2.1 | FAIL |
| static |  |  | 500 | 0.0 | 0.0 | 0.0 | 0.0 | pass |
| static |  |  | 800 | 0.0 | 0.0 | 0.0 | 0.0 | pass |
| static |  |  | 1300 | 0.0 | 0.0 | 0.0 | 0.0 | pass |
