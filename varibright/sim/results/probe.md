## (g) Hardware probes for the shutdown/wake behaviour (model predictions)

Row brightness (% of a stock row at intensity 15) for rows 1..8 that each wake model predicts. Different predictions mean the probe can tell the models apart by eye.

| probe | wake model | wake delay us | rows 1..8 % |
|---|---|---|---|
| P1: awake 50 us / shutdown 50 us, all on, int 15 | restart at digit 0 | 0 | 413 0 0 0 0 0 0 0 |
| P1: awake 50 us / shutdown 50 us, all on, int 15 | restart at digit 0 | 20 | 248 0 0 0 0 0 0 0 |
| P1: awake 50 us / shutdown 50 us, all on, int 15 | frozen, resume | 0 | 50 50 50 50 50 50 50 50 |
| P1: awake 50 us / shutdown 50 us, all on, int 15 | frozen, resume | 20 | 30 30 30 30 30 30 30 30 |
| P1: awake 50 us / shutdown 50 us, all on, int 15 | same digit, slot restarts | 0 | 0 0 413 0 0 0 0 0 |
| P1: awake 50 us / shutdown 50 us, all on, int 15 | same digit, slot restarts | 20 | 0 0 248 0 0 0 0 0 |
| P1: awake 50 us / shutdown 50 us, all on, int 15 | next digit | 0 | 52 52 52 52 52 52 52 52 |
| P1: awake 50 us / shutdown 50 us, all on, int 15 | next digit | 20 | 31 31 31 31 31 31 31 31 |
| P2: awake 400 us / shutdown 100 us, all on, int 15 | restart at digit 0 | 0 | 250 250 145 0 0 0 0 0 |
| P2: awake 400 us / shutdown 100 us, all on, int 15 | restart at digit 0 | 20 | 250 250 111 0 0 0 0 0 |
| P2: awake 400 us / shutdown 100 us, all on, int 15 | frozen, resume | 0 | 80 80 80 80 80 80 80 80 |
| P2: awake 400 us / shutdown 100 us, all on, int 15 | frozen, resume | 20 | 76 76 76 76 76 76 76 76 |
| P2: awake 400 us / shutdown 100 us, all on, int 15 | same digit, slot restarts | 0 | 99 62 99 62 99 62 99 62 |
| P2: awake 400 us / shutdown 100 us, all on, int 15 | same digit, slot restarts | 20 | 90 62 90 62 90 62 90 62 |
| P2: awake 400 us / shutdown 100 us, all on, int 15 | next digit | 0 | 81 81 81 81 81 81 81 81 |
| P2: awake 400 us / shutdown 100 us, all on, int 15 | next digit | 20 | 76 76 76 76 76 76 76 76 |
| P3: awake 50 us / shutdown 50 us, all on, int 0 | restart at digit 0 | 0 | 40 0 0 0 0 0 0 0 |
| P3: awake 50 us / shutdown 50 us, all on, int 0 | restart at digit 0 | 20 | 40 0 0 0 0 0 0 0 |
| P3: awake 50 us / shutdown 50 us, all on, int 0 | frozen, resume | 0 | 2 2 2 2 2 2 2 2 |
| P3: awake 50 us / shutdown 50 us, all on, int 0 | frozen, resume | 20 | 1 1 1 1 1 1 1 1 |
| P3: awake 50 us / shutdown 50 us, all on, int 0 | same digit, slot restarts | 0 | 0 0 40 0 0 0 0 0 |
| P3: awake 50 us / shutdown 50 us, all on, int 0 | same digit, slot restarts | 20 | 0 0 40 0 0 0 0 0 |
| P3: awake 50 us / shutdown 50 us, all on, int 0 | next digit | 0 | 5 5 5 5 5 5 5 5 |
| P3: awake 50 us / shutdown 50 us, all on, int 0 | next digit | 20 | 5 5 5 5 5 5 5 5 |
