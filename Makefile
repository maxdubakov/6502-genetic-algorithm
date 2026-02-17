VASM = ./vasm6502_oldstyle
VFLAGS = -Fbin -dotdir

all: ga.out morse.out

ga.out: ga.s constants.inc lcd.inc morse.inc
	$(VASM) $(VFLAGS) $< -o $@

morse.out: morse.s constants.inc lcd.inc morse.inc
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
