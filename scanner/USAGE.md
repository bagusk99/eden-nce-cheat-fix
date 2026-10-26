# Eden Scan: make your own cheats

A small Cheat Engine for Eden on Android. Scan for a value in the running game, narrow it down,
find a pointer chain from `main` that survives restarts, then install it as a cheat file.
Works for any game, not only Octopath Traveler II.

## Requirements

- Phone on `adb` (`adb devices` lists it).
- A **debuggable** Eden build installed (`relWithDebInfo` variant, package
  `dev.eden.eden_emulator.redfox.relWithDebInfo`). Scanning needs `run-as`, which only works on
  debuggable apps. The cheats it writes also work in the normal (release) build.
  Other package: `export EDENSCAN_PKG=<package>`.
- CPU backend **NCE**.
- Android NDK on the PC (found automatically in `~/Android/Sdk/ndk/*`, or set `EDENSCAN_CC` to an
  `aarch64-linux-android*-clang`). The phone-side helper `es.c` is compiled and pushed at start.
- Python 3, standard library only.

## Start

Open the game in Eden **debug**, then on the PC:

```bash
python3 scanner/edenscan.py
```

TitleID, BuildID and the `main` address are detected automatically. If the game has no cheat
folder yet, you're asked for the TitleID once (Eden: long-press game → properties); it's remembered.

```
 Eden Scan   Title 0100A3501946E000  Build 0D9649011312F62E  pid 15118
 main 1a28249000-1a31414180   type u32   results 12   chains -

 # address        old          now          where
 0 2ee0aeeae8     1100         1100         heap
 ...
 [s]scan [n]exact [+]inc [-]dec [c]changed [u]unchanged [t]type [l]list results/chains
 [p]pointer scan [v]validate [i]inject cheat [r]refresh [q]quit
```

## Keys

| Key | What it does |
|---|---|
| `s` | new scan: type the value, or `?` when you don't know it (snapshot) |
| `n` | next scan: value equals what you type |
| `+` / `-` | next scan: value went up / down |
| `c` / `u` | next scan: value changed / unchanged |
| `t` | value type: u32 → f32 → u16 → u8 → u64 → f64 (resets the scan) |
| `l` | switch the list between scan results and pointer chains |
| `p` | pointer scan from a result (asks result # and max depth) |
| `v` | validate chains after a game restart: type the current value |
| `i` | inject a chain as a cheat (name, value, release/debug/both) |
| `r` | re-detect the game (after a restart) |
| `q` | quit (scan state is kept for next time) |

## Example: gold

1. Gold is 1250 → `s`, `1250`. Tens of thousands of results.
2. Buy something, gold 1100 → `n`, `1100`. Repeat until 1–3 results remain.
3. `p` on the result. You get many candidate chains: most are coincidence.
4. Restart the game, start the tool again (or `r`), then `v` and type the current gold.
   Fake chains break after a restart; the real ones still point at gold.
   Still many? Change gold in game and `v` again, or restart once more and `v`.
5. 1–3 chains left → `i`: name `Gold 9999999`, value `9999999`, `b` (both builds).
6. Restart the game (Eden only loads cheats at boot). Done.

You don't have to rescan after a restart: `v` follows the saved chains and needs only the current value.

## Value without a number (bar, timer…)

`s` with `?`, then change it in game and use `+` / `-` / `c` / `u` to narrow down.
Don't start with `u` straight after `?` (almost everything is unchanged); it's refused above
20 million matches.

## Notes

- Heap addresses (`where = heap`) change every boot: that's why `p` + `v` exist.
  A result marked `main` is static: its chain is just `main+X` and works directly.
- Pointer scan: offsets up to 0x1000 per step, depth 4 by default (Unreal games sometimes need 5–6).
  Each level is capped at 200k pointers; deep levels may miss chains.
- For values in an array of characters/items, the chain points to one entry. For "all
  characters" you need a loop cheat written by hand (see the OT2 `999 All Stats` cheat).
- Don't save the game while a cheat writes weird values unless you want them permanent.
- Read-only: the tool never writes game memory. Cheats are applied by Eden's cheat engine.
