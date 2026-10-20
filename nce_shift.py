"""Shift main-relative addresses in Atmosphere cheat text by Eden's NCE pre-patch page.

Usage: nce_shift.py <in.txt> <out.txt> [shift_hex=1000]   |   nce_shift.py --test
Parses the hex word stream per opcode (line breaks don't matter to the VM), shifts
main-relative addresses, and re-emits one opcode per line. Unknown opcode types abort,
so nothing gets silently mangled.
"""
import re, sys



def opcode_len(w):
    """Number of 32-bit words this opcode consumes."""
    t, T = w[0], int(w[1], 16)
    vw = 2 if T == 8 else 1
    if t in '01':                     # store static / conditional mem: op, addr, value
        return 2 + vw
    if t in '28':                     # end cond / key cond
        return 1
    if t == '3':                      # loop start (2) / loop end (1)
        return 2 if w[1] == '0' else 1
    if t in '46':                     # load reg static / store static to reg addr (64-bit value)
        return 3
    if t in '57':                     # load reg from memory / legacy arithmetic
        return 2
    if w.startswith('C0') and w[5] == '4':   # C0TcS4.. register vs static value
        return 1 + (2 if int(w[2], 16) == 8 else 1)
    if w.startswith('FFF'):           # debug log
        return 2 if w[5] in '02' else 1
    raise ValueError(f'unsupported opcode {w}')


def is_main_rel(op):
    w = op[0]
    if w[0] in '01':
        return w[2] == '0'
    if w[0] == '5':
        return w[2] == '0' and w[4] == '0'
    if w.startswith('FFF'):
        return w[5] == '0' and w[6] == '0'
    return False


def shift(op, by):
    w0 = op[0]
    if w0.startswith('FFF'):
        addr = ((int(w0[7], 16) << 32) | int(op[1], 16)) + by
        return [w0[:7] + f'{addr >> 32:X}', f'{addr & 0xFFFFFFFF:08X}'] + op[2:]
    addr = ((int(w0[6:8], 16) << 32) | int(op[1], 16)) + by
    return [w0[:6] + f'{addr >> 32:02X}', f'{addr & 0xFFFFFFFF:08X}'] + op[2:]


def convert(text, by=0x1000):
    out, n = [], 0
    for line in text.splitlines():
        s = line.strip()
        if not s or s[0] in '[{':
            out.append(line)
            continue
        words = [w.upper() for w in s.split()]
        if not all(re.fullmatch(r'[0-9A-F]{8}', w) for w in words):
            raise ValueError(f'bad line: {line!r}')
        i = 0
        while i < len(words):
            k = opcode_len(words[i])
            op = words[i:i + k]
            if len(op) < k:
                raise ValueError(f'opcode split across lines: {op}')
            if is_main_rel(op):
                op, n = shift(op, by), n + 1
            out.append(' '.join(op))
            i += k
    return '\n'.join(out) + '\n', n


if __name__ == '__main__':
    if sys.argv[1] == '--test':
        c = lambda s: convert(s)[0].strip()
        assert c('580F0000 06A54830') == '580F0000 06A55830'
        assert c('580F1000 00000280') == '580F1000 00000280'          # register-relative
        assert c('040E0000 007B9334 14DFA31F') == '040E0000 007BA334 14DFA31F'
        assert c('010E0000 03FAAFE2 00000005') == '010E0000 03FAAFE2 00000005'.replace('3FAAFE2', '3FABFE2')
        assert c('FFF432E0 00000274') == 'FFF432E0 00000274'          # register-relative log
        one_line = '080E0000 03FAAFE8 00000000 00000000 040E0000 007B9B1C 14DFC525'
        assert c(one_line) == '080E0000 03FABFE8 00000000 00000000\n040E0000 007BAB1C 14DFC525'
        assert c('C041C400 00000001\n20000000') == 'C041C400 00000001\n20000000'
        try:
            convert('A4000000 00000000'); assert False
        except ValueError:
            pass
        print('ok')
    else:
        src = open(sys.argv[1], encoding='utf-8').read()
        dst, n = convert(src, int(sys.argv[3], 16) if len(sys.argv) > 3 else 0x1000)
        open(sys.argv[2], 'w', encoding='utf-8').write(dst)
        print(f'{n} opcodes shifted')
