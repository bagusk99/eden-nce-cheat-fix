#!/usr/bin/env python3
"""Cheat-Engine-style memory scanner for Eden on Android (TUI). See USAGE.md.

Scans the game running in the debuggable Eden build (run-as needs it), finds pointer
chains from `main`, and writes Atmosphere cheat files into Eden's load/ folder.
"""
import curses, glob, json, os, shlex, struct, subprocess, sys
from pathlib import Path

DEBUG_PKG = os.environ.get('EDENSCAN_PKG', 'dev.eden.eden_emulator.redfox.relWithDebInfo')
RELEASE_PKG = DEBUG_PKG.removesuffix('.relWithDebInfo')
HERE = Path(__file__).resolve().parent
STATE = HERE / '.edenscan.json'
TYPES = ['u32', 'f32', 'u16', 'u8', 'u64', 'f64']
FMT = {'u8': '<B', 'u16': '<H', 'u32': '<I', 'u64': '<Q', 'f32': '<f', 'f64': '<d'}
PTR_MAXOFF, PTR_DEPTH = 0x1000, 4


class Fail(Exception):
    pass


def adb(*args):
    r = subprocess.run(['adb', *args], capture_output=True, text=True)
    if r.returncode:
        raise Fail((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout).strip() else 'adb failed')
    return r.stdout


def es(*args):
    return adb('shell', f'run-as {DEBUG_PKG} ./es ' + ' '.join(map(str, args))).strip()


def run_as(cmd):
    return adb('shell', f'run-as {DEBUG_PKG} {cmd}')


def build_and_push():
    src, out = HERE / 'es.c', HERE / 'es'
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        cc = sorted(glob.glob(os.path.expanduser(
            '~/Android/Sdk/ndk/*/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android3*-clang')))
        cc = os.environ.get('EDENSCAN_CC') or (cc[-1] if cc else None)
        if not cc:
            sys.exit('Android NDK clang not found: install the NDK or set EDENSCAN_CC')
        subprocess.run([cc, '-O2', '-static', str(src), '-o', str(out)], check=True)
    adb('push', str(out), '/data/local/tmp/es')
    run_as('cp /data/local/tmp/es ./es')


def eden_files(pkg):
    return f'/sdcard/Android/data/{pkg}/files'


def load_state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save_state(st):
    STATE.write_text(json.dumps(st, indent=1))


def encode(typ, text):
    v = float(text) if typ[0] == 'f' else int(text, 0)
    return int.from_bytes(struct.pack(FMT[typ], v).ljust(8, b'\0'), 'little')


def cheat_text(name, chain, typ, value):
    """Atmosphere cheat that writes `value` at main+X -> +o1 ... -> +oN."""
    w, raw = int(typ[1:]) // 8, encode(typ, value)
    x, offs = chain[0], chain[1:]
    lines = [f'[{name}]']
    if not offs:  # static address inside main: opcode 0 with RF = 0 as offset register
        val = f'{raw >> 32:08X} {raw & 0xFFFFFFFF:08X}' if w == 8 else f'{raw:08X}'
        lines += ['400F0000 00000000 00000000', f'0{w}0F0000 {x:08X} {val}']
    else:
        lines.append(f'580F0000 {x:08X}')
        lines += [f'580F1000 {o:08X}' for o in offs[:-1]]
        if offs[-1]:
            lines.append(f'780F0000 {offs[-1]:08X}')
        lines.append(f'6{w}0F0000 {raw >> 32:08X} {raw & 0xFFFFFFFF:08X}')
    return '\n'.join(lines) + '\n'


class App:
    def __init__(self, scr):
        self.scr, self.st = scr, load_state()
        self.typ = self.st.get('type', 'u32')
        self.results = self.st.get('results')  # count, None = no scan yet
        self.chains = self.st.get('chains')
        self.view = 'chains' if self.chains else 'results'
        self.rows, self.msg = [], ''
        self.detect()

    def save(self):
        self.st.update(type=self.typ, results=self.results, chains=self.chains)
        save_state(self.st)

    # --- detection -------------------------------------------------------
    def detect(self):
        self.pid = adb('shell', f'pidof {DEBUG_PKG}; true').strip()
        if not self.pid:
            raise Fail(f'{DEBUG_PKG} not running: start the game in Eden debug first')
        if self.st.get('pid') != self.pid:  # new boot: old scan addresses are meaningless
            self.st['pid'], self.results = self.pid, None
        _, main, end, self.bid = es('info', self.pid).split()
        self.main, self.main_end = int(main, 16), int(end, 16)
        titles = self.st.setdefault('titles', {})
        if self.bid not in titles:
            hits = {p.split('/load/')[1].split('/')[0] for pkg in (DEBUG_PKG, RELEASE_PKG) for p in adb(
                'shell', f'find {eden_files(pkg)}/load -ipath "*/cheats/{self.bid}.txt" 2>/dev/null; true').split('\n') if p}
            tid = hits.pop() if len(hits) == 1 else self.ask(f'TitleID for BuildID {self.bid} (see Eden game properties): ')
            if len(tid) != 16:
                raise Fail('TitleID must be 16 hex chars')
            titles[self.bid] = tid.upper()
            self.save()
        self.tid = titles[self.bid]

    # --- UI helpers ------------------------------------------------------
    def ask(self, prompt, default=''):
        h, w = self.scr.getmaxyx()
        self.scr.move(h - 1, 0); self.scr.clrtoeol()
        self.scr.addstr(h - 1, 0, prompt[:w - 1])
        curses.echo(); curses.curs_set(1)
        s = self.scr.getstr(h - 1, min(len(prompt), w - 2)).decode().strip()
        curses.noecho(); curses.curs_set(0)
        return s or default

    def busy(self, text):
        self.msg = text
        self.draw()
        self.scr.refresh()

    def draw(self):
        s = self.scr
        s.erase()
        h, w = s.getmaxyx()
        put = lambda y, t, a=0: y < h and s.addstr(y, 0, t[:w - 1], a)
        put(0, f' Eden Scan   Title {self.tid}  Build {self.bid}  pid {self.pid}', curses.A_REVERSE)
        put(1, f' main {self.main:x}-{self.main_end:x}   type {self.typ}   '
               f'results {"-" if self.results is None else self.results}   chains {"-" if self.chains is None else self.chains}')
        put(3, ' # ' + ('address        old          now          where' if self.view == 'results' else 'pointer chain (main+X -> +off ...)'), curses.A_BOLD)
        for i, r in enumerate(self.rows[:h - 8]):
            put(4 + i, f'{i:2} {r}')
        put(h - 4, ' ' + self.msg)
        put(h - 3, ' [s]scan [n]exact [+]inc [-]dec [c]changed [u]unchanged [t]type [l]list results/chains', curses.A_DIM)
        put(h - 2, ' [p]pointer scan [v]validate [i]inject cheat [r]refresh [q]quit', curses.A_DIM)

    def refresh_rows(self):
        self.rows = []
        if self.view == 'results' and self.results:
            for line in es('peek', self.pid, self.typ, 'r.bin', 40).splitlines():
                p = line.split()
                self.rows.append(f'{p[0]:<14} {p[1]:<12} {p[2]:<12} {p[3]}' if len(p) == 4 else line)
        elif self.view == 'chains' and self.chains:
            for line in run_as('head -40 p.txt').splitlines():
                x, *offs = line.split()
                self.rows.append(f'main+{x.upper()} ' + ' '.join(f'-> +{o.upper()}' for o in offs))

    # --- commands --------------------------------------------------------
    def scan(self):
        v = self.ask(f'scan {self.typ} value (? = unknown): ')
        if not v:
            return
        self.busy('scanning...')
        self.results = int(es('scan', self.pid, self.typ, shlex.quote(v), 'r.bin'))
        self.view, self.msg = 'results', f'first scan: {self.results}' + (' (snapshot)' if v == '?' else '')

    def next(self, mode):
        if self.results is None:
            self.msg = 'no scan yet: press s'
            return
        v = self.ask(f'next {self.typ} value: ') if mode == 'eq' else '0'
        if not v:
            return
        self.busy('scanning...')
        self.results = int(es('next', self.pid, self.typ, mode, shlex.quote(v), 'r.bin', 'r.tmp'))
        run_as('mv r.tmp r.bin')
        self.view, self.msg = 'results', f'{mode}: {self.results} left'

    def pointer_scan(self):
        if not self.rows or self.view != 'results':
            self.msg = 'need scan results on screen (l to switch)'
            return
        i = int(self.ask('result # to pointer-scan [0]: ', '0'))
        addr = self.rows[i].split()[0]
        depth = int(self.ask(f'max depth [{PTR_DEPTH}]: ', str(PTR_DEPTH)))
        self.busy(f'pointer scan {addr} ...')
        self.chains = int(es('ptr', self.pid, addr, f'{PTR_MAXOFF:x}', depth, 'p.txt'))
        self.view = 'chains'
        self.msg = f'{self.chains} chains. Restart the game, then v with the current value'

    def validate(self):
        if not self.chains:
            self.msg = 'no chains: p first'
            return
        v = self.ask(f'current {self.typ} value: ')
        if not v:
            return
        self.busy('validating...')
        self.chains = int(es('val', self.pid, self.typ, shlex.quote(v), 'p.txt', 'p.tmp'))
        run_as('mv p.tmp p.txt')
        self.view, self.msg = 'chains', f'{self.chains} chains still valid'

    def inject(self):
        if not self.chains or self.view != 'chains':
            self.msg = 'need chains on screen: p (and v) first'
            return
        i = int(self.ask('chain # [0]: ', '0'))
        chain = [int(t, 16) for t in run_as(f'sed -n {i + 1}p p.txt').split()]
        name = self.ask('cheat name: ')
        value = self.ask(f'value to write ({self.typ}): ')
        where = self.ask('install to [r]elease [d]ebug [b]oth [b]: ', 'b')
        if not name or not value or '/' in name:
            self.msg = 'cancelled'
            return
        pkgs = {'r': [RELEASE_PKG], 'd': [DEBUG_PKG]}.get(where, [RELEASE_PKG, DEBUG_PKG])
        txt = HERE / '.cheat.txt'
        txt.write_text(cheat_text(name, chain, self.typ, value))
        for pkg in pkgs:
            d = f'{eden_files(pkg)}/load/{self.tid}/{name}/cheats'
            adb('shell', f'mkdir -p {shlex.quote(d)}')
            adb('push', str(txt), f'{d}/{self.bid}.txt')
        self.msg = f'"{name}" installed ({", ".join(p.rsplit(".", 1)[-1] for p in pkgs)}): restart the game'

    def loop(self):
        curses.curs_set(0)
        keys = {'s': self.scan, 'n': lambda: self.next('eq'), '+': lambda: self.next('inc'),
                '-': lambda: self.next('dec'), 'c': lambda: self.next('chg'), 'u': lambda: self.next('same'),
                'p': self.pointer_scan, 'v': self.validate, 'i': self.inject, 'r': self.detect}
        self.refresh_rows()
        while True:
            self.draw()
            k = chr(self.scr.getch())
            try:
                if k == 'q':
                    return
                if k == 't':
                    self.typ = TYPES[(TYPES.index(self.typ) + 1) % len(TYPES)]
                    self.results, self.msg = None, f'type {self.typ}: new scan needed'
                elif k == 'l':
                    self.view = 'chains' if self.view == 'results' else 'results'
                elif k in keys:
                    keys[k]()
                self.save()
                self.refresh_rows()
            except (Fail, ValueError, IndexError) as e:
                self.msg = f'error: {e}'


def main():
    if '--test' in sys.argv:
        assert cheat_text('G', [0x6A9A398, 0x248, 0x2E8], 'u32', '9999') == (
            '[G]\n580F0000 06A9A398\n580F1000 00000248\n780F0000 000002E8\n640F0000 00000000 0000270F\n')
        assert cheat_text('S', [0x100], 'f32', '1.5').endswith('040F0000 00000100 3FC00000\n')
        assert cheat_text('Z', [0x10, 0], 'u64', '1').endswith('580F0000 00000010\n680F0000 00000000 00000001\n')
        print('ok')
        return
    try:
        build_and_push()
        curses.wrapper(lambda scr: App(scr).loop())
    except Fail as e:
        sys.exit(f'error: {e}')


if __name__ == '__main__':
    main()
