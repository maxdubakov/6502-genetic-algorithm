"""Full GA test - idle phrase cycling + morse input mode."""

from py65.devices.mpu65c02 import MPU

PORTB = 0x6000
PORTA = 0x6001
RS = 0x20
E = 0x80

# Button masks (match constants.inc)
BTN_MORSE  = 0x01  # PA0
BTN_CHAR   = 0x02  # PA1
BTN_GO     = 0x04  # PA2
BTN_CANCEL = 0x08  # PA3

TARGET_BUF = 0x0400
PHRASE_IDX_ZP = 0x1F


class LCDCapture:
    """Intercept VIA writes to capture LCD output."""

    def __init__(self, mpu):
        self.mpu = mpu
        self.lines = ["", ""]
        self.cursor = 0
        self.last_portb = 0
        self.last_porta = 0

    def step(self):
        porta = self.mpu.memory[PORTA]
        portb = self.mpu.memory[PORTB]

        if (porta & E) and not (self.last_porta & E):
            if porta & RS:
                ch = chr(portb) if 0x20 <= portb <= 0x7E else "?"
                if self.cursor < 16:
                    self.lines[0] += ch
                elif self.cursor >= 64 and self.cursor < 80:
                    self.lines[1] += ch
                self.cursor += 1
            else:
                if portb == 0x01:
                    self.lines = ["", ""]
                    self.cursor = 0
                elif portb & 0x80:
                    self.cursor = portb & 0x7F

        self.last_porta = porta
        self.last_portb = portb

    def display(self):
        l1 = self.lines[0].ljust(16)[:16]
        l2 = self.lines[1].ljust(16)[:16]
        return l1, l2


def load_rom(mpu, path):
    with open(path, "rb") as f:
        data = f.read()
    for i, byte in enumerate(data):
        mpu.memory[0x8000 + i] = byte


def patch_delay(mpu):
    """Patch delay, lcd_wait, and debounce to RTS for fast emulation."""
    # Patch delay: TXA/PHA/TYA/PHA/LDX #200 ($C8)
    for addr in range(0x8000, 0xFFF0):
        if (mpu.memory[addr] == 0x8A and mpu.memory[addr+1] == 0x48 and
            mpu.memory[addr+2] == 0x98 and mpu.memory[addr+3] == 0x48 and
            mpu.memory[addr+4] == 0xA2 and mpu.memory[addr+5] == 0xC8):
            mpu.memory[addr] = 0x60
            break

    # Patch lcd_wait: PHA/LDA #$00/STA $6002
    for addr in range(0x8000, 0xFFF0):
        if (mpu.memory[addr] == 0x48 and mpu.memory[addr+1] == 0xA9 and
            mpu.memory[addr+2] == 0x00 and mpu.memory[addr+3] == 0x8D and
            mpu.memory[addr+4] == 0x02 and mpu.memory[addr+5] == 0x60):
            mpu.memory[addr] = 0x48      # PHA
            mpu.memory[addr + 1] = 0x68  # PLA
            mpu.memory[addr + 2] = 0x60  # RTS
            break

    # Patch debounce: TXA/PHA/TYA/PHA/LDX #20 ($14)
    for addr in range(0x8000, 0xFFF0):
        if (mpu.memory[addr] == 0x8A and mpu.memory[addr+1] == 0x48 and
            mpu.memory[addr+2] == 0x98 and mpu.memory[addr+3] == 0x48 and
            mpu.memory[addr+4] == 0xA2 and mpu.memory[addr+5] == 0x14):
            mpu.memory[addr] = 0x60
            break


def inject_buttons(mpu, buttons):
    """If next instruction is LDA PORTA, inject button state into low bits."""
    pc = mpu.pc
    if (mpu.memory[pc] == 0xAD and
        mpu.memory[pc+1] == 0x01 and
        mpu.memory[pc+2] == 0x60):
        mpu.memory[PORTA] = (mpu.memory[PORTA] & 0xF0) | (buttons & 0x0F)


def detect_tight_loop(mpu):
    """Detect JMP-to-self or BEQ-backward small loop."""
    pc = mpu.pc
    op = mpu.memory[pc]

    # JMP to self
    if (op == 0x4C and
        mpu.memory[pc + 1] == (pc & 0xFF) and
        mpu.memory[pc + 2] == ((pc >> 8) & 0xFF)):
        return True

    # BEQ backward small loop (e.g. input_loop)
    if op == 0xF0:
        offset = mpu.memory[pc + 1]
        if offset >= 0x80:
            target = pc + 2 + (offset - 256)
            if pc - target <= 100:
                return True

    return False


def run_steps(mpu, lcd, n, buttons=0):
    """Run n steps with given button state, injecting buttons on PORTA reads."""
    for _ in range(n):
        inject_buttons(mpu, buttons)
        mpu.step()
        lcd.step()


def run_until_tight_loop(mpu, lcd, max_steps, buttons=0):
    """Run until tight loop detected, returns steps taken or -1 if max reached."""
    for i in range(max_steps):
        inject_buttons(mpu, buttons)
        if detect_tight_loop(mpu):
            return i
        mpu.step()
        lcd.step()
    return -1


def read_target_buf(mpu):
    """Read TARGET_BUF as a string."""
    return ''.join(chr(mpu.memory[TARGET_BUF + i]) for i in range(16))


def run_until_solved(mpu, lcd, max_cycles, label=""):
    """Run GA until dist==0, checking every step. Returns (gen, cycles)."""
    cycles = 0
    last_gen = -1
    while cycles < max_cycles:
        inject_buttons(mpu, 0)
        mpu.step()
        lcd.step()
        cycles += 1

        # Check dist every 1000 steps (fast, just two memory reads)
        if cycles % 1000 == 0:
            dist = mpu.memory[0x04] * 256 + mpu.memory[0x03]
            gen = mpu.memory[0x07] * 256 + mpu.memory[0x06]
            if dist == 0 and gen > 0:
                l1, l2 = lcd.display()
                print(f"  {label}SOLVED in {gen} generations, {cycles:,} cycles")
                print(f"  {label}LCD: \"{l1}\" / \"{l2}\"")
                return gen, cycles
            # Verbose progress logging (less frequent)
            if gen != last_gen and gen % 100 == 0:
                l1, l2 = lcd.display()
                print(f"  {label}Gen {gen:4d} | dist={dist:3d} | LCD: \"{l1}\" / \"{l2}\"")
            last_gen = gen

    print(f"  {label}Timeout at {cycles:,} cycles")
    return -1, cycles


# --- Timing constants for morse simulation ---
DOT_HOLD      = 5000      # press_hi ~ 3 (well below threshold of 48)
DASH_HOLD     = 90000     # press_hi ~ 58 (above threshold of 48)
SETTLE        = 5000      # steps between elements (must NOT trigger auto-confirm)
CONFIRM_WAIT  = 1_500_000 # steps to wait for auto-confirm timeout (~1s worth of loop iterations)
BTN_PRESS     = 100       # steps to hold a non-timing button


def morse_element(mpu, lcd, is_dash):
    """Simulate one dot or dash press on BTN_MORSE."""
    hold = DASH_HOLD if is_dash else DOT_HOLD
    run_steps(mpu, lcd, hold, buttons=BTN_MORSE)
    run_steps(mpu, lcd, SETTLE, buttons=0)


def enter_morse_char(mpu, lcd, elements):
    """Enter a full morse character, then wait for auto-confirm."""
    for elem in elements:
        morse_element(mpu, lcd, is_dash=(elem == '-'))
    # Wait for auto-confirm timeout
    run_steps(mpu, lcd, CONFIRM_WAIT, buttons=0)


# =========================================================================
# Phase 1: Idle mode - GA auto-starts with phrase[0], then cycles
# =========================================================================

print("=== Phase 1: Idle mode - auto-solve phrases ===")

mpu = MPU()
load_rom(mpu, "dist/ga.out")
patch_delay(mpu)
mpu.memory[0x6004] = 0x42  # timer seed

mpu.pc = mpu.memory[0xFFFC] | (mpu.memory[0xFFFD] << 8)
print(f"Reset vector: ${mpu.pc:04X}")

lcd = LCDCapture(mpu)

# Verify phrase_idx starts at 0 and target is phrase[0]
target = read_target_buf(mpu)
print(f"  Initial phrase_idx: {mpu.memory[PHRASE_IDX_ZP]}")

# Let GA solve phrase[0] ("It's work")
gen, _ = run_until_solved(mpu, lcd, 50_000_000, label="[phrase 0] ")
assert gen >= 0, "Failed to solve phrase[0]"

# ga_done_wait auto-advances with patched delay (nearly instant).
# Run extra steps to ensure we're into phrase[1]'s GA.
run_steps(mpu, lcd, 200_000, buttons=0)

# Verify phrase_idx advanced to 1
phrase_idx = mpu.memory[PHRASE_IDX_ZP]
print(f"  phrase_idx after auto-advance: {phrase_idx}")
assert phrase_idx == 1, f"Expected phrase_idx=1, got {phrase_idx}"
target = read_target_buf(mpu)
print(f"  New target: \"{target}\"")
assert "I love Alisa" in target, f"Expected 'I love Alisa', got '{target}'"

# Let it solve phrase[1] too
gen, _ = run_until_solved(mpu, lcd, 50_000_000, label="[phrase 1] ")
assert gen >= 0, "Failed to solve phrase[1]"

# Verify it wraps back to phrase[0]
run_steps(mpu, lcd, 200_000, buttons=0)
phrase_idx = mpu.memory[PHRASE_IDX_ZP]
print(f"  phrase_idx after wrap: {phrase_idx}")
assert phrase_idx == 0, f"Expected phrase_idx=0 (wrap), got {phrase_idx}"

print("  Idle phrase cycling works!")

# =========================================================================
# Phase 2: Test morse input - press PA3 to enter input mode, enter "WOW"
# =========================================================================

print("\n=== Phase 2: Morse input test ===")

# GA is running with phrase[0] again. Press PA3 to enter input mode.
print("  Pressing PA3 to enter input mode...")
run_steps(mpu, lcd, 50_000, buttons=BTN_CANCEL)
run_steps(mpu, lcd, 5_000, buttons=0)

# Wait for input_loop tight loop
steps = run_until_tight_loop(mpu, lcd, 500_000)
assert steps >= 0, "Did not reach input_loop"
print(f"  Reached input mode after {steps} steps")

# Verify we're in input mode
target = read_target_buf(mpu)
target_pos = mpu.memory[0x1B]
print(f"  Target buffer: \"{target}\"")
assert target_pos == 0, f"Expected target_pos=0, got {target_pos}"

# Enter W (.--), O (---), W (.--) via morse
print("  Entering 'W' (.--) ...")
enter_morse_char(mpu, lcd, '.--')
ch = chr(mpu.memory[TARGET_BUF + 0])
print(f"    Decoded: '{ch}' | target_pos: {mpu.memory[0x1B]}")
assert ch == 'W', f"Expected 'W', got '{ch}'"

print("  Entering 'O' (---) ...")
enter_morse_char(mpu, lcd, '---')
ch = chr(mpu.memory[TARGET_BUF + 1])
print(f"    Decoded: '{ch}' | target_pos: {mpu.memory[0x1B]}")
assert ch == 'O', f"Expected 'O', got '{ch}'"

print("  Entering 'W' (.--) ...")
enter_morse_char(mpu, lcd, '.--')
ch = chr(mpu.memory[TARGET_BUF + 2])
print(f"    Decoded: '{ch}' | target_pos: {mpu.memory[0x1B]}")
assert ch == 'W', f"Expected 'W', got '{ch}'"

target = read_target_buf(mpu)
print(f"  Target buffer: \"{target}\"")

# Press BTN_GO to confirm target and start GA
print("  Pressing PA2 to start GA with target 'WOW'...")
run_steps(mpu, lcd, BTN_PRESS, buttons=BTN_GO)
run_steps(mpu, lcd, 50_000, buttons=0)

target = read_target_buf(mpu)
print(f"  Target buffer after GA start: \"{target}\"")
assert target == "WOW             ", f"Expected 'WOW             ', got '{target}'"

# Let GA run a few generations to confirm it's working
print("  Running GA with 'WOW' target...")
gen, _ = run_until_solved(mpu, lcd, 50_000_000, label="[WOW] ")
assert gen >= 0, "Failed to solve 'WOW'"

print("\n=== All tests passed! ===")
