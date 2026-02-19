; lcd.inc - LCD routines (shared between ga.s and morse.s)
; Requires: PORTB, PORTA, DDRB, E, RW, RS from constants.inc

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
