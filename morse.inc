; morse.inc - Morse code input routines
;
; Caller must define zero-page vars: morse_idx, target_pos, press_lo, press_hi, morse_len, scratch
; Caller must define RAM buffers: TEXT_BUF (16 bytes), MORSE_BUF (7 bytes)
; Requires: PORTA, BTN_MORSE, PRESS_THRESH from constants.inc
; Requires: lcd_instruction, lcd_set_line2, print_char from lcd.inc

; ---------------------------------------------------------------------------
; init_input: clear text buffer and reset morse state
; ---------------------------------------------------------------------------

init_input:
  lda #' '
  ldx #0
init_clear:
  sta TEXT_BUF,x
  inx
  cpx #16
  bne init_clear

  lda #0
  sta target_pos
  sta morse_len
  lda #1
  sta morse_idx
  rts

; ---------------------------------------------------------------------------
; read_morse_press: wait for button release, measure duration -> dot or dash
; ---------------------------------------------------------------------------

read_morse_press:
  lda #0
  sta press_lo
  sta press_hi

morse_hold:
  lda PORTA
  and #BTN_MORSE
  beq morse_released

  inc press_lo
  bne morse_hold
  inc press_hi
  jmp morse_hold

morse_released:
  jsr debounce

  ; morse_idx *= 2 (dot path)
  asl morse_idx

  ; Check if dash (high byte >= threshold)
  lda press_hi
  cmp #PRESS_THRESH
  bcc morse_is_dot

  ; Dash: add 1 to morse_idx
  inc morse_idx

  ; Record dash in display buffer (max 5 shown)
  ldy morse_len
  cpy #7
  bcs morse_dash_count
  lda #'-'
  sta MORSE_BUF,y
morse_dash_count:
  inc morse_len
  jmp morse_done

morse_is_dot:
  ; Record dot in display buffer (max 5 shown)
  ldy morse_len
  cpy #7
  bcs morse_dot_count
  lda #'.'
  sta MORSE_BUF,y
morse_dot_count:
  inc morse_len

morse_done:
  rts

; ---------------------------------------------------------------------------
; confirm_char: decode morse_idx via tree, append to text, reset morse state
; ---------------------------------------------------------------------------

confirm_char:
  ; Check if buffer full
  lda target_pos
  cmp #16
  bcs confirm_reset

  ; 7+ dots/dashes = space
  lda morse_len
  cmp #7
  bcs confirm_space

  ; Decode via binary tree
  lda morse_idx
  cmp #64
  bcs confirm_invalid
  tax
  lda morse_tree,x
  beq confirm_invalid
  jmp confirm_store

confirm_space:
  lda #' '
  jmp confirm_store

confirm_invalid:
  lda #'?'

confirm_store:
  ldx target_pos
  sta TEXT_BUF,x
  inc target_pos

confirm_reset:
  lda #1
  sta morse_idx
  lda #0
  sta morse_len
  rts

; ---------------------------------------------------------------------------
; backspace: remove last character from text buffer
; ---------------------------------------------------------------------------

backspace:
  lda target_pos
  beq backspace_done     ; nothing to delete
  dec target_pos
  ldx target_pos
  lda #' '
  sta TEXT_BUF,x
backspace_done:
  ; Reset morse state in case user was mid-entry
  lda #1
  sta morse_idx
  lda #0
  sta morse_len
  rts

; ---------------------------------------------------------------------------
; input_display: line 1 = entered text, line 2 = current morse pattern
; ---------------------------------------------------------------------------

input_display:
  lda #%00000001         ; clear display
  jsr lcd_instruction

  ; Line 1: text buffer
  ldx #0
disp_text:
  lda TEXT_BUF,x
  jsr print_char
  inx
  cpx #16
  bne disp_text

  ; Line 2: dot/dash pattern
  jsr lcd_set_line2

  ldx #0
disp_morse:
  cpx morse_len
  beq disp_morse_done
  lda MORSE_BUF,x
  jsr print_char
  inx
  cpx #5
  bne disp_morse

disp_morse_done:
  rts

; ---------------------------------------------------------------------------
; wait_release: wait until all buttons (PA0-PA3) are released, then debounce
; ---------------------------------------------------------------------------

wait_release:
  lda PORTA
  and #$0f
  bne wait_release
  jsr debounce
  rts

; ---------------------------------------------------------------------------
; debounce: ~20ms delay
; ---------------------------------------------------------------------------

debounce:
  txa
  pha
  tya
  pha
  ldx #20
debounce_outer:
  ldy #200
debounce_inner:
  dey
  bne debounce_inner
  dex
  bne debounce_outer
  pla
  tay
  pla
  tax
  rts

; ---------------------------------------------------------------------------
; Morse binary tree (64 bytes)
; Index 1 = root. Dot = index*2. Dash = index*2+1.
; Levels 1-4: letters. Level 5: numbers.
; ---------------------------------------------------------------------------

morse_tree:
  .byte 0              ; 0: unused
  .byte 0              ; 1: root
  .byte "E"            ; 2: .
  .byte "T"            ; 3: -
  .byte "I"            ; 4: ..
  .byte "A"            ; 5: .-
  .byte "N"            ; 6: -.
  .byte "M"            ; 7: --
  .byte "S"            ; 8: ...
  .byte "U"            ; 9: ..-
  .byte "R"            ; 10: .-.
  .byte "W"            ; 11: .--
  .byte "D"            ; 12: -..
  .byte "K"            ; 13: -.-
  .byte "G"            ; 14: --.
  .byte "O"            ; 15: ---
  .byte "H"            ; 16: ....
  .byte "V"            ; 17: ...-
  .byte "F"            ; 18: ..-.
  .byte 0              ; 19: ..--
  .byte "L"            ; 20: .-..
  .byte 0              ; 21: .-.-
  .byte "P"            ; 22: .--.
  .byte "J"            ; 23: .---
  .byte "B"            ; 24: -...
  .byte "X"            ; 25: -..-
  .byte "C"            ; 26: -.-.
  .byte "Y"            ; 27: -.--
  .byte "Z"            ; 28: --..
  .byte "Q"            ; 29: --.-
  .byte 0              ; 30: ---.
  .byte 0              ; 31: ----
  ; Level 5: numbers
  .byte "5"            ; 32: .....
  .byte "4"            ; 33: ....-
  .byte 0              ; 34: ...-.
  .byte "3"            ; 35: ...--
  .byte 0              ; 36: ..-..
  .byte 0              ; 37: ..-.-
  .byte 0              ; 38: ..--.
  .byte "2"            ; 39: ..---
  .byte 0              ; 40: .-...
  .byte 0              ; 41: .-..-(
  .byte 0              ; 42: .-.-.
  .byte 0              ; 43: .-.--
  .byte 0              ; 44: .--..
  .byte 0              ; 45: .--.-(
  .byte 0              ; 46: .---.
  .byte "1"            ; 47: .----
  .byte "6"            ; 48: -....
  .byte 0              ; 49: -...-
  .byte 0              ; 50: -..-.
  .byte 0              ; 51: -..--
  .byte 0              ; 52: -.-..
  .byte 0              ; 53: -.-.-
  .byte 0              ; 54: -.--.
  .byte 0              ; 55: -.---
  .byte "7"            ; 56: --...
  .byte 0              ; 57: --..-
  .byte 0              ; 58: --.-.
  .byte 0              ; 59: --.--
  .byte "8"            ; 60: ---..
  .byte 0              ; 61: ---.-
  .byte "9"            ; 62: ----.
  .byte "0"            ; 63: -----
