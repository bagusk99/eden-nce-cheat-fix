#!/usr/bin/env python3
"""Detect Eden's NCE main-offset bug for one game build, then fix that build's cheats.

  nce_detect.py install <TitleID> <BuildID>   push a read-only detector cheat
  -> run the game ~10s in NCE mode, then close it (Eden flushes the log on exit)
  nce_detect.py read    <TitleID> <BuildID>   parse Eden's log; if confirmed: remove detector,
                                              save the shift on the phone and run `fix`
  nce_detect.py fix     <TitleID> <BuildID> [shift_hex]   back up + shift every not-yet-shifted
                                              cheat for that build (default: saved shift)
  nce_detect.py --test

TitleID / BuildID may be a suffix (e.g. ...E000 or E000): matched against what's on the
phone (load/ folders, cheat file names). No match or more than one -> error.

How: under NCE, Eden may put a patch page in front of `main` while the cheat engine still
uses the old base. That page starts with `B +shift` (branch into the real code), so
reading [main+0] tells the shift. The real module has a small MOD0 offset in its 2nd word,
which we use to confirm. A shift past 0xF000 can't be confirmed by this detector.
"""
import re, shlex, subprocess, sys, tempfile, time
from pathlib import Path

from nce_shift import convert

DETECT_DIR = 'zz NCE Detect'
MARKER = '.nce_shifted'


def adb(*args, check=True):
    return subprocess.run(['adb', *args], capture_output=True, text=True, check=check).stdout


def sh(cmd):
    return adb('shell', cmd)


def eden_root():
    pkgs = [l.split(':', 1)[1] for l in sh('pm list packages dev.eden').split() if 'emulator' in l]
    if not pkgs:
        sys.exit('Eden not installed (or adb not connected)')
    return f'/sdcard/Android/data/{pkgs[0]}/files'


def resolve(arg, candidates, what):
    """Full 16-hex id as-is; otherwise the single candidate ending with it."""
    a = arg.lstrip('.').upper()
    if len(a) == 16:
        return a
    hits = sorted({c.upper() for c in candidates if c.upper().endswith(a)})
    if len(hits) != 1:
        sys.exit(f'{what} ...{a}: ' + (f'ambiguous: {", ".join(hits)}' if hits else 'no match'))
    return hits[0]


def title_ids(root):
    return sh(f'ls {shlex.quote(f"{root}/load")} 2>/dev/null; true').split()


def build_ids(root, tid):
    out = sh(f'find {shlex.quote(f"{root}/load/{tid}")} -ipath "*/cheats/*.txt" 2>/dev/null; true')
    return [p.rsplit('/', 1)[1][:-4] for p in out.splitlines() if p]


def detector_text(tid, bid):
    # FFF8I0Ma aaaaaaaa: DebugLog, 8 bytes, id I, main-relative address. Logs main+0x0000..0xF000.
    ops = '\n'.join(f'FFF8{k:X}000 {k * 0x1000:08X}' for k in range(16))
    return f'[NCE detect TID={tid} BID={bid}]\n\n[NCE detect read-only]\n{ops}\n'


def looks_like_module_start(v):
    """Real NSO text: 2nd word is the MOD0 header offset (small, 4-aligned, non-zero)."""
    mod0 = v >> 32
    return 0 < mod0 < 0x1000 and mod0 % 4 == 0


def analyse(vals):
    """vals[k] = u64 read at cheat-engine main + k*0x1000. Returns (shift, confirmed, why)."""
    v0 = vals[0]
    if looks_like_module_start(v0):
        return 0, True, 'main+0 is the real module start: no shift, cheats work as-is'
    w0 = v0 & 0xFFFFFFFF
    if w0 & 0xFC000000 != 0x14000000:
        return None, False, f'main+0 = {v0:016X} is neither module start nor a branch'
    shift = (w0 & 0x03FFFFFF) * 4
    if shift % 0x1000 or shift // 0x1000 >= len(vals):
        return shift, False, f'branch says +{shift:#x}, outside the detector range'
    ok = looks_like_module_start(vals[shift // 0x1000])
    return shift, ok, f'main+0 = B +{shift:#x}; real module start {"confirmed" if ok else "NOT found"} there'


def parse_log(text):
    """Last complete run of DebugLog ids 0..F in order -> list of 16 values."""
    entries = re.findall(r"DebugLog: ID '([0-9A-F])' Value '([0-9A-F]+)'", text)
    for end in range(len(entries), 15, -1):
        block = entries[end - 16:end]
        if [int(i, 16) for i, _ in block] == list(range(16)):
            return [int(v, 16) for _, v in block]
    return None


def saved_shift_path(root, tid, bid):
    # lives in load/<tid>/ root: Eden only reads files there named cheat_*, so it's ignored
    return f'{root}/load/{tid}/.nce_shift_{bid}'


def cheat_files(root, tid, bid):
    out = sh(f'find {shlex.quote(f"{root}/load/{tid}")} -ipath "*/cheats/{bid}.txt" 2>/dev/null; true')
    return [p for p in out.splitlines() if p and f'/{DETECT_DIR}/' not in p]


def cmd_install(root, tid, bid):
    d = f'{root}/load/{tid}/{DETECT_DIR}/cheats'
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
        f.write(detector_text(tid, bid))
    sh(f'mkdir -p {shlex.quote(d)}')
    adb('push', f.name, f'{d}/{bid}.txt')
    print(f'detector installed: {d}/{bid}.txt')
    print('now: CPU backend = NCE, start the game, wait ~10s, close the game, then run `read`')


def cmd_read(root, tid, bid):
    logs = ''.join(sh(f'cat {shlex.quote(f"{root}/log/{n}")} 2>/dev/null; true')
                   for n in ('eden_log.txt.old.txt', 'eden_log.txt'))
    vals = parse_log(logs)
    if vals is None:
        sys.exit('no detector output in the log (game run long enough? closed it? NCE mode? right BuildID?)')
    shift, ok, why = analyse(vals)
    print(why)
    if not ok:
        sys.exit('not confirmed: detector left in place, nothing shifted')
    sh(f'rm -rf {shlex.quote(f"{root}/load/{tid}/{DETECT_DIR}")} && '
       f'echo {shift:X} > {shlex.quote(saved_shift_path(root, tid, bid))}')
    print('detector removed, shift saved')
    if shift:
        cmd_fix(root, tid, bid, shift)


def cmd_fix(root, tid, bid, by):
    stamp = time.strftime('%Y%m%d-%H%M%S')
    backup = f'/sdcard/Download/nce_backup/{tid}-{stamp}'
    files = cheat_files(root, tid, bid)
    if not files:
        sys.exit(f'no cheats for build {bid} under load/{tid}')
    with tempfile.TemporaryDirectory() as tmp:
        for remote in files:
            cheats_dir = remote.rsplit('/', 1)[0]
            name = remote.split('/load/', 1)[1]
            if sh(f'[ -e {shlex.quote(cheats_dir + "/" + MARKER)} ] && echo y; true').strip() == 'y':
                print(f'skip (already shifted): {name}')
                continue
            local = Path(tmp, 'c.txt')
            adb('pull', remote, str(local))
            new, n = convert(local.read_text(encoding='utf-8'), by)   # raises on unknown opcodes
            sh(f'mkdir -p {shlex.quote(f"{backup}/{Path(name).parent}")} && '
               f'cp {shlex.quote(remote)} {shlex.quote(f"{backup}/{name}")}')
            local.write_text(new, encoding='utf-8')
            adb('push', str(local), remote)
            sh(f'echo {by:X} > {shlex.quote(cheats_dir + "/" + MARKER)}')
            print(f'{n:3} opcodes shifted: {name}')
    print(f'backup: {backup}')


def _test():
    ot2 = [0xF90007FE14000400, 0x0000000800000000] + [0] * 14     # measured on OT2, Eden ceadc10
    assert analyse(ot2)[:2] == (0x1000, True)
    clean = [0x0000000800000000] + [0] * 15
    assert analyse(clean)[:2] == (0, True)
    assert analyse([0x14000400] + [0] * 15)[:2] == (0x1000, False)  # branch but no module there
    log = ''.join(f"x DebugLog: ID '{k:X}' Value '{v:016X}'\n" for k, v in enumerate(ot2))
    assert parse_log("x DebugLog: ID '3' Value '00'\n" + log * 2) == ot2
    assert detector_text('T', 'B').splitlines()[4] == 'FFF81000 00001000'
    assert convert(detector_text('T', 'B'), 0)[1] == 16                # all 16 parse as main-relative
    ids = ['0100A3501946E000', '0100A3501946F001', '01006C300E9F0000']
    assert resolve('...E000', ids, 'T') == '0100A3501946E000'
    assert resolve('f001', ids, 'T') == '0100A3501946F001'
    assert resolve('0100ABCDABCDABCD', ids, 'T') == '0100ABCDABCDABCD'   # full id: no lookup
    for bad in ('0', 'FFFF'):                                              # ambiguous / none
        try:
            resolve(bad, ids, 'T'); assert False
        except SystemExit:
            pass
    print('ok')


if __name__ == '__main__':
    if sys.argv[1:] == ['--test']:
        _test()
        sys.exit()
    if len(sys.argv) < 4 or sys.argv[1] not in ('install', 'read', 'fix'):
        sys.exit(__doc__)
    cmd = sys.argv[1]
    root = eden_root()
    tid = resolve(sys.argv[2], title_ids(root), 'TitleID')
    bid = resolve(sys.argv[3], build_ids(root, tid), 'BuildID')
    print(f'{tid} / {bid}')
    if cmd == 'install':
        cmd_install(root, tid, bid)
    elif cmd == 'read':
        cmd_read(root, tid, bid)
    else:
        saved = sh(f'cat {shlex.quote(saved_shift_path(root, tid, bid))} 2>/dev/null; true').strip()
        by = sys.argv[4] if len(sys.argv) > 4 else saved
        if not by:
            sys.exit('no saved shift for this build: run install + read first')
        if int(by, 16) == 0:
            sys.exit('saved shift is 0: cheats for this build work as-is')
        cmd_fix(root, tid, bid, int(by, 16))
