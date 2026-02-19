  .include "constants.inc"

; Zero page variables
rng_lo = $00
rng_hi = $01
cur_ind = $02              ; current individual index (loop counter)
best_fit_lo = $03          ; best fitness distance low (lower = better)
best_fit_hi = $04          ; best fitness distance high
best_idx = $05             ; best individual index
gen_lo = $06               ; generation counter low byte
gen_hi = $07               ; generation counter high byte
scratch = $08              ; temp / exact match count for display
ptr_lo = $09               ; pointer for indirect addressing
ptr_hi = $0a
fit_a_lo = $0b             ; tournament: fitness of A, low
fit_a_hi = $0c             ; tournament: fitness of A, high
fit_b_lo = $0d             ; tournament: fitness of B, low
fit_b_hi = $0e             ; tournament: fitness of B, high
parent_a = $0f             ; index of parent A
parent_b = $10             ; index of parent B
crossover_pt = $11         ; crossover point
ptr2_lo = $12              ; second pointer (for child/dest)
ptr2_hi = $13
tourn_a = $14              ; tournament internal: candidate A index
tourn_b = $15              ; tournament internal: candidate B index
fit_res_lo = $16           ; calc_fitness result, low
fit_res_hi = $17           ; calc_fitness result, high
dec_lo = $18               ; temp for decimal print (16-bit value)
dec_hi = $19

; Morse input zero-page vars
morse_idx = $1a            ; current position in binary tree (1-31)
target_pos = $1b           ; cursor position in text buffer (0-15)
press_lo = $1c             ; press duration counter low
press_hi = $1d             ; press duration counter high
morse_len = $1e            ; number of dots/dashes for current char
phrase_idx = $1f            ; current phrase in idle rotation

; Population: 16 individuals x 16 bytes = 256 bytes at $0200
; New generation buffer at $0300-$03FF
POP_BASE = $0200
NEW_BASE = $0300
POP_SIZE = 16
IND_LEN = 16

; Morse input RAM buffers
TARGET_BUF = $0400         ; 16-byte target phrase buffer
TEXT_BUF = $0400           ; alias: morse.inc writes to TEXT_BUF
MORSE_BUF = $0410          ; morse dot/dash display (up to 7 chars)

PHRASE_COUNT = 2
DONE_DELAY = 150           ; 150 x 200ms = 30 seconds

  .org $8000

reset:
  ldx #$ff
  txs

  ; Configure VIA ports
  lda #%11111111 ; Set all 8 pins on port B to output
  sta DDRB
  lda #%11100000 ; Set top 3 pins on port A to output
  sta DDRA

  ; Initialize LCD
  lda #%00111000 ; 8-bit mode; 2-line display; 5x8 font
  jsr lcd_instruction
  lda #%00001100 ; Display on; Cursor off; Blinking off
  jsr lcd_instruction
  lda #%00000110 ; Increment and shift cursor; Don't shift display
  jsr lcd_instruction
  lda #%00000001 ; Clear display
  jsr lcd_instruction

  ; Seed PRNG from VIA Timer 1 (value varies each power-on)
  lda T1CL
  sta rng_lo
  ora #$01           ; ensure non-zero (zero state would get stuck)
  sta rng_hi

  ; Start idle mode: cycle through phrases
  lda #0
  sta phrase_idx
  jsr load_phrase
  jmp ga_start

; ---------------------------------------------------------------------------
; load_phrase: copy phrase_list[phrase_idx] into TARGET_BUF
; ---------------------------------------------------------------------------

load_phrase:
  lda phrase_idx
  asl a
  asl a
  asl a
  asl a              ; A = phrase_idx * 16
  clc
  adc #<phrase_list
  sta ptr_lo
  lda #>phrase_list
  adc #0
  sta ptr_hi
  ldy #0
load_phrase_loop:
  lda (ptr_lo),y
  sta TARGET_BUF,y
  iny
  cpy #IND_LEN
  bne load_phrase_loop
  rts

; ---------------------------------------------------------------------------
; next_phrase: advance phrase_idx (wrap around), load into TARGET_BUF
; ---------------------------------------------------------------------------

next_phrase:
  inc phrase_idx
  lda phrase_idx
  cmp #PHRASE_COUNT
  bcc next_phrase_ok
  lda #0
  sta phrase_idx
next_phrase_ok:
  jsr load_phrase
  rts

; ---------------------------------------------------------------------------
; input_mode: let user enter a custom target via morse, or cancel
; ---------------------------------------------------------------------------

input_mode:
  jsr init_input
  jsr input_display
  lda #0
  sta press_lo             ; reuse as timeout counter low
  sta press_hi             ; reuse as timeout counter high

input_loop:
  ; If morse in progress, check auto-confirm timeout
  lda morse_len
  beq input_poll           ; no morse elements yet, just poll buttons

  inc press_lo
  bne input_poll
  inc press_hi

  lda press_hi
  cmp #CONFIRM_THRESH
  bcc input_poll

  ; Timeout expired: auto-confirm
  jsr confirm_char
  jsr input_display
  lda #0
  sta press_lo
  sta press_hi
  jmp input_loop

input_poll:
  lda PORTA
  and #$0f               ; mask PA0-PA3

  ; Check PA0 (morse input)
  tax
  and #BTN_MORSE
  beq input_not_morse
  jsr debounce
  jsr read_morse_press
  jsr input_display
  ; Reset timeout after each element
  lda #0
  sta press_lo
  sta press_hi
  jmp input_loop

input_not_morse:
  ; Check PA1 (backspace)
  txa
  and #BTN_CHAR
  beq input_not_char
  jsr debounce
  jsr backspace
  jsr input_display
  jsr wait_release
  jmp input_loop

input_not_char:
  ; Check PA2 (confirm target -> start GA)
  txa
  and #BTN_GO
  beq input_not_go
  jsr debounce
  jmp ga_start

input_not_go:
  ; Check PA3 (cancel -> resume idle cycle)
  txa
  and #BTN_CANCEL
  beq input_loop         ; no button pressed
  jsr debounce
  jsr load_phrase
  jmp ga_start

; ---------------------------------------------------------------------------
; ga_start: reset generation counter, init population, begin GA
; ---------------------------------------------------------------------------

ga_start:
  lda #0
  sta gen_lo
  sta gen_hi

  jsr init_population
  jsr find_best
  jsr display

; ---------------------------------------------------------------------------
; Main GA loop
; ---------------------------------------------------------------------------

ga_loop:
  ; Check if perfect fitness reached (distance == 0)
  lda best_fit_lo
  ora best_fit_hi
  beq ga_done          ; both zero = perfect match

  ; Check PA3 (cancel -> re-enter input mode)
  lda PORTA
  and #BTN_CANCEL
  beq ga_continue
  jsr debounce
  jsr wait_release
  jmp input_mode

ga_continue:
  jsr evolve
  jsr copy_new_to_pop

  ; Increment generation counter (16-bit)
  inc gen_lo
  bne no_gen_carry
  inc gen_hi
no_gen_carry:

  jsr find_best
  jsr display
  jsr delay
  jmp ga_loop

; ---------------------------------------------------------------------------
; ga_done: wait ~30s polling PA3, then advance to next phrase
; ---------------------------------------------------------------------------

ga_done:
  lda #DONE_DELAY
  sta scratch            ; reuse as delay counter (display is done)
ga_done_wait:
  lda PORTA
  and #BTN_CANCEL
  bne ga_done_to_input
  jsr delay              ; ~200ms
  dec scratch
  bne ga_done_wait

  ; 30s elapsed: advance to next phrase
  jsr next_phrase
  jmp ga_start

ga_done_to_input:
  jsr debounce
  jsr wait_release
  jmp input_mode

; ---------------------------------------------------------------------------
; init_population: fill 16 individuals x 16 bytes with random printable chars
; ---------------------------------------------------------------------------

init_population:
  lda #0
  sta cur_ind
init_pop_outer:
  lda cur_ind
  jsr set_ptr_pop
  ldy #0
init_pop_inner:
  jsr rand_printable
  sta (ptr_lo),y
  iny
  cpy #IND_LEN
  bne init_pop_inner

  inc cur_ind
  lda cur_ind
  cmp #POP_SIZE
  bne init_pop_outer
  rts

; ---------------------------------------------------------------------------
; set_ptr_pop: set ptr_lo/ptr_hi to POP_BASE + A * 16
; set_ptr_new: set ptr2_lo/ptr2_hi to NEW_BASE + A * 16
; ---------------------------------------------------------------------------

set_ptr_pop:
  asl a
  asl a
  asl a
  asl a
  clc
  adc #<POP_BASE
  sta ptr_lo
  lda #>POP_BASE
  adc #0
  sta ptr_hi
  rts

set_ptr_new:
  asl a
  asl a
  asl a
  asl a
  clc
  adc #<NEW_BASE
  sta ptr2_lo
  lda #>NEW_BASE
  adc #0
  sta ptr2_hi
  rts

; ---------------------------------------------------------------------------
; calc_fitness: individual index in cur_ind
; Returns 16-bit distance (sum of abs diffs) in fit_res_lo/fit_res_hi
; Lower = better. 0 = perfect match.
; ---------------------------------------------------------------------------

calc_fitness:
  lda cur_ind
  jsr set_ptr_pop

  lda #0
  sta fit_res_lo
  sta fit_res_hi
  ldy #0
calc_fit_loop:
  cpy #IND_LEN
  beq calc_fit_done
  ; Compute abs(individual[y] - target[y])
  lda (ptr_lo),y
  sec
  sbc TARGET_BUF,y     ; compare against RAM target buffer
  bpl calc_fit_pos     ; positive or zero: already abs value
  ; Negative: negate (two's complement)
  eor #$ff
  clc
  adc #1
calc_fit_pos:
  ; A = abs difference (0-90). Add to 16-bit total.
  clc
  adc fit_res_lo
  sta fit_res_lo
  bcc calc_fit_no_carry
  inc fit_res_hi
calc_fit_no_carry:
  iny
  jmp calc_fit_loop
calc_fit_done:
  rts

; ---------------------------------------------------------------------------
; find_best: scan all individuals, set best_fit_lo/hi and best_idx
; Finds individual with MINIMUM distance.
; ---------------------------------------------------------------------------

find_best:
  lda #$ff             ; start with worst possible distance
  sta best_fit_lo
  sta best_fit_hi
  lda #0
  sta best_idx
  sta cur_ind
find_best_loop:
  jsr calc_fitness
  ; Compare fit_res with best_fit (16-bit): is fit_res < best_fit?
  lda fit_res_hi
  cmp best_fit_hi
  bcc find_best_new    ; fit_res_hi < best_fit_hi -> new best
  bne find_best_next   ; fit_res_hi > best_fit_hi -> skip
  ; High bytes equal, compare low bytes
  lda fit_res_lo
  cmp best_fit_lo
  bcs find_best_next   ; fit_res_lo >= best_fit_lo -> skip
find_best_new:
  lda fit_res_lo
  sta best_fit_lo
  lda fit_res_hi
  sta best_fit_hi
  lda cur_ind
  sta best_idx
find_best_next:
  inc cur_ind
  lda cur_ind
  cmp #POP_SIZE
  bne find_best_loop
  rts

; ---------------------------------------------------------------------------
; evolve: create next generation in NEW_BASE
; ---------------------------------------------------------------------------

evolve:
  ; --- Elitism: copy best individual to slot 0 of new generation ---
  lda best_idx
  jsr set_ptr_pop
  lda #0
  jsr set_ptr_new
  ldy #0
elite_copy:
  lda (ptr_lo),y
  sta (ptr2_lo),y
  iny
  cpy #IND_LEN
  bne elite_copy

  ; Evolve slots 1-15
  lda #1
  sta cur_ind
evolve_loop:
  lda cur_ind
  pha                  ; save evolve loop counter

  jsr tournament
  sta parent_a

  jsr tournament
  sta parent_b

  pla
  sta cur_ind          ; restore evolve loop counter

  ; --- Crossover ---
  lda parent_a
  jsr set_ptr_pop      ; ptr -> parent A
  lda cur_ind
  jsr set_ptr_new      ; ptr2 -> child slot

  ; Pick random crossover point (0-15)
  jsr rand
  and #$0f
  sta crossover_pt

  ; Copy bytes 0..crossover_pt from parent A
  ldy #0
cross_a:
  lda (ptr_lo),y
  sta (ptr2_lo),y
  cpy crossover_pt
  beq cross_switch
  iny
  jmp cross_a

cross_switch:
  iny
  cpy #IND_LEN
  beq mutate_child
  ; Switch ptr to parent B
  lda parent_b
  jsr set_ptr_pop
cross_b:
  lda (ptr_lo),y
  sta (ptr2_lo),y
  iny
  cpy #IND_LEN
  bne cross_b

  ; --- Mutate child (nudge mutations) ---
mutate_child:
  lda cur_ind
  jsr set_ptr_new      ; reload ptr2 to child
  ldy #0
mutate_loop:
  jsr rand
  and #$0f             ; 1/16 chance (~6%)
  bne mutate_skip
  ; Nudge: add random offset -8..+7 to current char
  lda (ptr2_lo),y
  sta scratch          ; save current char
  jsr rand
  and #$0f             ; 0-15
  sec
  sbc #8               ; -8..+7
  clc
  adc scratch          ; add to current char
  ; Clamp to printable range $20-$7A
  cmp #$20
  bcs mutate_check_hi
  lda #$20             ; clamp low
  jmp mutate_store
mutate_check_hi:
  cmp #$7b
  bcc mutate_store
  lda #$7a             ; clamp high
mutate_store:
  sta (ptr2_lo),y
mutate_skip:
  iny
  cpy #IND_LEN
  bne mutate_loop

  ; Next individual
  inc cur_ind
  lda cur_ind
  cmp #POP_SIZE
  bne evolve_loop
  rts

; ---------------------------------------------------------------------------
; tournament: pick 2 random individuals, return index of fitter one in A
; (lower distance = fitter)
; ---------------------------------------------------------------------------

tournament:
  ; Pick random individual A
  jsr rand
  and #$0f
  sta tourn_a
  sta cur_ind
  jsr calc_fitness
  lda fit_res_lo
  sta fit_a_lo
  lda fit_res_hi
  sta fit_a_hi

  ; Pick random individual B
  jsr rand
  and #$0f
  sta tourn_b
  sta cur_ind
  jsr calc_fitness
  lda fit_res_lo
  sta fit_b_lo
  lda fit_res_hi
  sta fit_b_hi

  ; Return the one with LOWER distance
  ; Compare fit_a with fit_b (16-bit)
  lda fit_a_hi
  cmp fit_b_hi
  bcc tourn_a_wins     ; fit_a_hi < fit_b_hi -> A is fitter
  bne tourn_b_wins     ; fit_a_hi > fit_b_hi -> B is fitter
  ; High bytes equal
  lda fit_a_lo
  cmp fit_b_lo
  bcc tourn_a_wins     ; fit_a_lo < fit_b_lo -> A is fitter
  beq tourn_a_wins     ; equal -> pick A
tourn_b_wins:
  lda tourn_b
  rts
tourn_a_wins:
  lda tourn_a
  rts

; ---------------------------------------------------------------------------
; copy_new_to_pop: copy $0300-$03FF to $0200-$02FF (256 bytes)
; ---------------------------------------------------------------------------

copy_new_to_pop:
  ldx #0
copy_loop:
  lda NEW_BASE,x
  sta POP_BASE,x
  inx
  bne copy_loop
  rts

; ---------------------------------------------------------------------------
; display: show best individual on line 1, stats on line 2
; ---------------------------------------------------------------------------

display:
  lda #%00000001
  jsr lcd_instruction

  ; Print best individual on line 1
  lda best_idx
  jsr set_ptr_pop

  ; Count exact matches while printing (for display)
  lda #0
  sta scratch          ; exact match count
  ldy #0
display_best:
  lda (ptr_lo),y
  cmp TARGET_BUF,y     ; compare against RAM target buffer
  bne display_no_match
  inc scratch
display_no_match:
  jsr print_char
  iny
  cpy #IND_LEN
  bne display_best

  ; Line 2: "Fit:X% Gen:XXXX"
  jsr lcd_set_line2

  ldx #0
display_fit_label:
  lda msg_fit,x
  beq display_fit_val
  jsr print_char
  inx
  jmp display_fit_label

display_fit_val:
  ; Display percentage (uses scratch, must come before print_dec16)
  ldx scratch
  lda pct_table,x      ; lookup percentage (0-100)
  sta dec_lo
  lda #0
  sta dec_hi
  jsr print_dec16
  lda #'%'
  jsr print_char

  ldx #0
display_gen_label:
  lda msg_gen,x
  beq display_gen_val
  jsr print_char
  inx
  jmp display_gen_label

display_gen_val:
  lda gen_lo
  sta dec_lo
  lda gen_hi
  sta dec_hi
  jsr print_dec16

  rts

; ---------------------------------------------------------------------------
; print_dec16: print dec_lo/dec_hi as up to 5 decimal digits (no leading zeros)
; Uses repeated subtraction for each power of 10.
; ---------------------------------------------------------------------------

print_dec16:
  ldx #0                ; index into dec_table (0-4)
  lda #0
  sta scratch           ; leading zero flag: 0 = still skipping
print_dec_place:
  ldy #0                ; digit counter for this place
print_dec_sub:
  ; Try subtracting dec_table[x] (16-bit) from dec_lo/hi
  lda dec_lo
  sec
  sbc dec_table_lo,x
  pha                   ; save tentative low
  lda dec_hi
  sbc dec_table_hi,x
  bcc print_dec_emit    ; underflow: done with this digit
  ; Subtraction succeeded
  sta dec_hi
  pla
  sta dec_lo
  iny                   ; digit++
  jmp print_dec_sub
print_dec_emit:
  pla                   ; discard tentative low
  ; Y = digit value for this place
  tya
  bne print_dec_nonzero
  ; Digit is 0: print only if we've seen a nonzero digit, or last place
  lda scratch
  beq print_dec_maybe_last
  tya                   ; restore A = 0 (the digit)
  beq print_dec_print   ; always taken
print_dec_maybe_last:
  cpx #4                ; last place (ones)? always print
  beq print_dec_print   ; A is already 0
  jmp print_dec_next    ; skip leading zero
print_dec_nonzero:
  inc scratch           ; mark that we've started printing
  tya
print_dec_print:
  clc
  adc #'0'
  jsr print_char
print_dec_next:
  inx
  cpx #5
  bne print_dec_place
  rts

dec_table_lo: .byte <10000, <1000, <100, <10, <1
dec_table_hi: .byte >10000, >1000, >100, >10, >1

; ---------------------------------------------------------------------------
; Data
; ---------------------------------------------------------------------------

; Phrase list for idle mode (each entry is IND_LEN=16 bytes, space-padded)
phrase_list:
  .byte "It's work       "
  .byte "I love Alisa    "

msg_fit: .asciiz "Fit:"
msg_gen: .asciiz " Gen:"

; Percentage lookup: index 0-16 -> round(i * 100 / 16)
pct_table: .byte 0, 6, 12, 19, 25, 31, 38, 44, 50, 56, 62, 69, 75, 81, 88, 94, 100

; ---------------------------------------------------------------------------
; PRNG: 16-bit Galois LFSR
; ---------------------------------------------------------------------------

rand:
  ldx #8               ; advance LFSR 8 bits for independence
rand_shift:
  lsr rng_hi
  ror rng_lo
  bcc rand_no_tap
  lda rng_hi
  eor #$b4
  sta rng_hi
rand_no_tap:
  dex
  bne rand_shift
  lda rng_lo
  rts

; ---------------------------------------------------------------------------
; rand_printable: returns random byte in range $20-$7A
; ---------------------------------------------------------------------------

rand_printable:
  jsr rand
  and #%01111111
rand_mod:
  cmp #91
  bcc rand_mod_done
  sbc #91
  jmp rand_mod
rand_mod_done:
  clc
  adc #$20
  rts

; ---------------------------------------------------------------------------
; Delay: ~200ms at 1 MHz
; ---------------------------------------------------------------------------

delay:
  txa
  pha
  tya
  pha
  ldx #200
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
  rts

  .include "lcd.inc"
  .include "morse.inc"

  .org $fffc
  .word reset
  .word $0000
