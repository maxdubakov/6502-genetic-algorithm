"""Full GA test - run from reset, cap at 1000 generations."""

from py65.devices.mpu65c02 import MPU

PORTB = 0x6000
PORTA = 0x6001
RS = 0x20
E = 0x80


class LCDCapture:
    """Intercept VIA writes to capture LCD output."""

    def __init__(self, mpu):
        self.mpu = mpu
        self.lines = ["", ""]  # two 16-char lines
        self.cursor = 0  # 0-15 = line 1, 64-79 = line 2
        self.last_portb = 0
        self.last_porta = 0

    def step(self):
        """Call after each mpu.step() to check for LCD writes."""
        porta = self.mpu.memory[PORTA]
        portb = self.mpu.memory[PORTB]

        # Detect rising edge of E (enable)
        if (porta & E) and not (self.last_porta & E):
            if porta & RS:
                # Data write (print_char): RS set
                ch = chr(portb) if 0x20 <= portb <= 0x7E else "?"
                if self.cursor < 16:
                    self.lines[0] += ch
                elif self.cursor >= 64 and self.cursor < 80:
                    self.lines[1] += ch
                self.cursor += 1
            else:
                # Instruction write
                if portb == 0x01:
                    # Clear display
                    self.lines = ["", ""]
                    self.cursor = 0
                elif portb & 0x80:
                    # Set DDRAM address
                    self.cursor = portb & 0x7F

        self.last_porta = porta
        self.last_portb = portb

    def display(self):
        """Return the current LCD content as a string."""
        l1 = self.lines[0].ljust(16)[:16]
        l2 = self.lines[1].ljust(16)[:16]
        return l1, l2


def load_rom(mpu, path):
    with open(path, "rb") as f:
        data = f.read()
    for i, byte in enumerate(data):
        mpu.memory[0x8000 + i] = byte


def patch_delay(mpu):
    """Only patch the delay routine - keep LCD routines working."""
    for addr in range(0x8000, 0xFFF0):
        if (mpu.memory[addr] == 0x8A and mpu.memory[addr+1] == 0x48 and
            mpu.memory[addr+2] == 0x98 and mpu.memory[addr+3] == 0x48 and
            mpu.memory[addr+4] == 0xA2 and mpu.memory[addr+5] == 0xC8):
            mpu.memory[addr] = 0x60
            break

    # Patch lcd_wait to just preserve A and return (PHA/PLA/RTS)
    # instead of actually polling the busy flag
    for addr in range(0x8000, 0xFFF0):
        if (mpu.memory[addr] == 0x48 and mpu.memory[addr+1] == 0xA9 and
            mpu.memory[addr+2] == 0x00 and mpu.memory[addr+3] == 0x8D and
            mpu.memory[addr+4] == 0x02 and mpu.memory[addr+5] == 0x60):
            # Replace lcd_wait body: PHA, PLA, RTS (keep A, skip busy loop)
            mpu.memory[addr] = 0x48      # PHA
            mpu.memory[addr + 1] = 0x68  # PLA
            mpu.memory[addr + 2] = 0x60  # RTS
            break


mpu = MPU()
load_rom(mpu, "ga.out")
patch_delay(mpu)
mpu.memory[0x6004] = 0x42

mpu.pc = mpu.memory[0xFFFC] | (mpu.memory[0xFFFD] << 8)
print(f"Reset vector: ${mpu.pc:04X}")

lcd = LCDCapture(mpu)
max_cycles = 500_000_000
cycles = 0
last_gen = -1

while cycles < max_cycles:
    pc = mpu.pc
    if (mpu.memory[pc] == 0x4C and
        mpu.memory[pc + 1] == (pc & 0xFF) and
        mpu.memory[pc + 2] == ((pc >> 8) & 0xFF)):
        # Hit a JMP-to-self (ga_done)
        gen = mpu.memory[0x07] * 256 + mpu.memory[0x06]
        dist = mpu.memory[0x04] * 256 + mpu.memory[0x03]
        l1, l2 = lcd.display()

        if gen != last_gen:
            if gen % 25 == 0 or dist == 0:
                print(f"  Gen {gen:4d} | dist={dist:3d} | LCD: \"{l1}\" / \"{l2}\"")
            last_gen = gen

        if dist == 0:
            print(f"\n  SOLVED in {gen} generations, {cycles:,} cycles!")
            break

        if gen >= 1000:
            print(f"\n  Stopped at gen {gen}, dist={dist}")
            break

        # Jump to ga_loop
        for a in range(0x8000, 0x80FF):
            if (mpu.memory[a] == 0xA5 and mpu.memory[a+1] == 0x03 and
                mpu.memory[a+2] == 0x05 and mpu.memory[a+3] == 0x04 and
                mpu.memory[a+4] == 0xF0):
                mpu.pc = a
                break
        else:
            print("Could not find ga_loop!")
            break
        continue

    mpu.step()
    lcd.step()
    cycles += 1

if cycles >= max_cycles:
    gen = mpu.memory[0x07] * 256 + mpu.memory[0x06]
    dist = mpu.memory[0x04] * 256 + mpu.memory[0x03]
    print(f"\n  Timeout at gen {gen}, dist={dist}")
