/*
 * Harness self-test firmware (NOT the gs64 firmware).  Build: avr-gcc -mmcu=atmega1281.
 * - bit-bangs MAX7219 init words on PORTE (E0 CLK, E1 LOAD, E2 DIN)
 * - Timer1 CTC ISR every 1.25 ms writes the intensity register (0x0A, count & 15)
 * - echoes every FT245 byte back; byte 0xEE instead returns EEPROM bytes 0..4
 * - scans the keypad like 64.c and reports changes as 0x21/0x20, col, row
 * - increments EEPROM byte 4 (boot counter) at start; shows EEPROM byte 0 on digit 1
 */
#define F_CPU 16000000UL
#include <avr/io.h>
#include <avr/eeprom.h>
#include <avr/interrupt.h>
#include <util/delay.h>

#define E0_CLK 0x01
#define E1_LD 0x02
#define E2_DIN 0x04
#define E3_KCLK 0x08
#define E4_KLD 0x10
#define E5_KDAT 0x20
#define C1_RXF 0x02
#define C2_WR 0x04
#define C3_RD 0x08

static void max_write(uint8_t a, uint8_t d)
{
	uint16_t w = ((uint16_t)a << 8) | d;
	PORTE &= ~E1_LD;
	for (uint8_t i = 0; i < 16; i++) {
		if (w & 0x8000) PORTE |= E2_DIN; else PORTE &= ~E2_DIN;
		PORTE |= E0_CLK;
		PORTE &= ~E0_CLK;
		w <<= 1;
	}
	PORTE |= E1_LD;
}

static void tx(uint8_t b)
{
	DDRD = 0xFF;
	PORTC |= C2_WR;
	PORTD = b;
	PORTC &= ~C2_WR;
	DDRD = 0;
	PORTD = 0;
}

static volatile uint8_t tick;

ISR(TIMER1_COMPA_vect)
{
	max_write(0x0A, tick++ & 15);
}

int main(void)
{
	uint8_t keys[8] = {0};
	DDRE = (uint8_t)~E5_KDAT;
	DDRB = 0x70;
	DDRC = C2_WR | C3_RD;
	PORTC = C3_RD;
	DDRD = 0;
	PORTE = 0;

	uint8_t boots = eeprom_read_byte((uint8_t *)4);
	eeprom_write_byte((uint8_t *)4, boots + 1);

	max_write(0x0B, 7);
	max_write(0x0A, 15);
	max_write(0x09, 0);
	max_write(1, eeprom_read_byte((uint8_t *)0));
	for (uint8_t i = 2; i <= 8; i++)
		max_write(i, 1 << (i - 1));
	max_write(0x0C, 1);
	max_write(0x0F, 0);

	TCCR1A = 0;
	TCCR1B = (1 << WGM12) | (1 << CS10);   /* CTC, clk/1 */
	OCR1A = 20000 - 1;                     /* 1.25 ms */
	TIMSK1 = (1 << OCIE1A);
	sei();

	for (;;) {
		while ((PINC & C1_RXF) == 0) {
			PORTC &= ~C3_RD;
			_delay_us(1);
			uint8_t b = PIND;
			PORTC |= C3_RD;
			_delay_us(1);
			if (b == 0xEE) {
				for (uint8_t i = 0; i < 5; i++)
					tx(eeprom_read_byte((uint8_t *)(uint16_t)i));
			} else {
				tx(b);
			}
		}
		for (uint8_t row = 0; row < 8; row++) {
			PORTB = row << 4;
			_delay_us(20);
			PORTE |= E4_KLD;
			_delay_us(1);
			for (uint8_t col = 0; col < 8; col++) {
				uint8_t down = (PINE & E5_KDAT) == 0;
				uint8_t was = (keys[row] >> col) & 1;
				if (down != was) {
					keys[row] ^= 1 << col;
					tx(down ? 0x21 : 0x20);
					tx(col);
					tx(row);
				}
				PORTE |= E3_KCLK;
				_delay_us(1);
				PORTE &= ~E3_KCLK;
				_delay_us(1);
			}
			PORTE &= ~E4_KLD;
		}
	}
}
