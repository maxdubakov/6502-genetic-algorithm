PORTB = $6000
PORTA = $6001
DDRB = $6002
DDRA = $6003

E = %10000000
RW = %01000000
RS = %00100000

  .org $8000

reset:
  ldx #$ff
  txs

  lda #%11111111       ; Port B all output (LCD data)
  sta DDRB
  lda #%11100000       ; PA7-5 output (LCD), PA4-0 input (buttons)
  sta DDRA

  ; Init LCD
  lda #%00111000       ; 8-bit, 2-line, 5x8
  jsr lcd_instruction
  lda #%00001100       ; Display on, cursor off
  jsr lcd_instruction
  lda #%00000110       ; Increment cursor
  jsr lcd_instruction

loop:
  lda #%00000001       ; Clear display
  jsr lcd_instruction

  ; Read port A and show as binary on line 1
  lda PORTA
  and #%00011111       ; mask to input pins PA0-PA4
  sta $00              ; save in ZP

  ; Print "PORTA: " label
  ldx #0
print_label:
  lda msg,x
  beq print_bits
  jsr print_char
  inx
  jmp print_label

print_bits:
  ; Print bits 4..0 as '0'/'1'
  ldx #4               ; start from bit 4
print_bit:
  lda $00
  and bit_mask,x
  beq print_zero
  lda #'1'
  jmp print_store
print_zero:
  lda #'0'
print_store:
  jsr print_char
  lda #' '
  jsr print_char
  dex
  bpl print_bit

  ; Line 2: show which buttons are pressed
  jsr lcd_set_line2
  ldx #0
print_label2:
  lda msg2,x
  beq print_btn_state
  jsr print_char
  inx
  jmp print_label2

print_btn_state:
  lda $00
  and #%00011111
  beq no_press
  ; Print the raw hex value
  jsr print_hex
  jmp delay_loop
no_press:
  lda #'N'
  jsr print_char
  lda #'o'
  jsr print_char
  lda #'n'
  jsr print_char
  lda #'e'
  jsr print_char

delay_loop:
  ; Short delay to avoid LCD flicker
  txa
  pha
  tya
  pha
  ldx #80
delay_outer:
  ldy #250
delay_inner:
  dey
  bne delay_inner
  dex
  bne delay_outer
  pla
  tay
  pla
  tax

  jmp loop

; Print A as 2 hex digits
print_hex:
  pha
  lsr a
  lsr a
  lsr a
  lsr a
  jsr print_hex_digit
  pla
  and #$0f
  jsr print_hex_digit
  rts

print_hex_digit:
  cmp #10
  bcc hex_num
  clc
  adc #('A' - 10)
  jsr print_char
  rts
hex_num:
  clc
  adc #'0'
  jsr print_char
  rts

msg:  .asciiz "PA: "
msg2: .asciiz "Btn: "

bit_mask: .byte 1, 2, 4, 8, 16

; --- LCD routines ---

lcd_set_line2:
  lda #$c0
  jsr lcd_instruction
  rts

lcd_wait:
  pha
  lda #%00000000
  sta DDRB
lcd_busy:
  lda #RW
  sta PORTA
  lda #(RW | E)
  sta PORTA
  lda PORTB
  and #%10000000
  bne lcd_busy
  lda #RW
  sta PORTA
  lda #%11111111
  sta DDRB
  pla
  rts

lcd_instruction:
  jsr lcd_wait
  sta PORTB
  lda #0
  sta PORTA
  lda #E
  sta PORTA
  lda #0
  sta PORTA
  rts

print_char:
  jsr lcd_wait
  sta PORTB
  lda #RS
  sta PORTA
  lda #(RS | E)
  sta PORTA
  lda #RS
  sta PORTA
  rts

  .org $fffc
  .word reset
  .word $0000
