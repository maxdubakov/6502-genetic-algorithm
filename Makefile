VASM = ./vasm6502_oldstyle
VFLAGS = -Fbin -dotdir

all: ga.out buttons.out

ga.out: ga.s
	$(VASM) $(VFLAGS) $< -o $@

buttons.out: buttons.s
	$(VASM) $(VFLAGS) $< -o $@

%.out: %.s
	$(VASM) $(VFLAGS) $< -o $@

test: ga.out
	python3 test_ga.py

clean:
	rm -f *.out

.PHONY: all test clean
