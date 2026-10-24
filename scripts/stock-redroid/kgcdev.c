// kgcdev — device-side helper (static x86_64) for the redroid *stock* KGC client.
//
// Why this exists:
//  1) Inside zygote64's mount namespace /system/bin/linker64 is bind-mounted to the
//     arm64 linker (that is what makes XIGNCODE's bytehook init succeed).  The side
//     effect is that x86_64 binaries can no longer be exec'd *in that namespace*
//     (their PT_INTERP is /system/bin/linker64), so `nsenter ... mount` stops working.
//     `nsbind` does setns()+mount(2) itself, so it keeps working forever.
//  2) The pristine client dies in `GameManager.Init()` because Firebase.Messaging cannot
//     initialize without Google Play Services, and it dies again ~1 min later on a null
//     graphics device / destroyed mutexes.  APK bytes must stay untouched (XIGNCODE
//     AppSign), so every fix is a RAM-only write into the running process:
//       patch    <pkg> …  -> libil2cpp, which the packer decrypts into a memfd: the first
//                            mapping (file offset 0) is the ELF's vaddr 0, so addr = base + RVA
//       patchlib <pkg> …  -> a .so mapped straight out of the split APK (libunity, …): the
//                            mapping's file offset is a position inside the APK, so the caller
//                            passes that absolute APK position
//     Both keep polling: a memfd reads back zeros until the packer finishes decrypting, and
//     the APK lib is mapped a moment after the process starts.
//
// usage:
//   kgcdev nsbind   <zygote_pid>
//   kgcdev patch    <package> <rva_hex> <expect_hex> [replacement_hex]
//   kgcdev patchlib <package> <libname> <apk_file_pos_hex> <expect_hex> [replacement_hex]
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <unistd.h>

#define ARM64_LINKER "/system/bin/arm64/linker64"
#define LINKER_PATH "/system/bin/linker64"
#define MAX_TARGETS 256

// ---- nsbind: patch the linker *inside* a namespace, without executing anything there

static int nsbind(pid_t pid) {
  char p[64];
  snprintf(p, sizeof p, "/proc/%d/ns/mnt", pid);
  int fd = open(p, O_RDONLY);
  if (fd < 0) { fprintf(stderr, "open %s: %s\n", p, strerror(errno)); return 1; }
  if (setns(fd, CLONE_NEWNS) != 0) { fprintf(stderr, "setns: %s\n", strerror(errno)); return 1; }
  close(fd);
  // do not leak the bind mount back to init's namespace
  if (mount(NULL, "/", NULL, MS_REC | MS_PRIVATE, NULL) != 0)
    fprintf(stderr, "make-rprivate: %s\n", strerror(errno));
  if (mount(ARM64_LINKER, LINKER_PATH, NULL, MS_BIND, NULL) != 0) {
    fprintf(stderr, "bind %s -> %s: %s\n", ARM64_LINKER, LINKER_PATH, strerror(errno));
    return 1;
  }
  printf("nsbind ok (zygote %d): %s -> %s\n", pid, ARM64_LINKER, LINKER_PATH);
  return 0;
}

// ---- process / mapping discovery

static pid_t find_pid(const char *pkg) {
  DIR *d = opendir("/proc");
  if (!d) return -1;
  struct dirent *e;
  char path[128], buf[256];
  pid_t found = -1;
  while ((e = readdir(d))) {
    if (e->d_name[0] < '0' || e->d_name[0] > '9') continue;
    snprintf(path, sizeof path, "/proc/%s/cmdline", e->d_name);
    int fd = open(path, O_RDONLY);
    if (fd < 0) continue;
    ssize_t n = read(fd, buf, sizeof buf - 1);
    close(fd);
    if (n <= 0) continue;
    buf[n] = 0;
    if (strcmp(buf, pkg) == 0) { found = (pid_t)atoi(e->d_name); break; }
  }
  closedir(d);
  return found;
}

// runtime address of an ELF vaddr in a memfd-mapped libil2cpp (first mapping == vaddr 0)
static unsigned long addr_from_rva(pid_t pid, unsigned long rva) {
  char path[64], line[512];
  snprintf(path, sizeof path, "/proc/%d/maps", pid);
  FILE *f = fopen(path, "r");
  if (!f) return 0;
  unsigned long base = 0;
  while (fgets(line, sizeof line, f)) {
    if (!strstr(line, "libil2cpp.so")) continue;
    unsigned long start, off;
    if (sscanf(line, "%lx-%*lx %*s %lx", &start, &off) != 2) continue;
    if (off == 0) { base = start; break; }
  }
  fclose(f);
  return base ? base + rva : 0;
}

// runtime address of an absolute position inside the split APK (lib mmap'd from the zip)
static unsigned long addr_from_apkpos(pid_t pid, const char *libname, unsigned long pos) {
  char path[64], line[512];
  snprintf(path, sizeof path, "/proc/%d/maps", pid);
  FILE *f = fopen(path, "r");
  if (!f) return 0;
  unsigned long addr = 0;
  while (fgets(line, sizeof line, f)) {
    if (!strstr(line, libname)) continue;
    unsigned long start, end, off;
    if (sscanf(line, "%lx-%lx %*s %lx", &start, &end, &off) != 3) continue;
    if (off <= pos && pos < off + (end - start)) { addr = start + (pos - off); break; }
  }
  fclose(f);
  return addr;
}

// ---- hex helpers

static int hexval(int c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static int parse_hex(const char *s, unsigned char *out, int max) {
  int n = 0;
  while (*s && n < max && s[1]) {
    int hi = hexval(s[0]), lo = hexval(s[1]);
    if (hi < 0 || lo < 0) break;
    out[n++] = (unsigned char)((hi << 4) | lo);
    s += 2;
  }
  return n;
}

// ---- the polling loop
//
// resolve(pid, ctx) returns the runtime address to patch (0 = not mapped yet).
typedef void *(*resolver)(pid_t, void *);

struct rva_ctx { unsigned long rva; };
static void *resolve_rva(pid_t pid, void *c) {
  return (void *)addr_from_rva(pid, ((struct rva_ctx *)c)->rva);
}

struct apk_ctx { const char *lib; unsigned long pos; };
static void *resolve_apk(pid_t pid, void *c) {
  struct apk_ctx *a = c;
  return (void *)addr_from_apkpos(pid, a->lib, a->pos);
}

static int run_loop(const char *pkg, resolver resolve, void *ctx, const unsigned char *expect,
                    int elen, const unsigned char *repl, int rlen, int revert_sec) {
  pid_t done[MAX_TARGETS];
  int ndone = 0;
  long miss = 0, nomap = 0;
  for (;;) {
    pid_t pid = find_pid(pkg);
    if (pid > 0) {
      int seen = 0;
      for (int i = 0; i < ndone; i++)
        if (done[i] == pid) seen = 1;
      if (!seen) {
        unsigned long addr = (unsigned long)resolve(pid, ctx);
        if (!addr && ++nomap % 250 == 0) {
          printf("pid %d: target mapping not there yet\n", pid);
          fflush(stdout);
        }
        if (addr) {
          char mp[64];
          snprintf(mp, sizeof mp, "/proc/%d/mem", pid);
          int fd = open(mp, O_RDWR);
          if (fd >= 0) {
            unsigned char cur[64] = {0};
            ssize_t got = pread(fd, cur, elen, (off_t)addr);
            if (got == elen && memcmp(cur, repl, rlen) == 0) {
              // a second daemon (or an earlier run of this one) already did it: without this we
              // would sit on "mismatch" forever, because the original prologue never comes back
              printf("pid %d addr %#lx already patched, skip\n", pid, addr);
              fflush(stdout);
              if (ndone < MAX_TARGETS) done[ndone++] = pid;
            } else if (got == elen && memcmp(cur, expect, elen) == 0) {
              ssize_t wr = pwrite(fd, repl, rlen, (off_t)addr);
              unsigned char chk[8] = {0};
              pread(fd, chk, 8, (off_t)addr);
              printf("pid %d addr %#lx PATCH wr=%zd (%s) after=", pid, addr, wr,
                     wr == rlen ? "ok" : strerror(errno));
              for (int i = 0; i < 8; i++) printf("%02x", chk[i]);
              printf("\n");
              fflush(stdout);
              if (ndone < MAX_TARGETS) done[ndone++] = pid;
              if (revert_sec > 0) {
                // "patch, use, restore": a patched code page in RAM is visible to XIGNCODE's
                // periodic integrity scan (suspected cause of the ~1 min crashes), so put the
                // original bytes back once the single call we cared about has happened
                sleep((unsigned)revert_sec);
                pwrite(fd, expect, elen, (off_t)addr);
                unsigned char chk2[8] = {0};
                pread(fd, chk2, 8, (off_t)addr);
                printf("pid %d addr %#lx REVERTED after %ds -> ", pid, addr, revert_sec);
                for (int i = 0; i < 8; i++) printf("%02x", chk2[i]);
                printf("\n");
                fflush(stdout);
              }
            } else if (++miss % 100 == 0) {
              printf("waiting: pid %d addr %#lx got=%zd cur=", pid, addr, got);
              for (int i = 0; i < (got > 0 ? got : 0); i++) printf("%02x", cur[i]);
              printf("\n");
              fflush(stdout);
            }
            close(fd);
          }
        }
      }
    }
    usleep(20000);
  }
  return 0;
}

int main(int argc, char **argv) {
  unsigned char expect[64], repl[64];
  int elen, rlen;

  if (argc >= 3 && strcmp(argv[1], "nsbind") == 0) return nsbind((pid_t)atoi(argv[2]));

  if (argc >= 5 && strcmp(argv[1], "patch") == 0) {
    elen = parse_hex(argv[4], expect, sizeof expect);
    if (argc > 5) rlen = parse_hex(argv[5], repl, sizeof repl);
    else { memcpy(repl, "\xc0\x03\x5f\xd6", 4); rlen = 4; }  // ret
    if (!elen) { fprintf(stderr, "bad expect hex\n"); return 2; }
    struct rva_ctx c = {strtoul(argv[3], NULL, 16)};
    int rev = (argc > 6) ? atoi(argv[6]) : 0;
    printf("patch: pkg=%s rva=%#lx expect=%d bytes revert=%ds\n", argv[2], c.rva, elen, rev);
    fflush(stdout);
    return run_loop(argv[2], resolve_rva, &c, expect, elen, repl, rlen, rev);
  }

  if (argc >= 6 && strcmp(argv[1], "patchlib") == 0) {
    elen = parse_hex(argv[5], expect, sizeof expect);
    if (argc > 6) rlen = parse_hex(argv[6], repl, sizeof repl);
    else { memcpy(repl, "\xc0\x03\x5f\xd6", 4); rlen = 4; }
    if (!elen) { fprintf(stderr, "bad expect hex\n"); return 2; }
    struct apk_ctx c = {argv[3], strtoul(argv[4], NULL, 16)};
    int rev = (argc > 7) ? atoi(argv[7]) : 0;
    printf("patchlib: pkg=%s lib=%s apk_pos=%#lx expect=%d bytes revert=%ds\n",
           argv[2], c.lib, c.pos, elen, rev);
    fflush(stdout);
    return run_loop(argv[2], resolve_apk, &c, expect, elen, repl, rlen, rev);
  }

  fprintf(stderr,
          "usage:\n"
          "  %s nsbind <zygote_pid>\n"
          "  %s patch <package> <rva_hex> <expect_hex> [replacement_hex] [revert_seconds]\n"
          "  %s patchlib <package> <libname> <apk_file_pos_hex> <expect_hex> [replacement_hex]"
          " [revert_seconds]\n",
          argv[0], argv[0], argv[0]);
  return 2;
}
