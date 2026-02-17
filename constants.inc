; constants.inc - Shared hardware definitions
;
; VIA registers
PORTB = $6000
PORTA = $6001
DDRB = $6002
DDRA = $6003
T1CL = $6004              ; VIA Timer 1 counter low byte

; LCD control pins (accent accent accent accent accent accent accent accent accent accent accent)
E = %10000000
RW = %01000000
RS = %00100000

; Button masks (active-high, leftmost physical = PA0)
BTN_MORSE = %00000001     ; PA0 - morse input
BTN_CHAR  = %00000010     ; PA1 - backspace
BTN_GO    = %00000100     ; PA2 - confirm target / clear
BTN_CANCEL = %00001000    ; PA3 - cancel / unused

; Timing threshold for dot vs dash (high byte of press duration counter)
PRESS_THRESH = $30

; Auto-confirm timeout: high byte threshold (~1s at 1 MHz)
CONFIRM_THRESH = $50
