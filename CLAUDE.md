# Notes for Claude

## Octopath Traveler II v1.1.1 (TitleID 0100A3501946E000, BuildID 0D9649011312F62E)

- Character stat block: `[[[main+0x6A9A398]+0x248]+0x708]+0xB0`, 40 characters, stride 0xF0
  (cheat loop: 14 u32 = 0x38, then `780F0000 000000B8`).
- The 14 u32 at the block start are **bonus values**, normally 0, fed into the game's stat formula.
  Not a plain add: bonus 100..1400 per field gave screen diffs like +130 HP, +720 Phys Atk. Screen
  stats cap at 999. Writing 9999 there = every stat shows the cap.
- Field map (u32 offset from block start), found with 4 bit-coded boots:
  HP 0x00, SP 0x04, (0x08-0x10 unknown), Phys Atk 0x14, Phys Def 0x18, Elem Atk 0x1C,
  Elem Def 0x20, Accuracy 0x24, Evasion 0x28, Critical 0x2C, Speed 0x30, (0x34 unknown).
- Single-stat cheat: start at block+off (`780F0000 000000B0+off`), write, then add
  0xF0 minus bytes written. Example `8 9999 Crit Evasion`: +0xD8, one 8-byte write, +0xE8.
- Crit *rate* is computed in Blueprints; patching it was abandoned. Raising the Critical stat is a
  different thing.

## Eden on the phone

- The running build is usually **debug**: `dev.eden.eden_emulator.redfox.relWithDebInfo`.
  Check with `adb shell cat /proc/<pid>/cmdline`, don't guess from `pidof` output.
- Cheats load only at boot. Debug cheats: tell the user not to save while they're active.
- Report before copying anything to the phone.
