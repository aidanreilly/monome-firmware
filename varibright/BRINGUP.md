# gs64rec10 varibright: hardware bring-up checklist

Nothing in this repository has run on hardware. Work through the steps in order and stop at
the first one that misbehaves. Steps 1 to 3 change nothing permanent.

Tools on Fedora: `sudo dnf install avrdude python3-pyserial`, plus `ftdi_eeprom` (libftdi)
for step 5. Programmer: AVRISP mkII on the logic board's ISP header. The programmer does not
power the board, so the grid's USB cable must be plugged in as well.

## 1. Connection test (reads only)

```
avrdude -c avrispmkII -P usb -p m325 -v
```

Expect the ATmega325 signature `1E 95 05`. A permission error means a missing udev rule; run
with `sudo` or add a rule for USB id 03eb:2104.

## 2. Back up the unit

```
avrdude -c avrispmkII -P usb -p m325 \
  -U flash:r:gs64-flash-backup.hex:i \
  -U eeprom:r:gs64-eeprom-backup.hex:i \
  -U lfuse:r:-:h -U hfuse:r:-:h -U efuse:r:-:h
```

Write down the three fuse values. The stock Makefile expects `0xff 0x99 0xff`. If yours
differ, stop and compare before flashing, because `make vb-pro` rewrites them to those values.

## 3. Note the FTDI serial

```
udevadm info -q property -n /dev/ttyUSB0 | grep ID_SERIAL_SHORT
```

Expect something like `m64-0123`. Keep it; restoring it is how you return to stock behaviour.

## 4. Flash

```
cd gs64rec10-vb
make vb-pro          # or: avrdude -c avrispmkII -P usb -p m325 -e -U flash:w:64vb.hex:i
```

The unit should play its start-up animation and then sit dark. Restore at any time with
`avrdude ... -e -U flash:w:gs64-flash-backup.hex:i`.

## 5. Mono check over direct serial (serialosc stopped)

```
systemctl --user stop serialosc 2>/dev/null; pkill serialoscd
tools/gridtest.py info       # handshake OK, varibright off, no calibration stored
tools/gridtest.py mono       # all on, chase, rows, columns, triangle
tools/gridtest.py keys       # press all 64 keys
```

Check that the LED chase runs left to right and top to bottom, and that each key lights the
LED under it. A mirrored or rotated picture is a coordinate bug to report, with which of the
two (LEDs or keys) is wrong.

## 6. Probe the MAX7219 wake behaviour

This decides which brightness mode suits the chip. Probe 1 runs at the lowest intensity and
must come first.

```
tools/gridtest.py vb probe 1
```

All LEDs alternate between a 1 s reference and a 1 s probe phase. Read the probe phase:

| Probe 1 shows | Meaning | Do next |
|---|---|---|
| All rows lit, slightly dimmer than the reference | Scan resumes after shutdown ("frozen") | Keep the default T-SD mode. Run probes 2, 3 and 4 |
| One line of LEDs at an edge bright, the rest dark | Scan restarts at the first digit | Skip probes 2 and 3 (they would overdrive that line). The 16-level SD mode is the better choice |
| One line elsewhere bright, the rest dark | Scan restarts the interrupted digit | Skip probes 2 and 3. Both modes fail in simulation; stay in mono and report |
| All rows lit, slightly brighter than the reference | Scan skips to the next digit | Both modes fail in simulation; stay in mono and report |

Probe 4 (`vb probe 4`) shows all LEDs at a middle step, 2 s at the set period and 2 s detuned
by 0.5 %. It is only meaningful after step 7. Steady in both phases is the good result.
Flicker in the detuned phase means the chip holds its latched data across the wake, and then
only an exact calibration works.

Photos or a phone video of each probe are worth keeping. A phone camera in slow-motion mode
shows flicker the eye misses.

## 7. Calibrate the frame period

```
tools/gridtest.py vb nudge
```

A band of lit rows rolls across the grid. Type `-100`, `-10`, `-1`, `+1`, `+10`, `+100` until
it stands still, then `r` to preview a brightness ramp, `b` to return to the band, `s` to
save. Calibrate after the unit has been on for a few minutes. If the band never rolls at any
period, the chip restarts its scan on wake (see step 6).

The same procedure works without a computer: hold the top-left key while plugging in, then
use the key map in `gs64rec10-vb/README-varibright.md` section 4.

Write down the saved period (`tools/gridtest.py vb get`). A reflash with chip erase clears it.

## 8. Brightness check

```
tools/gridtest.py levels
tools/gridtest.py vb set --mode sd      # try the 16-level mode
tools/gridtest.py levels
tools/gridtest.py vb set --mode tsd --save
```

Things to look for, in a dim room and with the grid in the corner of your eye, where flicker
is most visible: shimmer, a slowly rolling band, one row brighter or dimmer than the rest,
flicker that appears as the unit warms up. Note which mode and which levels show it.

## 9. serialosc

Rewrite the FTDI serial to `m` + digits (for example `m0000064`) as described in
`gs64rec10-vb/README-varibright.md` section 3, after `ftdi_eeprom --read-eeprom` as a backup.
Replug, start serialosc, then:

```
tools/gridtest.py osc list       # the unit should appear
tools/gridtest.py osc levels     # smooth ramps = serialosc drives it as varibright
tools/gridtest.py osc keys
```

A hard on/off split in `osc levels` means serialosc opened the unit with the series protocol
(serial string still `m64-...`) or the unit is uncalibrated.

## What to report back

1. Fuse values and the original FTDI serial.
2. Probe 1 result, and probes 2 to 4 if run.
3. The calibrated period, and whether it needs retuning warm versus cold.
4. Which mode looks clean, and anything seen in step 8.
5. Whether `osc levels` shows ramps.
