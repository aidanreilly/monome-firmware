## Host level -> step mapping

step(L) = 0 for L = 0, else max(1, round(L P / 15)). It is the minimax-optimal monotonic map to a linear ramp with 0 -> off, 15 -> full and every nonzero level lit; max err = worst |step/P - L/15| in % of full scale. The last column counts host levels per step 0..P.

| P | steps for host levels 0..15 | max err % FS | levels per step |
|---|---|---|---|
| 3 | 0 1 1 1 1 1 1 1 2 2 2 2 2 3 3 3 | 26.7 | 1 7 5 3 |
| 4 | 0 1 1 1 1 1 2 2 2 2 3 3 3 3 4 4 | 18.3 | 1 5 4 4 2 |
| 5 | 0 1 1 1 1 2 2 2 3 3 3 4 4 4 5 5 | 13.3 | 1 4 3 3 3 2 |
| 6 | 0 1 1 1 2 2 2 3 3 4 4 4 5 5 6 6 | 10.0 | 1 3 3 2 3 2 2 |
