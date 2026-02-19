VASM = ./vasm6502_oldstyle
VFLAGS = -Fbin -dotdir -Isrc

all: dist/ga.out dist/morse.out

dist/ga.out: src/ga.s src/constants.inc src/lcd.inc src/morse.inc
	$(VASM) $(VFLAGS) $< -o $@

dist/morse.out: src/morse.s src/constants.inc src/lcd.inc src/morse.inc
	$(VASM) $(VFLAGS) $< -o $@

test: dist/ga.out
	.venv/bin/python3 src/simulate.py

clean:
	rm -f dist/*.out

.PHONY: all test clean
