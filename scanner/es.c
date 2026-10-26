// es: guest memory scanner for Eden (NCE) on Android. Runs on the phone via `run-as <debuggable eden>`.
// Guest memory = /memfd:HostMemory mappings below 0x6000000000 (under NCE guest VA == host VA).
//
//   es info  PID                                   main base, main end, BuildID
//   es scan  PID TYPE VALUE|? OUT                  first scan (? = unknown: snapshot everything)
//   es next  PID TYPE MODE VALUE IN OUT            MODE: eq inc dec chg same (VALUE ignored except eq)
//   es peek  PID TYPE IN N                         first N results: addr old cur
//   es ptr   PID TARGET MAXOFF DEPTH OUT           pointer chains main+X -> +o1 ... -> TARGET
//   es val   PID TYPE VALUE IN OUT                 keep chains that resolve to VALUE now
//
// TYPE: u8 u16 u32 u64 f32 f64. Results file: {u64 addr, u64 value} records.
// Unknown-scan file: magic "ESDUMP\0\0", then per region {u64 start, u64 len, bytes}.
// Chain file: text, one chain per line, hex: "X o1 o2 ... oN" (main-relative X).
#include <fcntl.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static int fd;
static const char *pid;
static int W, FLT;  // width in bytes, float type

static void die(const char *m) { fprintf(stderr, "error: %s\n", m); exit(1); }

static int rd(uint64_t a, void *b, size_t n) { return pread64(fd, b, n, a) == (ssize_t)n; }

static uint64_t rq(uint64_t a) { uint64_t v = 0; rd(a, &v, 8); return v; }

typedef struct { uint64_t s, e; int w; } Reg;
static Reg *regs; static int nregs;

static void load_regs(void) {
  char p[64]; sprintf(p, "/proc/%s/maps", pid);
  FILE *m = fopen(p, "r"); if (!m) die("no such pid");
  char line[512];
  while (fgets(line, sizeof line, m)) {
    unsigned long s, e; char perm[8];
    if (sscanf(line, "%lx-%lx %7s", &s, &e, perm) != 3 || perm[0] != 'r') continue;
    if (!strstr(line, "HostMemory") || s >= 0x6000000000UL) continue;
    if (nregs && regs[nregs - 1].e == s && regs[nregs - 1].w == (perm[1] == 'w')) { regs[nregs - 1].e = e; continue; }
    regs = realloc(regs, (nregs + 1) * sizeof *regs);
    regs[nregs++] = (Reg){s, e, perm[1] == 'w'};
  }
  fclose(m);
  if (!nregs) die("no guest memory (game not running?)");
}

// main = 2nd module with a MOD0 header (rtld, main, subsdk*, sdk). End = MOD0 bss_end.
static uint64_t MAIN, MAIN_END;
static void find_main(void) {
  int seen = 0;
  for (int i = 0; i < nregs; i++)
    for (uint64_t a = regs[i].s; a < regs[i].e; a += 0x1000) {
      uint32_t w[2]; char mg[4];
      if (!rd(a, w, 8)) break;
      if (!w[1] || w[1] > 0x100000 || (w[1] & 3) || !rd(a + w[1], mg, 4) || memcmp(mg, "MOD0", 4)) continue;
      if (++seen == 2) {
        int32_t bss_end; rd(a + w[1] + 12, &bss_end, 4);
        MAIN = a; MAIN_END = a + w[1] + bss_end; return;
      }
    }
  die("main module not found");
}

static void set_type(const char *t) {
  FLT = t[0] == 'f'; W = atoi(t + 1) / 8;
  if (W != 1 && W != 2 && W != 4 && W != 8) die("bad type");
}

static double as_num(uint64_t raw) {
  if (FLT) {
    if (W == 4) { float f; memcpy(&f, &raw, 4); return f; }
    double d; memcpy(&d, &raw, 8); return d;
  }
  return (double)raw;
}

static uint64_t parse_val(const char *s) {
  uint64_t r = 0;
  if (FLT) { double d = atof(s); if (W == 4) { float f = d; memcpy(&r, &f, 4); } else memcpy(&r, &d, 8); }
  else r = strtoull(s, 0, 0);
  return r;
}

static uint64_t mask(uint64_t v) { return W == 8 ? v : v & ((1ULL << (W * 8)) - 1); }

static int eq(uint64_t cur, uint64_t want) {
  if (!FLT) return cur == want;
  double c = as_num(cur), w = as_num(want);
  return fabs(c - w) < (w == floor(w) ? 0.5 : 0.001);  // integer input matches the displayed (rounded) float
}

static int test(const char *mode, uint64_t old, uint64_t cur, uint64_t want) {
  double o = as_num(old), c = as_num(cur);
  if (!strcmp(mode, "eq")) return eq(cur, want);
  if (!strcmp(mode, "inc")) return c > o;
  if (!strcmp(mode, "dec")) return c < o;
  if (!strcmp(mode, "chg")) return cur != old;
  if (!strcmp(mode, "same")) return cur == old;
  die("bad mode"); return 0;
}

#define CH (1 << 24)
#define MAX_RESULTS 20000000  // 320 MB of results on the phone

static void cmd_scan(const char *v, const char *out) {
  FILE *o = fopen(out, "wb"); if (!o) die("cannot write output");
  uint8_t *b = malloc(CH); long n = 0;
  int unknown = !strcmp(v, "?");
  uint64_t want = unknown ? 0 : parse_val(v);
  if (unknown) fwrite("ESDUMP\0\0", 8, 1, o);
  for (int i = 0; i < nregs; i++) {
    if (!regs[i].w) continue;
    for (uint64_t a = regs[i].s; a < regs[i].e; a += CH) {
      size_t k = regs[i].e - a < CH ? regs[i].e - a : CH;
      if (!rd(a, b, k)) continue;
      if (unknown) { uint64_t h[2] = {a, k}; fwrite(h, 16, 1, o); fwrite(b, k, 1, o); n += k / W; continue; }
      for (size_t j = 0; j + W <= k; j += W) {
        uint64_t cur = 0; memcpy(&cur, b + j, W);
        if (eq(cur, want)) { uint64_t r[2] = {a + j, cur}; fwrite(r, 16, 1, o); n++; }
      }
    }
  }
  fclose(o);
  printf("%ld\n", n);
}

static void cmd_next(const char *mode, const char *v, const char *in, const char *out) {
  FILE *f = fopen(in, "rb"), *o = fopen(out, "wb");
  if (!f || !o) die("no previous scan");
  uint64_t want = parse_val(v); long n = 0; char mg[8];
  if (fread(mg, 8, 1, f) == 1 && !memcmp(mg, "ESDUMP\0\0", 8)) {
    uint8_t *old = malloc(CH), *cur = malloc(CH); uint64_t h[2];
    while (fread(h, 16, 1, f) == 1 && fread(old, h[1], 1, f) == 1) {
      if (!rd(h[0], cur, h[1])) continue;
      for (size_t j = 0; j + W <= h[1]; j += W) {
        uint64_t a = 0, c = 0; memcpy(&a, old + j, W); memcpy(&c, cur + j, W);
        if (test(mode, a, c, want)) { uint64_t r[2] = {h[0] + j, c}; fwrite(r, 16, 1, o); n++; }
      }
      if (n > MAX_RESULTS) { fclose(o); remove(out); die("too many matches: change the value in game, then use changed/inc/dec"); }
    }
  } else {
    rewind(f); uint64_t r[2];
    while (fread(r, 16, 1, f) == 1) {
      uint64_t c = 0;
      if (rd(r[0], &c, W) && test(mode, r[1], c, want)) { r[1] = c; fwrite(r, 16, 1, o); n++; }
    }
  }
  fclose(o);
  printf("%ld\n", n);
}

static void print_val(uint64_t raw) {
  if (FLT) printf("%g", as_num(raw)); else printf("%llu", (unsigned long long)mask(raw));
}

static void cmd_peek(const char *in, int max) {
  FILE *f = fopen(in, "rb"); if (!f) die("no scan");
  uint64_t r[2]; char mg[8];
  if (fread(mg, 8, 1, f) == 1 && !memcmp(mg, "ESDUMP\0\0", 8)) { printf("unknown snapshot\n"); return; }
  rewind(f);
  for (int i = 0; i < max && fread(r, 16, 1, f) == 1; i++) {
    uint64_t c = 0; rd(r[0], &c, W);
    printf("%llx ", (unsigned long long)r[0]); print_val(r[1]); putchar(' '); print_val(c);
    printf(" %s\n", r[0] >= MAIN && r[0] < MAIN_END ? "main" : "heap");
  }
}

// Pointer scan, breadth-first: each level is one pass over writable guest memory, collecting
// qwords that point at most MAXOFF below any address of the previous level.
typedef struct { uint64_t addr; int parent; uint32_t off; } Node;
static Node *nodes; static int nnodes;
static int add_node(uint64_t a, int p, uint32_t off) {
  if (nnodes % 65536 == 0) nodes = realloc(nodes, (nnodes + 65536) * sizeof *nodes);
  nodes[nnodes] = (Node){a, p, off}; return nnodes++;
}

static int by_addr(const void *x, const void *y) {
  uint64_t a = nodes[*(int *)x].addr, b = nodes[*(int *)y].addr;
  return a < b ? -1 : a > b;
}

static long nchains;
static void emit(FILE *o, int n) {
  fprintf(o, "%llx", (unsigned long long)(nodes[n].addr - MAIN));
  for (; nodes[n].parent >= 0; n = nodes[n].parent) fprintf(o, " %x", nodes[n].off);
  fputc('\n', o); nchains++;
}

#define MAX_FRONTIER 200000  // ponytail: hard cap per level; smarter pruning if real games hit it
#define MAX_CHAINS 100000

static void cmd_ptr(uint64_t target, uint32_t maxoff, int depth, const char *out) {
  FILE *o = fopen(out, "w"); if (!o) die("cannot write output");
  add_node(target, -1, 0);
  if (target >= MAIN && target < MAIN_END) emit(o, 0);
  int lo = 0, hi = 1;  // current frontier = nodes[lo..hi)
  uint8_t *b = malloc(CH);
  for (int lvl = 1; lvl <= depth && lo < hi && nchains < MAX_CHAINS; lvl++) {
    int nf = hi - lo, *idx = malloc(nf * sizeof *idx);
    for (int i = 0; i < nf; i++) idx[i] = lo + i;
    qsort(idx, nf, sizeof *idx, by_addr);
    uint64_t *ta = malloc(nf * 8);
    for (int i = 0; i < nf; i++) ta[i] = nodes[idx[i]].addr;
    int start = nnodes, capped = 0;
    for (int r = 0; r < nregs && !capped; r++) {
      if (!regs[r].w) continue;
      for (uint64_t a = regs[r].s; a < regs[r].e && !capped; a += CH) {
        size_t k = regs[r].e - a < CH ? regs[r].e - a : CH;
        if (!rd(a, b, k)) continue;
        for (size_t j = 0; j + 8 <= k; j += 8) {
          uint64_t v = *(uint64_t *)(b + j);
          if (v < ta[0] - maxoff || v > ta[nf - 1]) continue;
          int l = 0, h = nf;  // first target >= v
          while (l < h) { int m = (l + h) / 2; if (ta[m] < v) l = m + 1; else h = m; }
          for (int t = l; t < nf && ta[t] - v <= maxoff; t++) {
            int n = add_node(a + j, idx[t], (uint32_t)(ta[t] - v));
            if (a + j >= MAIN && a + j < MAIN_END) { emit(o, n); nnodes--; }  // static: chain done
            if (nnodes - start > MAX_FRONTIER) { capped = 1; break; }
          }
        }
      }
    }
    fprintf(stderr, "level %d: %d pointers%s, %ld chains\n", lvl, nnodes - start, capped ? " (capped)" : "", nchains);
    free(idx); free(ta);
    lo = start; hi = nnodes;
  }
  fclose(o);
  printf("%ld\n", nchains);
}

static int resolve(char *line, uint64_t *out) {
  char *s = line, *e; uint64_t x = strtoull(s, &e, 16), a = MAIN + x;
  for (s = e; ; s = e) {
    uint64_t off = strtoull(s, &e, 16);
    if (e == s) break;
    a = rq(a);
    if (!a) return 0;
    a += off;
  }
  *out = a; return 1;
}

static void cmd_val(const char *v, const char *in, const char *out) {
  FILE *f = fopen(in, "r"), *o = fopen(out, "w");
  if (!f || !o) die("no pointer scan");
  uint64_t want = parse_val(v); char line[512]; long n = 0;
  while (fgets(line, sizeof line, f)) {
    uint64_t a, c = 0;
    if (resolve(line, &a) && rd(a, &c, W) && eq(c, want)) { fputs(line, o); n++; }
  }
  fclose(o);
  printf("%ld\n", n);
}

int main(int argc, char **argv) {
  if (argc < 3) die("usage: see es.c header");
  pid = argv[2];
  char p[64]; sprintf(p, "/proc/%s/mem", pid);
  if ((fd = open(p, O_RDONLY)) < 0) die("cannot open process memory");
  load_regs(); find_main();
  const char *c = argv[1];
  if (!strcmp(c, "info")) {
    // GNU build-id note: namesz=4, descsz, type=3, "GNU\0", id. Cheat BuildID = first 8 bytes.
    static const uint8_t pat[] = {3, 0, 0, 0, 'G', 'N', 'U', 0};
    uint8_t *b = malloc(CH);
    for (uint64_t a = MAIN; a < MAIN_END; a += CH - 64) {
      size_t k = MAIN_END - a < CH ? MAIN_END - a : CH;
      if (!rd(a, b, k)) continue;
      uint8_t *h = memmem(b, k, pat, sizeof pat);
      if (h && h - b >= 8 && h + 16 <= b + k && *(uint32_t *)(h - 8) == 4) {
        printf("main %llx %llx ", (unsigned long long)MAIN, (unsigned long long)MAIN_END);
        for (int i = 0; i < 8; i++) printf("%02X", h[8 + i]);
        putchar('\n'); return 0;
      }
    }
    printf("main %llx %llx ?\n", (unsigned long long)MAIN, (unsigned long long)MAIN_END);
  } else if (!strcmp(c, "scan") && argc == 6) { set_type(argv[3]); cmd_scan(argv[4], argv[5]); }
  else if (!strcmp(c, "next") && argc == 8) { set_type(argv[3]); cmd_next(argv[4], argv[5], argv[6], argv[7]); }
  else if (!strcmp(c, "peek") && argc == 6) { set_type(argv[3]); cmd_peek(argv[4], atoi(argv[5])); }
  else if (!strcmp(c, "ptr") && argc == 7) cmd_ptr(strtoull(argv[3], 0, 16), strtoul(argv[4], 0, 16), atoi(argv[5]), argv[6]);
  else if (!strcmp(c, "val") && argc == 7) { set_type(argv[3]); cmd_val(argv[4], argv[5], argv[6]); }
  else die("bad command / args");
  return 0;
}
