# 6502 Genetic Algorithm Computer

A genetic algorithm that evolves random text to match a target phrase, running on a homebrew 6502 computer with a 16x2 character LCD. Target phrases can be entered via morse code using a single button.

## Hardware

- **CPU**: W65C02S at 1 MHz
- **RAM**: HM62256B (32K)
- **ROM**: 28C256 (32K EEPROM)
- **I/O**: W65C22 VIA
- **Display**: HD44780-compatible 16x2 character LCD
- **Input**: 4 buttons on VIA Port A (active-high, accent accent accent accent)

### Button layout (accent accent accent accent accent accent accent accent accent accent to right)

| Button | VIA pin | Function (GA mode) | Function (input mode) |
|--------|---------|-------------------|-----------------------|
| 1 | PA0 | — | Morse input (dot/dash) |
| 2 | PA1 | — | Backspace |
| 3 | PA2 | — | Confirm target, start GA |
| 4 | PA3 | Enter input mode | Cancel, use default |

## How it works

### Genetic algorithm

The GA maintains a population of 16 individuals, each a 16-byte string of printable ASCII characters. Every generation:

1. **Fitness**: Sum of absolute differences between each character and the target (lower = better)
2. **Elitism**: Best individual copies directly to next generation
3. **Tournament selection**: Pairs of random individuals compete; fitter one becomes a parent
4. **Crossover**: Two parents combine at a random point to produce a child
5. **Mutation**: ~6% chance per character of a small random nudge (accent accent accent accent8..+7)

The LCD shows the best individual on line 1 and fitness percentage + generation count on line 2.

### Idle mode

On power-up, the computer starts solving phrases from a built-in list, cycling to the next phrase after a 30-second pause at 100%. Press PA3 at any time to enter morse input mode.

### Morse code input

Characters are entered using a single button (PA0):
- **Short press** = dot
- **Long press** (~220ms+) = dash
- Characters **auto-confirm** after ~1 second of inactivity
- **7 dots** = space
- Supports A-Z and 0-9

## Files

| File | Description |
|------|-------------|
| `ga.s` | Main program: GA + idle mode + morse input integration |
| `morse.s` | Standalone morse input test program |
| `constants.inc` | Shared hardware definitions (VIA, LCD, buttons) |
| `lcd.inc` | LCD routines (wait, instruction, print_char) |
| `morse.inc` | Morse input routines, binary tree, debounce |
| `test_ga.py` | Emulated tests using py65 (6502 emulator) |
| `Makefile` | Build and test targets |

## Building

Requires [vasm](http://sun.hasenbraten.de/vasm/) (6502 oldstyle syntax, binary output):

```sh
# Place vasm6502_oldstyle in the project root, then:
make
```

This produces `ga.out` and `morse.out` — 32K ROM images ready to flash to a 28C256 EEPROM.

## Testing

Tests run the ROM in a py65 6502 emulator, verifying the GA solves phrases and morse input works correctly:

```sh
python3 -m venv .venv
.venv/bin/pip install py65
make test
```

## Memory map

| Address | Contents |
|---------|----------|
| `$0000-$001F` | Zero-page variables |
| `$0200-$02FF` | Population (16 x 16 bytes) |
| `$0300-$03FF` | New generation buffer |
| `$0400-$040F` | Target phrase buffer |
| `$0410-$0416` | Morse display buffer |
| `$6000-$600F` | VIA (W65C22) registers |
| `$8000-$FFFF` | ROM |

## License

MIT
