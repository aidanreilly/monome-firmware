/*
 * libmonome platform layer stub wired to the gs64sim harness (simulation only).
 *
 * Replaces src/platform/{posix,linux}.c: libmonome's own libmonome.c, proto/mext.c and
 * rotation.c are compiled unchanged on top of it.  The FTDI serial string that the real
 * platform reads from the USB device comes from stub_serial, so the protocol selection
 * in libmonome's devices.h runs for real.
 *
 *   monome_platform_write          -> gs64sim_host_write (FT245 receive FIFO)
 *   monome_platform_wait_for_input -> run the simulation until a device byte is pending
 *   monome_platform_read           -> gs64sim_host_read, with posix.c's semantics
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <monome.h>
#include "internal.h"
#include "platform.h"
#include "gs64sim.h"

gs64sim_t *stub_sim;
const char *stub_serial = "m0000064";
unsigned long stub_bytes_written;
unsigned long stub_queries_sent;      /* 0x00 bytes written at the start of a message */

#ifndef STUB_LATENCY_US
#define STUB_LATENCY_US 16000.0
#endif

monome_t *monome_protocol_new(void);   /* proto/mext.c (built without EMBED_PROTOS) */

char *monome_platform_get_dev_serial(const char *device)
{
	(void)device;
	return strdup(stub_serial);
}

monome_t *monome_platform_load_protocol(const char *proto)
{
	if (strcmp(proto, "mext")) {
		fprintf(stderr, "stub: libmonome asked for protocol '%s', only mext is linked\n", proto);
		return NULL;
	}
	return monome_protocol_new();
}

void monome_platform_free(monome_t *monome)
{
	monome->free(monome);
}

int monome_platform_open(monome_t *monome, const monome_devmap_t *m, const char *dev)
{
	(void)m; (void)dev;
	monome->fd = -1;
	return 0;
}

int monome_platform_close(monome_t *monome)
{
	(void)monome;
	return 0;
}

ssize_t monome_platform_write(monome_t *monome, const uint8_t *buf, size_t nbyte)
{
	(void)monome;
	if (nbyte && buf[0] == 0x00)
		stub_queries_sent++;
	if (getenv("STUB_DEBUG")) { fprintf(stderr, "W"); for (size_t i = 0; i < nbyte; i++) fprintf(stderr, " %02x", buf[i]); fprintf(stderr, " @%.0f us\n", gs64sim_time_us(stub_sim)); }
	gs64sim_host_write(stub_sim, buf, nbyte);
	stub_bytes_written += nbyte;
	return (ssize_t)nbyte;
}

/* 0 = input available, 1 = timeout (as linux.c) */
int monome_platform_wait_for_input(monome_t *monome, uint_t msec)
{
	(void)monome;
	if (!msec)
		return 0;
	if (gs64sim_tx_pending(stub_sim))
		return 0;
	if (!gs64sim_run_until_tx(stub_sim, 1, msec * 1000.0))
		return 1;
	/* FT245 -> USB: the FTDI chip sends a packet when 62 bytes are buffered or its
	   latency timer (16 ms default) expires, so the host sees a burst, not single bytes */
	gs64sim_run_until_tx(stub_sim, 62, STUB_LATENCY_US);
	return 0;
}

/* posix.c: one non-blocking read, then wait up to 25 ms for each further chunk */
ssize_t monome_platform_read(monome_t *monome, uint8_t *buf, size_t nbyte)
{
	size_t got = gs64sim_host_read(stub_sim, buf, nbyte);
	while (got && got < nbyte) {
		if (monome_platform_wait_for_input(monome, 25) > 0)
			return (ssize_t)got;
		got += gs64sim_host_read(stub_sim, buf + got, nbyte - got);
	}
	if (getenv("STUB_DEBUG")) { fprintf(stderr, "R%zu/%zu", got, nbyte); for (size_t i = 0; i < got; i++) fprintf(stderr, " %02x", buf[i]); fprintf(stderr, "\n"); }
	return (ssize_t)got;
}

void *m_malloc(size_t size) { return malloc(size); }
void *m_calloc(size_t nmemb, size_t size) { return calloc(nmemb, size); }
void *m_strdup(const char *s) { return strdup(s); }
void m_free(void *ptr) { free(ptr); }
void m_sleep(uint_t msec) { gs64sim_run_us(stub_sim, msec * 1000.0); }
