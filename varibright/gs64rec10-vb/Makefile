CC=avr-gcc
MCU=atmega325
CFLAGS=-g -Os -Wall -mcall-prologues -mmcu=atmega325
ALL_CFLAGS = -mmcu=$(MCU) -I. $(CFLAGS)
LDFLAGS = -Wl,-Map=$(TARGET).map,--cref	
OBJ2HEX=avr-objcopy 


####### Files:

SOURCES       = 64.c \
				button.c

OBJECTS	      = 64.o \
				button.o

TARGET=	64


####### Implicit rules

.SUFFIXES: .c .o .cpp .cc .cxx .C


.c.o:
	$(CC) -c $(CFLAGS) $(INCPATH) -o $@ $<

%.elf:	$(OBJECTS)


####### Build rules

$(TARGET):	$(OBJECTS)
		$(CC) $(CFLAGS) -o $(TARGET) $(OBJECTS)
		$(CC) $(ALL_CFLAGS) $(OBJECTS) --output $(TARGET).elf $(LDFLAGS)	
		$(OBJ2HEX) -R .eeprom -O ihex $(TARGET) $(TARGET).hex
program: $(TARGET).hex
	avarice -2 --erase --program --file $(TARGET).hex --jtag usb --jtag-bitrate 500KHz --write-fuses ff99ff

debug: $(TARGET).hex
	avarice --jtag /dev/tty.usbserial-1B1 --jtag-bitrate 500KHz localhost:8086

erase:
	avrdude -p m325 -b 115200 -P usb -c avrispmkII -e 
	#avarice --erase --jtag /dev/tty.usbserial-1B1 --jtag-bitrate 500KHz

fuses: 
	#avrdude -p m325 -b 115200 -P usb -c avrispmkII -U lfuse:w:0xff:m
	avarice -2 --write-fuses ff99ff --jtag usb --jtag-bitrate 500KHz

pro: $(TARGET).hex
	avrdude -p m325 -b 115200 -P usb -c avrispmkII -e -D -U flash:w:$(TARGET).hex:i -U lfuse:w:0xff:m -U hfuse:w:0x99:m -U efuse:w:0xff:m
	#avarice --erase --program --file $(TARGET).hex --jtag /dev/tty.usbserial-1B1 --jtag-bitrate 500KHz --write-fuses fc89ef

qpro: $(TARGET).hex
	avrdude -p m325 -b 115200 -P usb -c avrispmkII -e -V -D -U flash:w:$(TARGET).hex:i

boot: $(TARGET).hex
	avrdude -p m325 -b 115200 -P /dev/tty.usbserial-m64-0001 -c arduino -e -D -U flash:w:64.hex:i


####### Compile

64.o:		64.c
button.o:	button.c


####### Varibright mext build (64vb.c), see README-varibright.md
#  make vb    -> 64vb.elf / 64vb.hex for the real ATmega325
#  make sim   -> 64vb-sim.elf for simavr (atmega1281 core, -DSIM register shim)
#  VBFLAGS    -> compile-time options, e.g. make vb VBFLAGS="-DVB_TABLE=5 -DVB_INT_FIRST=0"
#  (rebuild with make vb-clean first when changing VBFLAGS)

VBFLAGS   =
VB_CFLAGS = -g -Os -Wall -Wextra -mcall-prologues -I. $(VBFLAGS)
VB_HDRS   = button.h types.h

.PHONY: vb sim vb-pro vb-clean

vb: 64vb.hex

64vb.elf: 64vb.c button.c $(VB_HDRS)
	$(CC) $(VB_CFLAGS) -mmcu=atmega325 -Wl,-Map=64vb.map,--cref -o $@ 64vb.c button.c
	avr-size -C --mcu=atmega325 $@

64vb.hex: 64vb.elf
	$(OBJ2HEX) -R .eeprom -O ihex $< $@

sim: 64vb-sim.elf

64vb-sim.elf: 64vb.c button.c $(VB_HDRS)
	$(CC) $(VB_CFLAGS) -mmcu=atmega1281 -DSIM -o $@ 64vb.c button.c
	avr-size $@

64vb.lst: 64vb.elf
	avr-objdump -d -S $< > $@

64vb-sim.lst: 64vb-sim.elf
	avr-objdump -d -S $< > $@

vb-pro: 64vb.hex
	avrdude -p m325 -b 115200 -P usb -c avrispmkII -e -D -U flash:w:64vb.hex:i -U lfuse:w:0xff:m -U hfuse:w:0x99:m -U efuse:w:0xff:m

vb-clean:
	rm -f 64vb.elf 64vb.hex 64vb.map 64vb.lst 64vb-sim.elf 64vb-sim.lst
