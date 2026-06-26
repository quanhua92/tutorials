# AES (Rijndael) — A Substitution-Permutation Network, From Scratch

> **Companion code:** [`aes_spn.py`](./aes_spn.py). **Every number in this guide
> is printed by `uv run python aes_spn.py`** — nothing hand-computed, not even
> the S-box (it is *generated* from GF(2⁸) math and verified against FIPS-197).
>
> **Sibling guide:** [`XOR_CIPHER.md`](./XOR_CIPHER.md) — AES-CTR/GCM are
> literally "XOR with an AES-derived keystream," so the two guides connect.
> Cross-references are marked 🔗 throughout.
>
> **Live animation:** [`aes_spn.html`](./aes_spn.html) — the S-box built
> live, the 4×4 state marching through SubBytes → ShiftRows → MixColumns →
> AddRoundKey, recomputed in JS and checked against FIPS-197.

---

## 0. TL;DR — confusion + diffusion, layered 10 times

> **The key insight (read this first):** a **Substitution-Permutation Network
> (SPN)** scrambles a block by alternating two operations, over and over:
> **substitution** (the S-box — nonlinear *confusion*, hides the key's effect)
> and **permutation/mixing** (ShiftRows + MixColumns — *diffusion*, spreads one
> byte's influence across the whole block). One round of each is weak; AES-128
> chains **ten rounds** with a round key mixed in each time, so the avalanche
> compounds until every output bit depends on every key bit **and** every input
> bit.

```
one AES round:
  state ──SubBytes──▶ ──ShiftRows──▶ ──MixColumns──▶ ──AddRoundKey──▶ state
         (substitute)   (permute)      (mix/diffuse)   (mix in key)
   (the 10th/last round drops MixColumns)
```

```
AES-128:  128-bit block, 128-bit key, 10 rounds.
          one AddRoundKey(K0), then 9 full rounds, then a final round
          (SubBytes, ShiftRows, AddRoundKey — NO MixColumns).
```

One plain sentence: **substitute each byte (confusion), shuffle and blend them
(diffusion), XOR in a round key — repeat ten times.** The S-box is the only
nonlinear piece; without it the whole cipher would be linear over GF(2) and
trivially breakable.

---

### Glossary (plain English — refer back any time)

| Term | Plain meaning |
|---|---|
| **block** | The fixed-size data unit AES works on = 128 bits = 16 bytes, arranged as a 4×4 **column-major** matrix called the *state*. |
| **state** | The 4×4 byte matrix AES transforms. Filled column by column: bytes 0–3 = column 0, 4–7 = column 1, … |
| **key** | AES-128 key = 128 bits = 16 bytes. |
| **round key** | A 16-byte key derived from the master key; one is XORed in (AddRoundKey) before round 1 and after every round. |
| **S-box** | The 256-byte substitution table. Nonlinear. Built from a GF(2⁸) inverse + an affine map. |
| **GF(2⁸)** | The finite field of 256 elements AES lives in. Bytes **add** by XOR; they **multiply** modulo `x⁸+x⁴+x³+x+1` (0x11b). MixColumns multiplies here. |
| **confusion** | The ciphertext should depend on the key in a complex, non-obvious way. Provided by the S-box. |
| **diffusion** | Changing 1 input bit should change MANY output bits. Provided by ShiftRows + MixColumns (avalanche). |
| **round** | SubBytes → ShiftRows → MixColumns → AddRoundKey. AES-128 uses 10 (the last drops MixColumns). |
| **key schedule** | The algorithm expanding the 128-bit key into 11 round keys (Rijndael key expansion). |

---

## 1. GF(2⁸) — the field AES multiplies in

AES does all its math in **GF(2⁸)**: 256 elements, where **addition is XOR**
and **multiplication** is polynomial multiply reduced modulo the AES polynomial
`0x11b` (= x⁸+x⁴+x³+x+1). The primitive is `xtime(a) = a·2` (left-shift, and
if the top bit overflows, XOR in `0x1b`). From `aes_spn.py` **Section A**:

```
xtime(0x01) = 0x02     xtime(0x57) = 0xae     xtime(0x80) = 0x1b     xtime(0xff) = 0xe5

products (used by MixColumns and S-box construction):
  0x57 * 0x83 = 0xc1
  0x02 * 0x57 = 0xae
  0x03 * 0x57 = 0xf9

[check] 0x57 * 0x83 == 0xc1 (FIPS-197 Appendix) ?  True

INVERSES (the heart of the S-box): inverse(a) * a == 1, with inverse(0)=0:
  inverse(0x53) = 0xca   -> 0x53 * 0xca = 0x01  (=1 ✓)
  inverse(0x57) = 0xbf   -> 0x57 * 0xbf = 0x01  (=1 ✓)
```

```python
def xtime(a):                 # multiply by x (=2) in GF(2^8)
    a <<= 1
    if a & 0x100: a ^= 0x11b  # reduce mod the AES polynomial
    return a & 0xFF

def gmul(a, b):               # Russian-peasant multiply using xtime
    res = 0
    for _ in range(8):
        if b & 1: res ^= a
        a = xtime(a); b >>= 1
    return res
```

> These two functions are the **entire** arithmetic foundation of AES —
> MixColumns, the S-box, and the key schedule all reduce to `gmul` and XOR.

---

## 2. The S-box, generated from scratch (confusion)

The S-box is the **only nonlinear** part of AES. FIPS-197 defines it as:

```
sbox[b] = affine( inverse_gf28(b) )      (with inverse(0) = 0)
```

Two steps: take the multiplicative inverse in GF(2⁸), then apply an affine
transformation (`b ^ rotl(b,1) ^ rotl(b,2) ^ rotl(b,3) ^ rotl(b,4) ^ 0x63`).
From `aes_spn.py` **Section B**:

```
  b    | inverse | affine | sbox[b]
  0x00 |   0x00   |  0x63  |   0x63
  0x01 |   0x01   |  0x7c  |   0x7c
  0x53 |   0xca   |  0xed  |   0xed
  0xff |   0x1c   |  0x16  |   0x16

spot-checks against the FIPS-197 table:
  sbox[0x00] = 0x63 (expected 0x63)  ✓
  sbox[0x53] = 0xed (expected 0xed)  ✓
  sbox[0xff] = 0x16 (expected 0x16)  ✓

[check] generated S-box matches FIPS-197 at all spot-checks ?  True
[check] S-box is a bijection (permutation of 0..255) ?  True
```

> The inverse+affine construction has **no simple algebraic shortcut**, which is
> exactly what **confusion** needs: the ciphertext's dependence on the key
> becomes opaque. Being a bijection guarantees decryption is possible.

---

## 3. ShiftRows + MixColumns (diffusion)

**ShiftRows** cyclically left-shifts row `r` by `r` positions — scattering each
column's bytes across all columns. **MixColumns** then matrix-multiplies each
*column* by the fixed circulant matrix `[2 3 1 1; 1 2 3 1; 1 1 2 3; 3 1 1 2]`
over GF(2⁸). From `aes_spn.py` **Section C**:

```
starting state:
    00 10 20 30
    40 50 60 70
    80 90 a0 b0
    c0 d0 e0 f0

ShiftRows (row r left-rotates r):
    00 10 20 30
    50 60 70 40
    a0 b0 80 90
    f0 c0 d0 e0
[check] row0..3 start 00,50,a0,f0 ?  True

MixColumns column 0 = [0x00, 0x50, 0xa0, 0xf0]:
  out[0] = 2*0x00 ^ 3*0x50 ^ 1*0xa0 ^ 1*0xf0 = ...
  (each output byte is a GF(2^8) blend of all 4 input bytes)

[check] inv_mix_columns(mix_columns(state)) == state ?  True   (verified)
```

```python
def shift_rows(s):
    return [[s[r][(c + r) % 4] for c in range(4)] for r in range(4)]

def mix_columns(s):       # each column * the fixed matrix over GF(2^8)
    for c in range(4):
        col = [s[r][c] for r in range(4)]
        for r in range(4):
            out[r][c] = gmul(MIX[r][0],col[0]) ^ gmul(MIX[r][1],col[1]) ...
```

> One changed input byte flips, on average, **half** of the 4 output bytes in
> its column. Combined with ShiftRows, this spreads 1 byte across the **whole
> block within 2 rounds** — the avalanche that makes AES secure.

---

## 4. The key schedule (128-bit key → 11 round keys)

AES-128 needs **44 four-byte words** (4 words per round key × 11 round keys).
The first 4 words are the key; each later word `w[i]` is
`w[i-4] ^ w[i-1]`, except every 4th word gets `RotWord → SubWord → ^Rcon`
first. The round constants `Rcon` (powers of `x` in GF(2⁸)) break key symmetry.
From `aes_spn.py` **Section D**:

```
master key = 2b 7e 15 16 28 ae d2 a6 ab f7 15 88 09 cf 4f 3c

Round constants Rcon: 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36

i  | operation                            | word
0  | (from key)                           | 2b 7e 15 16
...
4  | w[i-4] ^ SubWord(RotWord(w[i-1])) ^ Rcon | a0 fa fe 17
5  | w[i-4] ^ w[i-1]                       | 88 54 2c b1
...

the 11 round keys:
  K0  = 2b 7e 15 16 28 ae d2 a6 ab f7 15 88 09 cf 4f 3c
  K1  = a0 fa fe 17 88 54 2c b1 23 a3 39 39 2a 6c 76 05
  ...
  K10 = d0 14 f9 a8 c9 ee 25 89 e1 3f 0c c8 b6 63 0c a6

[check] K0 == master key AND K1 == a0fafe17 88542cb1 23a33939 2a6c7605 (FIPS-197) ?  True
```

> `AddRoundKey` (XOR the round key into the state) is the **only** step that
> uses the key — and it's just the XOR cipher from [`XOR_CIPHER.md`](./XOR_CIPHER.md)
> applied 11 times. The key schedule exists so each round mixes in a
> *different*, key-dependent 16 bytes.

---

## 5. One full round, step by step (FIPS-197 Appendix B)

The official FIPS-197 test vector, traced through round 1. From `aes_spn.py`
**Section E** (key `2b7e1516…`, plaintext `3243f6a8…`):

```
input state:                 after AddRoundKey(K0)  (plaintext ^ K0):
    32 88 31 e0                  19 a0 9a e9
    43 5a 31 37                  3d f4 c6 f8
    f6 30 98 07                  e3 e2 8d 48
    a8 8d a2 34                  be 2b 2a 08

ROUND 1: SubBytes -> ShiftRows -> MixColumns -> AddRoundKey(K1)

Step 1 - SubBytes (S-box = confusion):     Step 2 - ShiftRows (row r ←r):
    d4 e0 b8 1e                                d4 e0 b8 1e
    27 bf b4 41                                bf b4 41 27
    11 98 5d 52                                5d 52 11 98
    ae f1 e5 30                                30 ae f1 e5

Step 3 - MixColumns (GF(2^8) mix):         Step 4 - AddRoundKey(K1):
    04 e0 48 28                                a4 68 6b 02
    66 cb f8 06                                9c 9f 5b 6a
    81 19 d3 26                                7f 35 ea 50
    e5 9a 7a 4c                                f2 2b 43 49

state after round 1 = a4 9c 7f f2 68 9f 35 2b 6b 5b ea 43 02 6a 50 49
[check] round-1 state == a49c7ff2 689f352b 6b5bea43 026a5049 (FIPS-197) ?  True
```

> Watch each column's bytes **scatter** (ShiftRows) then **blend** (MixColumns):
> after one round a byte from any cell has already influenced every column.
> After a few more rounds the diffusion is total.

---

## 6. Full AES-128 — verified against FIPS-197

Run all 10 rounds. The plaintext becomes unrecognizable ciphertext. From
`aes_spn.py` **Section F**:

```
key        = 2b 7e 15 16 28 ae d2 a6 ab f7 15 88 09 cf 4f 3c
plaintext  = 32 43 f6 a8 88 5a 30 8d 31 31 98 a2 e0 37 07 34
ciphertext = 39 25 84 1d 02 dc 09 fb dc 11 85 97 19 6a 0b 32
expected   = 39 25 84 1d 02 dc 09 fb dc 11 85 97 19 6a 0b 32   (FIPS-197 Appendix B)

[check] AES-128(PT, KEY) == FIPS-197 Appendix B ciphertext ?  True
```

```python
def aes128_encrypt(plaintext, key):
    round_keys = key_expansion(key)
    state = bytes_to_state(plaintext)
    state = add_round_key(state, round_keys[0])
    for rnd in range(1, 11):
        state = sub_bytes(state)
        state = shift_rows(state)
        if rnd != 10: state = mix_columns(state)   # last round skips it
        state = add_round_key(state, round_keys[rnd])
    return state_to_bytes(state)
```

---

## 7. Why AES is secure — avalanche (confusion + diffusion)

Flip **one bit** of the plaintext and watch the ciphertext avalanche. From
`aes_spn.py` **Section G**:

```
plaintext A = 32 43 f6 a8 88 5a 30 8d 31 31 98 a2 e0 37 07 34
plaintext B = 33 43 f6 a8 88 5a 30 8d 31 31 98 a2 e0 37 07 34   (bit 0 flipped)

ciphertext A = 39 25 84 1d 02 dc 09 fb dc 11 85 97 19 6a 0b 32
ciphertext B = 8c 55 eb 94 df ea d5 c4 fa 78 df 03 44 bf 0c d2

bits that differ in the ciphertext = 68 / 128
[check] avalanche >= 50 bits (confusion + diffusion working) ?  True
```

> A 1-bit plaintext change flips **~half** the 128 ciphertext bits. After a few
> rounds the diffusion is total: each output bit depends on every input bit
> (diffusion) and the key's influence is smeared by the S-box (confusion).
> Differential & linear cryptanalysis need `> 2¹⁰⁰` chosen texts to attack 4+
> rounds — far beyond brute force of the `2¹²⁸` key space.

---

## 8. When to use AES (and the modes that chain blocks)

AES is a **128-bit block cipher**: it maps one 16-byte block to one 16-byte
block. Real messages are bigger, so you wrap it in a **mode**. From
`aes_spn.py` **Section H**:

| mode | how it works | security | when to use |
|---|---|---|---|
| **AES-GCM** | counter + auth tag | confidential + integrity | TLS 1.3, HTTPS, SSH (the default AEAD) |
| **AES-CTR** | encrypt a counter | confidential (no integrity) | turns AES into a keystream → XOR 🔗 |
| **AES-CBC** | chain blocks via XOR | confidential (needs MAC) | legacy TLS, older disk encryption |
| **AES-XTS** | tweak per sector | confidential | full-disk encryption (BitLocker, FileVault) |
| **raw AES** | 1 block | **NOT for messages** | the building block; never use alone |

> **Rule of thumb:** use **AES-GCM** (AEAD) for confidentiality + integrity.
> Never use raw AES on data (ECB leaks patterns), and never roll your own mode.
> AES-CTR is *literally* "XOR with an AES-derived keystream" — the bridge to
> [`XOR_CIPHER.md`](./XOR_CIPHER.md). 🔗

---

## 9. Gold check

The `aes_spn.html` page rebuilds the S-box (inverse+affine), the key schedule,
one full round, and the complete AES-128 encrypt **in JS** on the exact same
`(key, plaintext)` as `aes_spn.py`, and verifies every value matches. From
`aes_spn.py` **Section I**:

```
gold key        = 2b 7e 15 16 28 ae d2 a6 ab f7 15 88 09 cf 4f 3c
gold plaintext  = 32 43 f6 a8 88 5a 30 8d 31 31 98 a2 e0 37 07 34
gold round key K1  = a0 fa fe 17 88 54 2c b1 23 a3 39 39 2a 6c 76 05
gold state-after-round-1 = a4 9c 7f f2 68 9f 35 2b 6b 5b ea 43 02 6a 50 49
gold ciphertext = 39 25 84 1d 02 dc 09 fb dc 11 85 97 19 6a 0b 32

[check] round-1 matches FIPS-197 ?  True
[check] ciphertext matches FIPS-197 Appendix B ?  True

gold S-box:  sbox[0x00]=0x63  sbox[0x01]=0x7c  sbox[0x53]=0xed  sbox[0xff]=0x16
```

---

### References

- Daemen, J. & Rijmen, V. (2002), *The Design of Rijndael: AES — The Advanced
  Encryption Standard*. The design rationale (wide-trail strategy = strong
  diffusion defeating differential/linear cryptanalysis).
- NIST (2001), **FIPS-197**, *Advanced Encryption Standard*. Defines AES; the
  test vector and S-box construction in this guide are verified against it.
- 🔗 [`XOR_CIPHER.md`](./XOR_CIPHER.md) — AES-CTR/GCM reduce to "XOR with an
  AES-derived keystream"; the AddRoundKey step *is* the XOR cipher.
