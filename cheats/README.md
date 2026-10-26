# Cheats

Tested on Eden (NCE, Android). Each game folder is `<Game name> [<TitleID>]`. To install, copy a
cheat folder (e.g. `8 9999 Crit Evasion (v1.1.1)`) into
`Android/data/<eden package>/files/load/<TitleID>/`, then enable it under the game's Add-ons.
Eden needs the folder named by the TitleID only, without the game name.

## Octopath Traveler II v1.1.1 (`0100A3501946E000`, build `0D9649011312F62E`)

| Cheat | What it does |
|---|---|
| `00 master code` | Master code (entry hook) fixed for v1.1.1 |
| `Gold 1M` | Gold set to 1,000,000. Tested with `00 master code` enabled |
| `5 999 All Stats (v1.1.1)` | Every stat at the cap, all 40 characters |
| `8 9999 Crit Evasion (v1.1.1)` | Only Critical and Evasion at the cap, other stats normal |

Don't enable both at once. Both write the per-character stat bonus block
(`[[[main+0x6A9A398]+0x248]+0x708]+0xB0`, stride 0xF0). Field offsets, for making other
single-stat cheats: HP 0x00, SP 0x04, Phys Atk 0x14, Phys Def 0x18, Elem Atk 0x1C, Elem Def 0x20,
Accuracy 0x24, Evasion 0x28, Critical 0x2C, Speed 0x30.
