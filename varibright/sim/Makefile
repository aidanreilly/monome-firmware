# MAX7219 varibright simulation (workstream A).  Everything here is simulation.
#   make         build model library, simavr harness, harness self-test firmware
#   make test    unit tests + harness tests + quick versions of all experiments (~1-2 min)
#   make sweep   full experiments, results in results/*.md (~7 min on 2 cores)
CC      ?= gcc
CFLAGS  ?= -O2 -Wall -Wextra -Wno-unused-parameter
AVRCC   ?= avr-gcc
PY      ?= python3
JOBS    ?= $(shell nproc 2>/dev/null || echo 2)
B       := build

LIBMONOME ?= ../../libmonome
FWDIR   ?= ../gs64rec10-vb
FW      := $(FWDIR)/64vb-sim.elf
LM_SRC  := $(LIBMONOME)/src/libmonome.c $(LIBMONOME)/src/proto/mext.c $(LIBMONOME)/src/rotation.c
LM_INC  := -I$(LIBMONOME)/public -I$(LIBMONOME)/src/private -I$(LIBMONOME)/src/proto -Iharness

all: $(B)/libmax7219.so $(B)/gs64sim $(B)/api_test $(B)/libgs64sim.a $(B)/testfw.elf $(B)/e2e_libmonome $(B)/64vb-sim-txe.elf $(FW)

$(B):
	mkdir -p $(B)

$(B)/libmax7219.so: max7219.c | $(B)
	$(CC) -O2 -shared -fPIC -o $@ $< -lm

$(B)/gs64sim.o: harness/gs64sim.c harness/gs64sim.h | $(B)
	$(CC) $(CFLAGS) -c -o $@ $<

$(B)/libgs64sim.a: $(B)/gs64sim.o
	ar rcs $@ $^

$(B)/gs64sim: harness/main.c $(B)/libgs64sim.a
	$(CC) $(CFLAGS) -Iharness -o $@ $^ -lsimavr -lm

$(B)/api_test: harness/api_test.c $(B)/libgs64sim.a
	$(CC) $(CFLAGS) -Iharness -o $@ $^ -lsimavr -lm

# libmonome's own sources (unchanged) + stub platform + harness + MAX7219 model
$(B)/e2e_libmonome: tests/e2e_libmonome.c tests/monome_stub.c max7219.c $(B)/libgs64sim.a $(LM_SRC)
	$(CC) -O2 -w $(LM_INC) -o $@ tests/e2e_libmonome.c tests/monome_stub.c $(LM_SRC) $(B)/libgs64sim.a -lsimavr -lm

$(FW): $(FWDIR)/64vb.c $(FWDIR)/button.c
	$(MAKE) -C $(FWDIR) sim

# same firmware with -DVB_USE_TXE=1 (output-buffer test only)
$(B)/64vb-sim-txe.elf: $(FWDIR)/64vb.c $(FWDIR)/button.c | $(B)
	$(AVRCC) -g -Os -Wall -Wextra -mcall-prologues -I$(FWDIR) -mmcu=atmega1281 -DSIM -DVB_USE_TXE=1 -o $@ $(FWDIR)/64vb.c $(FWDIR)/button.c

$(B)/testfw.elf: testfw/testfw.c | $(B)
	$(AVRCC) -mmcu=atmega1281 -Os -Wall -o $@ $<

test: all
	$(PY) tests/test_model.py
	$(B)/api_test $(B)/testfw.elf
	$(PY) tests/test_harness.py $(B)
	$(PY) experiments.py --quick --jobs $(JOBS) --out results/quick all > results/quick.log 2>&1 || (cat results/quick.log; exit 1)
	@echo "== step 3a: libmonome end to end (T-SD, SD, mono) against $(FW)"
	$(B)/e2e_libmonome $(FW) tsd > results/quick/e2e_tsd.log 2>&1 || (cat results/quick/e2e_tsd.log; exit 1)
	$(B)/e2e_libmonome $(FW) sd > results/quick/e2e_sd.log 2>&1 || (cat results/quick/e2e_sd.log; exit 1)
	$(B)/e2e_libmonome $(FW) mono > results/quick/e2e_mono.log 2>&1 || (cat results/quick/e2e_mono.log; exit 1)
	@tail -n1 results/quick/e2e_tsd.log results/quick/e2e_sd.log results/quick/e2e_mono.log
	@echo "== step 3b..e: firmware integration tests (quick)"
	$(PY) tests/test_fw.py --quick --jobs $(JOBS) --out results/quick/fw_tests.md > results/quick/fw_tests.log 2>&1 || (cat results/quick/fw_tests.log; exit 1)
	@tail -n1 results/quick/fw_tests.log
	@echo "quick experiment tables in results/quick/*.md"
	@echo "ALL TESTS PASSED"

# full firmware test run (all f_s), tables in results/fw_tests.md and results/e2e_*.log
fwtest: all
	$(B)/e2e_libmonome $(FW) tsd > results/e2e_tsd.log 2>&1; tail -n1 results/e2e_tsd.log
	$(B)/e2e_libmonome $(FW) sd > results/e2e_sd.log 2>&1; tail -n1 results/e2e_sd.log
	$(B)/e2e_libmonome $(FW) mono > results/e2e_mono.log 2>&1; tail -n1 results/e2e_mono.log
	$(B)/e2e_libmonome $(FW) tsd 500 > results/e2e_tsd_500.log 2>&1; tail -n1 results/e2e_tsd_500.log
	$(B)/e2e_libmonome $(FW) sd 1300 > results/e2e_sd_1300.log 2>&1; tail -n1 results/e2e_sd_1300.log
	$(PY) tests/test_fw.py --jobs $(JOBS) --out results/fw_tests.md 2>&1 | tee results/fw_tests.log | tail -n1

sweep: all
	$(PY) experiments.py --jobs $(JOBS) all 2>&1 | tee results/full.log

clean:
	rm -rf $(B) __pycache__ tests/__pycache__ results/quick results/quick.log

.PHONY: all test sweep clean fwtest
