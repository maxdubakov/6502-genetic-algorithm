"""
6502 GA Simulator — emulates the genetic algorithm ROM using py65.

Runs two test phases:
  Phase 1: Idle mode — verifies the GA solves preset phrases and auto-cycles.
  Phase 2: Morse input — enters "WOW" via simulated morse code, then solves it.
"""

import sys
import time
from py65.devices.mpu65c02 import MPU

# ---------------------------------------------------------------------------
# Hardware addresses (match constants.inc)
# ---------------------------------------------------------------------------
PORTB = 0x6000
PORTA = 0x6001
RS    = 0x20
E     = 0x80

BTN_MORSE  = 0x01   # PA0 — morse key
BTN_CHAR   = 0x02   # PA1 — backspace
BTN_GO     = 0x04   # PA2 — confirm target
BTN_CANCEL = 0x08   # PA3 — cancel / enter input mode

# Zero-page & RAM locations used by ga.s
TARGET_BUF    = 0x0400
PHRASE_IDX_ZP = 0x1F
DIST_LO       = 0x03
DIST_HI       = 0x04
GEN_LO        = 0x06
GEN_HI        = 0x07
TARGET_POS    = 0x1B

# ---------------------------------------------------------------------------
# Morse simulation timing (in CPU steps)
# ---------------------------------------------------------------------------
DOT_HOLD      = 5_000       # short press  — press_hi ~ 3  (< threshold 48)
DASH_HOLD     = 90_000      # long press   — press_hi ~ 58 (> threshold 48)
SETTLE        = 5_000       # gap between elements
CONFIRM_WAIT  = 1_500_000   # wait for auto-confirm timeout (~1 s)
BTN_PRESS     = 100         # brief button tap


# ===== LCD capture =========================================================

class LCDCapture:
    """Intercept VIA writes to reconstruct HD44780 LCD content."""

    def __init__(self, mpu):
        self.mpu = mpu
        self.lines = ["", ""]
        self.cursor = 0
        self.last_porta = 0

    def step(self):
        porta = self.mpu.memory[PORTA]
        portb = self.mpu.memory[PORTB]

        # Detect rising edge on E (enable)
        if (porta & E) and not (self.last_porta & E):
            if porta & RS:                          # data write
                ch = chr(portb) if 0x20 <= portb <= 0x7E else "?"
                if self.cursor < 16:
                    self.lines[0] += ch
                elif 64 <= self.cursor < 80:
                    self.lines[1] += ch
                self.cursor += 1
            else:                                   # command
                if portb == 0x01:                   # clear display
                    self.lines = ["", ""]
                    self.cursor = 0
                elif portb & 0x80:                  # set DDRAM address
                    self.cursor = portb & 0x7F

        self.last_porta = porta

    def display(self):
        return self.lines[0].ljust(16)[:16], self.lines[1].ljust(16)[:16]


# ===== ROM helpers =========================================================

def load_rom(mpu, path):
    """Load a binary ROM image at $8000."""
    with open(path, "rb") as f:
        data = f.read()
    for i, byte in enumerate(data):
        mpu.memory[0x8000 + i] = byte


def patch_delay(mpu):
    """Replace delay / lcd_wait / debounce with RTS so emulation is fast."""

    def _find_and_patch(signature, patch_bytes):
        for addr in range(0x8000, 0xFFF0):
            if all(mpu.memory[addr + i] == b for i, b in enumerate(signature)):
                for i, b in enumerate(patch_bytes):
                    mpu.memory[addr + i] = b
                return addr
        return None

    # delay:    TXA PHA TYA PHA LDX #$C8  -> RTS
    _find_and_patch([0x8A, 0x48, 0x98, 0x48, 0xA2, 0xC8], [0x60])
    # lcd_wait: PHA LDA #$00 STA $6002    -> PHA PLA RTS
    _find_and_patch([0x48, 0xA9, 0x00, 0x8D, 0x02, 0x60], [0x48, 0x68, 0x60])
    # debounce: TXA PHA TYA PHA LDX #$14  -> RTS
    _find_and_patch([0x8A, 0x48, 0x98, 0x48, 0xA2, 0x14], [0x60])


# ===== Simulation primitives ===============================================

def inject_buttons(mpu, buttons):
    """When the CPU is about to execute LDA PORTA, set button bits."""
    pc = mpu.pc
    if (mpu.memory[pc] == 0xAD and
        mpu.memory[pc + 1] == 0x01 and
        mpu.memory[pc + 2] == 0x60):
        mpu.memory[PORTA] = (mpu.memory[PORTA] & 0xF0) | (buttons & 0x0F)


def detect_tight_loop(mpu):
    """Return True if the CPU is stuck in a polling loop (waiting for input)."""
    pc = mpu.pc
    op = mpu.memory[pc]

    if (op == 0x4C and                              # JMP to self
        mpu.memory[pc + 1] == (pc & 0xFF) and
        mpu.memory[pc + 2] == ((pc >> 8) & 0xFF)):
        return True

    if op == 0xF0:                                  # BEQ backward (small loop)
        offset = mpu.memory[pc + 1]
        if offset >= 0x80:
            target = pc + 2 + (offset - 256)
            if pc - target <= 100:
                return True

    return False


def run_steps(mpu, lcd, n, buttons=0):
    """Execute *n* CPU steps with the given button state held."""
    for _ in range(n):
        inject_buttons(mpu, buttons)
        mpu.step()
        lcd.step()


def run_until_tight_loop(mpu, lcd, max_steps, buttons=0):
    """Run until a tight loop is detected.  Returns step count, or -1."""
    for i in range(max_steps):
        inject_buttons(mpu, buttons)
        if detect_tight_loop(mpu):
            return i
        mpu.step()
        lcd.step()
    return -1


def read_target_buf(mpu):
    """Read the 16-byte TARGET_BUF as a Python string."""
    return "".join(chr(mpu.memory[TARGET_BUF + i]) for i in range(16))


# ===== GA monitoring =======================================================

def run_until_solved(mpu, lcd, max_cycles, label=""):
    """Run the GA until fitness distance reaches zero.

    Checks every 1 000 steps.  Prints progress every 100 generations.
    Returns (generation, cycles) or (-1, cycles) on timeout.
    """
    cycles = 0
    last_gen = -1
    while cycles < max_cycles:
        inject_buttons(mpu, 0)
        mpu.step()
        lcd.step()
        cycles += 1

        if cycles % 1000 == 0:
            dist = mpu.memory[DIST_HI] * 256 + mpu.memory[DIST_LO]
            gen  = mpu.memory[GEN_HI]  * 256 + mpu.memory[GEN_LO]
            if dist == 0 and gen > 0:
                l1, l2 = lcd.display()
                print(f"    Solved in {gen} generations ({cycles:,} cycles)")
                print(f"    LCD line 1: {l1}")
                print(f"    LCD line 2: {l2}")
                return gen, cycles
            if gen != last_gen and gen % 100 == 0 and dist != 65535:
                l1, _ = lcd.display()
                print(f"    gen {gen:>4}  dist {dist:>4}  best: {l1.rstrip()}")
            last_gen = gen

    print(f"    TIMEOUT after {cycles:,} cycles")
    return -1, cycles


# ===== Morse input helpers =================================================

def morse_element(mpu, lcd, is_dash):
    """Simulate a single dot or dash press on BTN_MORSE."""
    hold = DASH_HOLD if is_dash else DOT_HOLD
    run_steps(mpu, lcd, hold, buttons=BTN_MORSE)
    run_steps(mpu, lcd, SETTLE, buttons=0)


def enter_morse_char(mpu, lcd, elements):
    """Key in a full morse character (e.g. '.--') then wait for auto-confirm."""
    for elem in elements:
        morse_element(mpu, lcd, is_dash=(elem == "-"))
    run_steps(mpu, lcd, CONFIRM_WAIT, buttons=0)


# ===== Assertion helper ====================================================

passed = 0
failed = 0

def check(condition, message):
    """Soft assertion — logs PASS/FAIL and continues."""
    global passed, failed
    if condition:
        passed += 1
        print(f"    PASS  {message}")
    else:
        failed += 1
        print(f"  * FAIL  {message}")


# ###########################################################################
#  Phase 1 — Idle mode: GA auto-solves preset phrases and cycles between them
# ###########################################################################

def phase1(mpu, lcd):
    print()
    print("=" * 60)
    print("  Phase 1: Idle mode — auto-solve & phrase cycling")
    print("=" * 60)

    print()
    print("  The GA boots and immediately starts evolving phrase[0].")
    print("  After solving, it waits briefly, then moves to phrase[1].")
    print("  After solving all phrases it wraps back to phrase[0].")
    print()

    # --- Solve phrase[0] ---
    print("  -- Solving phrase[0] (\"It's work\") --")
    gen, _ = run_until_solved(mpu, lcd, 50_000_000)
    check(gen >= 0, "phrase[0] solved")

    # Let it auto-advance to phrase[1]
    run_steps(mpu, lcd, 200_000, buttons=0)
    phrase_idx = mpu.memory[PHRASE_IDX_ZP]
    target = read_target_buf(mpu)
    check(phrase_idx == 1, f"phrase_idx advanced to 1 (got {phrase_idx})")
    check("I love Alisa" in target, f"target is now \"{target.strip()}\"")

    # --- Solve phrase[1] ---
    print()
    print("  -- Solving phrase[1] (\"I love Alisa\") --")
    gen, _ = run_until_solved(mpu, lcd, 50_000_000)
    check(gen >= 0, "phrase[1] solved")

    # Verify wrap-around
    run_steps(mpu, lcd, 200_000, buttons=0)
    phrase_idx = mpu.memory[PHRASE_IDX_ZP]
    check(phrase_idx == 0, f"phrase_idx wrapped to 0 (got {phrase_idx})")
    print()


# ###########################################################################
#  Phase 2 — Morse input: enter "WOW" then let the GA solve it
# ###########################################################################

MORSE_TABLE = {
    "W": ".--",
    "O": "---",
}

def phase2(mpu, lcd):
    print("=" * 60)
    print("  Phase 2: Morse input — enter \"WOW\" and solve")
    print("=" * 60)

    print()
    print("  While the GA is running, press PA3 to enter input mode.")
    print("  Then key in W-O-W via morse and confirm with PA2.")
    print()

    # Enter input mode
    print("  -- Entering input mode (PA3) --")
    run_steps(mpu, lcd, 50_000, buttons=BTN_CANCEL)
    run_steps(mpu, lcd, 5_000, buttons=0)
    steps = run_until_tight_loop(mpu, lcd, 500_000)
    check(steps >= 0, f"reached input_loop after {steps} steps")

    target_pos = mpu.memory[TARGET_POS]
    check(target_pos == 0, f"target_pos is 0 (got {target_pos})")

    # Enter each letter
    word = "WOW"
    print()
    print(f"  -- Entering \"{word}\" via morse --")
    for i, letter in enumerate(word):
        code = MORSE_TABLE[letter]
        print(f"    '{letter}' = {code}")
        enter_morse_char(mpu, lcd, code)
        ch = chr(mpu.memory[TARGET_BUF + i])
        check(ch == letter, f"position {i} decoded as '{ch}'")

    target = read_target_buf(mpu)
    print(f"    buffer: \"{target.strip()}\"")

    # Confirm and run GA
    print()
    print("  -- Confirming target (PA2) --")
    run_steps(mpu, lcd, BTN_PRESS, buttons=BTN_GO)
    run_steps(mpu, lcd, 50_000, buttons=0)
    target = read_target_buf(mpu)
    check(target == "WOW             ", f"target buffer = \"{target}\"")

    print()
    print("  -- GA evolving towards \"WOW\" --")
    gen, _ = run_until_solved(mpu, lcd, 50_000_000)
    check(gen >= 0, "GA solved \"WOW\"")
    print()


# ###########################################################################
#  Main
# ###########################################################################

def main():
    t0 = time.time()

    print()
    print("  6502 Genetic Algorithm — Simulation Test")
    print("  Emulating ROM: dist/ga.out")
    print()

    mpu = MPU()
    load_rom(mpu, "dist/ga.out")
    patch_delay(mpu)
    mpu.memory[0x6004] = 0x42              # seed VIA Timer 1

    reset = mpu.memory[0xFFFC] | (mpu.memory[0xFFFD] << 8)
    mpu.pc = reset
    print(f"  Reset vector: ${reset:04X}")

    lcd = LCDCapture(mpu)

    phase1(mpu, lcd)
    phase2(mpu, lcd)

    elapsed = time.time() - t0

    # Summary
    print("=" * 60)
    total = passed + failed
    if failed == 0:
        print(f"  All {total} checks passed.  ({elapsed:.1f}s)")
    else:
        print(f"  {passed}/{total} checks passed, {failed} FAILED.  ({elapsed:.1f}s)")
    print("=" * 60)
    print()

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
