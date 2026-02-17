"""Full GA test - run from reset, then test morse input mode."""

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
    """Detect JMP-to-self, BEQ-backward small loop, or PORTA polling loop."""
    pc = mpu.pc
    op = mpu.memory[pc]

    # JMP to self
    if (op == 0x4C and
        mpu.memory[pc + 1] == (pc & 0xFF) and
        mpu.memory[pc + 2] == ((pc >> 8) & 0xFF)):
        return True

    # BEQ backward small loop (e.g. ga_done polling, input_loop)
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


def find_ga_loop_addr(mpu):
    """Find the ga_loop address (LDA best_fit_lo / ORA best_fit_hi / BEQ)."""
    for a in range(0x8000, 0x80FF):
        if (mpu.memory[a] == 0xA5 and mpu.memory[a+1] == 0x03 and
            mpu.memory[a+2] == 0x05 and mpu.memory[a+3] == 0x04 and
            mpu.memory[a+4] == 0xF0):
            return a
    return None


# --- Timing constants for morse simulation ---
DOT_HOLD      = 5000      # press_hi ~ 3 (well below threshold of 24)
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
# Phase 1: GA with default target (press BTN_CANCEL to skip input mode)
# =========================================================================

print("=== Phase 1: GA with default target ===")

mpu = MPU()
load_rom(mpu, "ga.out")
patch_delay(mpu)
mpu.memory[0x6004] = 0x42  # timer seed

mpu.pc = mpu.memory[0xFFFC] | (mpu.memory[0xFFFD] << 8)
print(f"Reset vector: ${mpu.pc:04X}")

lcd = LCDCapture(mpu)

# Run until we hit the input_loop polling
steps = run_until_tight_loop(mpu, lcd, 500_000)
assert steps >= 0, "Did not reach input_loop"
print(f"  Reached input mode after {steps} steps")

# Verify default target is loaded
target = read_target_buf(mpu)
print(f"  Default target in buffer: \"{target}\"")

# Press BTN_CANCEL (PA3) to use default target and start GA
run_steps(mpu, lcd, BTN_PRESS, buttons=BTN_CANCEL)
run_steps(mpu, lcd, SETTLE, buttons=0)

ga_loop_addr = find_ga_loop_addr(mpu)
assert ga_loop_addr is not None, "Could not find ga_loop address"
print(f"  ga_loop at ${ga_loop_addr:04X}")

max_cycles = 500_000_000
cycles = 0
last_gen = -1

while cycles < max_cycles:
    if detect_tight_loop(mpu):
        gen = mpu.memory[0x07] * 256 + mpu.memory[0x06]
        dist = mpu.memory[0x04] * 256 + mpu.memory[0x03]
        l1, l2 = lcd.display()

        if gen != last_gen:
            if gen % 25 == 0 or dist == 0:
                print(f"  Gen {gen:4d} | dist={dist:3d} | LCD: \"{l1}\" / \"{l2}\"")
            last_gen = gen

        if dist == 0:
            print(f"  SOLVED in {gen} generations, {cycles:,} cycles!")
            break

        if gen >= 1000:
            print(f"  Stopped at gen {gen}, dist={dist}")
            break

        # Jump back to ga_loop to continue
        mpu.pc = ga_loop_addr
        continue

    mpu.step()
    lcd.step()
    cycles += 1

if cycles >= max_cycles:
    print(f"  Timeout at {cycles:,} cycles")

# =========================================================================
# Phase 2: Test morse input - enter "WOW" and verify
# =========================================================================

print("\n=== Phase 2: Morse input test ===")

# CPU is stuck at ga_done (PORTA polling loop).
# Press BTN_CANCEL (PA3) to enter input mode.
print("  Pressing PA3 to enter input mode...")
run_steps(mpu, lcd, BTN_PRESS, buttons=BTN_CANCEL)
run_steps(mpu, lcd, SETTLE, buttons=0)

# Wait for input_loop
steps = run_until_tight_loop(mpu, lcd, 100_000)
assert steps >= 0, "Did not reach input_loop after pressing cancel"

# Verify we're in input mode: target_pos should be 0, target buffer should be spaces
target = read_target_buf(mpu)
target_pos = mpu.memory[0x1B]  # target_pos zero-page var
print(f"  Target buffer: \"{target}\"")
print(f"  Target position: {target_pos}")
assert target == "                ", f"Expected spaces, got \"{target}\""
assert target_pos == 0, f"Expected target_pos=0, got {target_pos}"

l1, l2 = lcd.display()
print(f"  LCD: \"{l1}\" / \"{l2}\"")

# Enter W (.--), O (---), W (.--) via morse
print("  Entering 'W' (.--) ...")
enter_morse_char(mpu, lcd, '.--')
pos = mpu.memory[0x1B]
ch = chr(mpu.memory[TARGET_BUF + 0])
print(f"    Decoded: '{ch}' | target_pos: {pos}")
assert ch == 'W', f"Expected 'W', got '{ch}'"

print("  Entering 'O' (---) ...")
enter_morse_char(mpu, lcd, '---')
pos = mpu.memory[0x1B]
ch = chr(mpu.memory[TARGET_BUF + 1])
print(f"    Decoded: '{ch}' | target_pos: {pos}")
assert ch == 'O', f"Expected 'O', got '{ch}'"

print("  Entering 'W' (.--) ...")
enter_morse_char(mpu, lcd, '.--')
pos = mpu.memory[0x1B]
ch = chr(mpu.memory[TARGET_BUF + 2])
print(f"    Decoded: '{ch}' | target_pos: {pos}")
assert ch == 'W', f"Expected 'W', got '{ch}'"

target = read_target_buf(mpu)
print(f"  Target buffer: \"{target}\"")

l1, l2 = lcd.display()
print(f"  LCD: \"{l1}\" / \"{l2}\"")

# Press BTN_GO to confirm target and start GA
print("  Pressing PA2 to start GA with target 'WOW'...")
run_steps(mpu, lcd, BTN_PRESS, buttons=BTN_GO)
run_steps(mpu, lcd, SETTLE, buttons=0)

# Verify target is preserved
target = read_target_buf(mpu)
print(f"  Target buffer after GA start: \"{target}\"")
assert target == "WOW             ", f"Expected 'WOW             ', got '{target}'"

# Let GA run a few generations to confirm it's working with new target
print("  Running GA with 'WOW' target...")
for _ in range(5_000_000):
    if detect_tight_loop(mpu):
        gen = mpu.memory[0x07] * 256 + mpu.memory[0x06]
        dist = mpu.memory[0x04] * 256 + mpu.memory[0x03]
        l1, l2 = lcd.display()
        if gen % 25 == 0 or dist == 0:
            print(f"  Gen {gen:4d} | dist={dist:3d} | LCD: \"{l1}\" / \"{l2}\"")

        if dist == 0:
            print(f"  SOLVED 'WOW' in {gen} generations!")
            break

        if gen >= 200:
            print(f"  GA running at gen {gen}, dist={dist} (OK, stopping test)")
            break

        mpu.pc = ga_loop_addr
        continue

    mpu.step()
    lcd.step()

print("\n=== All tests passed! ===")
