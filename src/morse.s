; morse.s - Standalone morse code input test
; Enter letters via single button (timing-based dot/dash),
; confirm each character, see result on LCD.
;
; Buttons (active-high, leftmost physical = PA0):
;   PA0 (leftmost)  - Morse input: short press = dot, long press = dash
;   PA1             - Confirm character (decode & append to buffer)
;   PA2             - Clear display and reset
;   PA3 (rightmost) - (unused)

  .include "constants.inc"

; Zero page variables
morse_idx = $00            ; current position in binary tree (1-31)
target_pos = $01           ; cursor position in text buffer (0-15)
press_lo = $02             ; press duration counter low
press_hi = $03             ; press duration counter high
morse_len = $04            ; number of dots/dashes for current char
scratch = $05

; RAM buffers
TEXT_BUF = $0200           ; 16-byte entered text buffer
MORSE_BUF = $0210          ; morse dot/dash display (up to 5 chars)

  .org $8000

reset:
  ldx #$ff
  txs

  ; Configure VIA ports
  lda #%11111111           ; Port B all output (LCD data)
  sta DDRB
  lda #%11100000           ; PA5-7 output (LCD ctrl), PA0-4 input (buttons)
  sta DDRA

  ; Initialize LCD
  lda #%00111000           ; 8-bit mode; 2-line; 5x8 font
  jsr lcd_instruction
  lda #%00001100           ; Display on; cursor off; blink off
  jsr lcd_instruction
  lda #%00000110           ; Increment cursor; no display shift
  jsr lcd_instruction
  lda #%00000001           ; Clear display
  jsr lcd_instruction

  jsr init_input
  jsr input_display
  lda #0
  sta press_lo             ; reuse as timeout counter low
  sta press_hi             ; reuse as timeout counter high

; ---------------------------------------------------------------------------
; Main loop: poll buttons with auto-confirm timeout
; ---------------------------------------------------------------------------

main_loop:
  ; If morse in progress, check auto-confirm timeout
  lda morse_len
  beq main_poll           ; no morse elements yet, just poll buttons

  inc press_lo
  bne main_poll
  inc press_hi

  lda press_hi
  cmp #CONFIRM_THRESH
  bcc main_poll

  ; Timeout expired: auto-confirm
  jsr confirm_char
  jsr input_display
  lda #0
  sta press_lo
  sta press_hi
  jmp main_loop

main_poll:
  lda PORTA
  and #$0f               ; mask PA0-PA3

  ; Check PA0 (morse button)
  tax
  and #BTN_MORSE
  beq not_morse
  jsr debounce
  jsr read_morse_press
  jsr input_display
  ; Reset timeout after each element
  lda #0
  sta press_lo
  sta press_hi
  jmp main_loop

not_morse:
  ; Check PA1 (backspace)
  txa
  and #BTN_CHAR
  beq not_char
  jsr debounce
  jsr backspace
  jsr input_display
  jsr wait_release
  jmp main_loop

not_char:
  ; Check PA2 (clear/reset)
  txa
  and #BTN_GO
  beq main_loop          ; no button pressed
  jsr debounce
  jsr init_input
  jsr input_display
  jsr wait_release
  jmp main_loop

  .include "lcd.inc"
  .include "morse.inc"

  .org $fffc
  .word reset
  .word $0000
