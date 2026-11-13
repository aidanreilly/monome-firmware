# gs64meter

Measure the gs64rec10 varibright display through its own supply ripple, with no test equipment.

The firmware's `0x0C` extension streams ADC readings of the ATmega325's internal 1.1 V bandgap against AREF.
Every MAX7219 digit slot with lit LEDs dips the supply, so the scan shows up as pulses.
These tools turn that into a scan rate, scan creep (how fast the scan slides through the frames) and scan position.

## Prerequisites

- Python 3 with `numpy` and `pyserial`.
- The grid on `/dev/ttyUSB0`, running a `64vb.c` build with the `0x0C` capture.
- serialosc stopped, so it does not hold the port: `systemctl --user stop serialosc`.

## Getting started

```
$ python3 gs64meter.py fs --cols 1
scan rate 885.415 Hz with 1 columns lit
$ python3 gs64meter.py creep 18750 0x30 1
period 18750 cfg 0x30: {'creep': 6.25e-07, 'jumps': 0, 'steps': 1413}  steady=True
```

`steady=True` means creep within ±0.0005 frames per cycle and no wrap-arounds.
That's the pass bar for a flicker-free display.

`gs64meter.py sweep START STOP STEP CFG LEVEL` measures creep across periods and prints the zero crossing.

## Tests

The parsing and analysis code has offline tests with synthetic signals:

```
$ python3 -m unittest discover -s tests -v
```

## Notes

- `creep` with no wraps fits one line through every cycle position over the capture (about 7 s), so its resolution is far below the ±0.0005 bound.
- The board filters each pulse into a bipolar response about 500 µs long. Averaged (DC) readings barely move with light, so don't try to read brightness from a low-passed signal.
