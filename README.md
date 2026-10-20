# eden-nce-cheat-fix

Fix Atmosphere-format cheats that do nothing, or crash the game, on **Eden (Android) with the
NCE CPU backend**.

## Why this exists

Cheats for Switch games are written against the game's `main` module: "write value V at
`main+0x6A54830`". On Eden for Android, the fast CPU backend (**NCE**, native code execution)
sometimes places one page of its own patch code **in front of** `main`, but Eden's cheat engine
still uses the old start address. Every `main+X` address in every cheat then lands
`page size` bytes too early:

- cheats that **read/write data** (HP, gold, items) silently do nothing
- cheats that **write code** (master codes, code caves, hooks) overwrite the wrong instructions
  and crash the game (`SIGILL`)

The same cheats work fine on the JIT backend (Dynarmic), but JIT is often too slow or unstable
on phones. So you're stuck choosing between a playable game and working cheats.

This was found while debugging cheats for Octopath Traveler II: reading `main+0` through the
cheat engine returned `B +0x1000` (a jump over Eden's patch page) instead of the game's real
module header, which sat exactly `0x1000` bytes later.

## What it solves

- **Measures** the shift for a given game build with a harmless, read-only detector cheat,
  instead of guessing. The shift is not a global constant: it can differ per game and per Eden
  version (some games aren't shifted at all).
- **Rewrites** every installed cheat for that build so its `main`-relative addresses point at
  the right place, opcode by opcode. Unknown opcodes abort instead of being guessed at.
- **Backs up** the originals and marks rewritten cheats so running it twice never shifts twice.

Measured so far (Eden nightly `ceadc10`):

| Game | Build ID | Shift |
|---|---|---|
| Octopath Traveler II v1.0.0 / v1.1.1 (`0100A3501946E000`) | `65619A04B8A04B10` / `0D9649011312F62E` | `0x1000` |
| `010032C00AC58000` | `2CDB9B9D70010E88` | `0` (works as-is) |

## Getting cheats

- [Eden Cheats Manager](https://github.com/ChrisA95G/eden-cheats-manager) (EDC): Android app
  that downloads cheats straight into Eden's `load/` folder. Each cheat becomes its own add-on
  you can toggle in Eden.
- [CheatSlips](https://www.cheatslips.com/): large searchable cheat collection, by game and
  build ID.
- [switch-cheats-db](https://github.com/HamletDuFromage/switch-cheats-db): community database
  that many tools pull from.

Cheats are tied to a **build ID** (the cheat file is named `<BuildID>.txt`); a cheat for another
game version will not work. Eden shows the build ID in the game's properties, and EDC shows it
too.

## Requirements

- Phone connected over `adb` (USB or wireless; `adb devices` lists it). If several devices
  are connected, pick one with `export ANDROID_SERIAL=<serial>`.
- Python 3, standard library only.
- Eden (stable or nightly) installed on the phone, cheats already placed in its `load/` folder
  (e.g. with EDC).

## Install

```bash
git clone https://github.com/bagusk99/eden-nce-cheat-fix.git
cd eden-nce-cheat-fix
python3 nce_detect.py --test    # self-test, no phone needed
```

## Usage

```bash
# 1. push the detector (read-only cheat, writes nothing to the game)
python3 nce_detect.py install <TitleID> <BuildID>

# 2. on the phone: CPU backend = NCE, start the game, wait ~10 s, then CLOSE the game
#    (Eden only flushes its log file when the game exits)

# 3. read the result and fix automatically
python3 nce_detect.py read <TitleID> <BuildID>
#    "no shift"      -> cheats work as-is; detector removed, done
#    "... confirmed" -> detector removed, shift saved on the phone, all cheats for that build shifted
#    "not confirmed" -> nothing changed, detector left in place

# later, after installing more cheats for the same build:
python3 nce_detect.py fix <TitleID> <BuildID>
```

Output is marked: `✔` success, `•` skipped, `✘` error (coloured in a terminal).

IDs can be given as a **suffix**; it is matched against what's on the phone (`load/` folders
and cheat file names). No match or more than one match is an error that lists the candidates.

```bash
python3 nce_detect.py fix ...E000 ...F62E      # = 0100A3501946E000 0D9649011312F62E
```

`install` for a build that has no cheat file yet needs the full build ID.

Convert one file by hand (no phone):

```bash
python3 nce_shift.py input.txt output.txt 1000
```

## How it works

### Detector (`nce_detect.py install` / `read`)

The detector is a cheat with 16 `DebugLog` opcodes that read 8 bytes at
`main+0x0000, +0x1000, … +0xF000` and print them to Eden's log. `read` then decides:

1. **`main+0` is the real module start** -> no shift.
   An NSO module starts with a 32-bit word followed by the offset of its `MOD0` header
   (small, multiple of 4).
2. **`main+0` holds `B +X`** (`0x14xxxxxx`) -> that's Eden's patch page, whose first instruction
   jumps into the game code. `X = imm26 × 4` is the shift. It's confirmed only if a real
   module start is found at `main+X`.
3. Anything else -> **not confirmed**; no shift is suggested.

Real example, OT2: `main+0 = F90007FE 14000400` -> `B +0x400×4 = +0x1000`, and
`main+0x1000 = 00000008 00000000` (MOD0 offset 8) -> confirmed.

Once confirmed, the detector folder is deleted, the shift is saved to
`load/<TitleID>/.nce_shift_<BuildID>` (Eden ignores it) and `fix` runs. `fix` without a number
uses that saved shift; `fix <TitleID> <BuildID> <hex>` forces another one.

### Converter (`nce_shift.py`, used by `fix`)

A cheat is a stream of 8-digit hex words. **Line breaks and spaces mean nothing** to the cheat
VM; the first digit of an opcode decides how many words it takes. The converter parses per
opcode (not per line), adds the shift to `main`-relative addresses, and writes one opcode per
line.

| Opcode | Meaning | Shifted when |
|---|---|---|
| `0TMR00AA AAAAAAAA V…` | store static value to memory | `M = 0` (main) |
| `1TMC00AA AAAAAAAA V…` | `if` memory compared to value | `M = 0` |
| `5TMR00AA AAAAAAAA` | load memory into register | `M = 0`, absolute address mode |
| `FFFTI0Ma aaaaaaaa` | debug log from memory | `M = 0` |
| `2…`, `3…`, `4…`, `6…`, `7…`, `8…`, `C0TcS4…` | control flow / registers | never |

**Not** shifted: register-relative addresses (`580F1000 …`), heap addresses (`M = 1`), and the
ARM64 instructions a cheat writes (branches are PC-relative, so they stay correct).

### Safety in `fix`

- Originals are backed up on the phone to `/sdcard/Download/nce_backup/<TitleID>-<time>/`.
- Every rewritten `cheats/` folder gets a `.nce_shifted` marker; later runs skip it.
- Installed more cheats from EDC? Run `fix` again; only unmarked ones are shifted.

## Limitations

- Shifts above `0xF000` are detected but can't be confirmed.
- Rare opcodes (`9…` register arithmetic, `A…` register store, `C1`–`C3`, …) aren't supported
  yet; the converter stops with an error.
- If you switch to the JIT backend, or Eden fixes this bug, shifted cheats become wrong.
  Restore them from the backup.
- Eden runs cheat folders in **alphabetical order**. A master code must run first, so give its
  folder a name like `00 master code`.
