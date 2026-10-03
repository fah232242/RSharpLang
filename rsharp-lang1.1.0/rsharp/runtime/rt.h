/* R# runtime v0.1 -- prepended to every generated C file. */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdarg.h>
#include <ctype.h>
#include <errno.h>
#include <time.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif

static void rs_panic(const char *fmt, ...) __attribute__((noreturn, format(printf, 1, 2)));
static void rs_panic(const char *fmt, ...) {
    va_list ap;
    fflush(stdout);
    fputs("panic: ", stderr);
    va_start(ap, fmt);
    vfprintf(stderr, fmt, ap);
    va_end(ap);
    fputc('\n', stderr);
    exit(101);
}

/* v0.1 has no garbage collector: heap memory is reclaimed at process exit. */
static void *rs_alloc(size_t n) {
    void *p = calloc(1, n ? n : 1);
    if (!p) rs_panic("out of memory");
    return p;
}
static void *rs_realloc(void *p, size_t n) {
    p = realloc(p, n ? n : 1);
    if (!p) rs_panic("out of memory");
    return p;
}
static const char *rs_strdup(const char *s) {
    size_t n = strlen(s);
    char *r = rs_alloc(n + 1);
    memcpy(r, s, n);
    return r;
}

/* checked integer arithmetic */
static inline int64_t rs_add(int64_t a, int64_t b) {
    int64_t r;
    if (__builtin_add_overflow(a, b, &r)) rs_panic("integer overflow in addition");
    return r;
}
static inline int64_t rs_sub(int64_t a, int64_t b) {
    int64_t r;
    if (__builtin_sub_overflow(a, b, &r)) rs_panic("integer overflow in subtraction");
    return r;
}
static inline int64_t rs_mul(int64_t a, int64_t b) {
    int64_t r;
    if (__builtin_mul_overflow(a, b, &r)) rs_panic("integer overflow in multiplication");
    return r;
}
static inline int64_t rs_div(int64_t a, int64_t b, int line) {
    if (b == 0) rs_panic("division by zero (line %d)", line);
    if (a == INT64_MIN && b == -1) rs_panic("integer overflow in division (line %d)", line);
    return a / b;
}
static inline int64_t rs_mod(int64_t a, int64_t b, int line) {
    if (b == 0) rs_panic("modulo by zero (line %d)", line);
    if (b == -1) return 0;
    return a % b;
}
static inline int64_t rs_f2i(double d) {
    if (!(d >= -9223372036854775808.0 && d < 9223372036854775808.0))
        rs_panic("cannot convert %g to int: out of range", d);
    return (int64_t)d;
}
static void rs_panic_index(int64_t i, int64_t len, int line) {
    rs_panic("index %lld out of bounds for length %lld (line %d)", (long long)i, (long long)len, line);
}

/* strings */
static const char *rs_concat(const char *a, const char *b) {
    size_t la = strlen(a), lb = strlen(b);
    char *r = rs_alloc(la + lb + 1);
    memcpy(r, a, la);
    memcpy(r + la, b, lb);
    return r;
}
static const char *rs_str_int(int64_t v) {
    char buf[32];
    snprintf(buf, sizeof buf, "%lld", (long long)v);
    return rs_strdup(buf);
}
static const char *rs_str_float(double d) {
    char buf[64];
    if (isnan(d)) return "nan";
    if (isinf(d)) return d < 0 ? "-inf" : "inf";
    for (int p = 1; p <= 17; p++) {
        snprintf(buf, sizeof buf, "%.*g", p, d);
        if (strtod(buf, NULL) == d) break;
    }
    if (!strpbrk(buf, ".eE")) strcat(buf, ".0");
    return rs_strdup(buf);
}
static const char *rs_str_bool(bool b) { return b ? "true" : "false"; }

typedef struct { char *buf; size_t len, cap; } rs_sb;
static void rs_sb_cat(rs_sb *b, const char *s) {
    size_t n = strlen(s);
    if (b->len + n + 1 > b->cap) {
        b->cap = (b->len + n + 1) * 2;
        b->buf = rs_realloc(b->buf, b->cap);
    }
    memcpy(b->buf + b->len, s, n + 1);
    b->len += n;
}
static const char *rs_repr_string(const char *s) {
    rs_sb b = {0};
    rs_sb_cat(&b, "\"");
    for (; *s; s++) {
        char t[3] = {*s, 0, 0};
        if (*s == '"') rs_sb_cat(&b, "\\\"");
        else if (*s == '\\') rs_sb_cat(&b, "\\\\");
        else if (*s == '\n') rs_sb_cat(&b, "\\n");
        else if (*s == '\t') rs_sb_cat(&b, "\\t");
        else rs_sb_cat(&b, t);
    }
    rs_sb_cat(&b, "\"");
    return b.buf;
}

/* printing */
static void rs_print_int(int64_t v) { printf("%lld", (long long)v); }
static void rs_print_float(double d) { fputs(rs_str_float(d), stdout); }
static void rs_print_bool(bool b) { fputs(b ? "true" : "false", stdout); }
static void rs_print_str(const char *s) { fputs(s, stdout); }
static void rs_print_sp(void) { fputc(' ', stdout); }
static void rs_print_nl(void) { fputc('\n', stdout); }

/* ---- v0.2 additions ---- */
static inline int64_t rs_abs(int64_t a) {
    if (a == INT64_MIN) rs_panic("integer overflow in abs()");
    return a < 0 ? -a : a;
}
static int64_t rs_ipow(int64_t b, int64_t e) {
    if (e < 0) rs_panic("negative exponent in integer power (use float64)");
    int64_t r = 1;
    while (e) {
        if (e & 1) r = rs_mul(r, b);
        e >>= 1;
        if (e) b = rs_mul(b, b);
    }
    return r;
}
static int64_t rs_gcd(int64_t a, int64_t b) {
    a = a < 0 ? -a : a; b = b < 0 ? -b : b;
    while (b) { int64_t t = a % b; a = b; b = t; }
    return a;
}
static inline int64_t rs_min_int(int64_t a, int64_t b) { return a < b ? a : b; }
static inline int64_t rs_max_int(int64_t a, int64_t b) { return a > b ? a : b; }
static inline double rs_min_float(double a, double b) { return a < b ? a : b; }
static inline double rs_max_float(double a, double b) { return a > b ? a : b; }
static inline const char *rs_min_string(const char *a, const char *b) { return strcmp(a, b) <= 0 ? a : b; }
static inline const char *rs_max_string(const char *a, const char *b) { return strcmp(a, b) >= 0 ? a : b; }
static void rs_assert(bool c, const char *msg, int line) {
    if (!c) rs_panic("assertion failed%s%s (line %d)", *msg ? ": " : "", msg, line);
}
static void rs_exit(int64_t code) { fflush(stdout); exit((int)code); }

/* comparators for qsort */
static int rs_cmp_int(const void *a, const void *b) {
    int64_t x = *(const int64_t *)a, y = *(const int64_t *)b;
    return (x > y) - (x < y);
}
static int rs_cmp_float(const void *a, const void *b) {
    double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}
static int rs_cmp_string(const void *a, const void *b) {
    return strcmp(*(const char *const *)a, *(const char *const *)b);
}

/* strings */
static void rs_norm_slice(int64_t n, int64_t lo, int64_t hi, int hl, int hh, int64_t *a, int64_t *b) {
    int64_t l = hl ? lo : 0, h = hh ? hi : n;
    if (l < 0) l += n;
    if (h < 0) h += n;
    if (l < 0) l = 0;
    if (l > n) l = n;
    if (h < 0) h = 0;
    if (h > n) h = n;
    if (h < l) h = l;
    *a = l; *b = h;
}
static const char *rs_slice_str(const char *s, int64_t lo, int64_t hi, int hl, int hh) {
    int64_t a, b;
    rs_norm_slice((int64_t)strlen(s), lo, hi, hl, hh, &a, &b);
    char *r = rs_alloc((size_t)(b - a) + 1);
    memcpy(r, s + a, (size_t)(b - a));
    return r;
}
static const char *rs_char_at(const char *s, int64_t i, int line) {
    int64_t n = (int64_t)strlen(s), j = i < 0 ? i + n : i;
    if (j < 0 || j >= n) rs_panic_index(i, n, line);
    char *r = rs_alloc(2);
    r[0] = s[j];
    return r;
}
static const char *rs_upper(const char *s) {
    char *r = (char *)rs_strdup(s);
    for (char *p = r; *p; p++) *p = (char)toupper((unsigned char)*p);
    return r;
}
static const char *rs_lower(const char *s) {
    char *r = (char *)rs_strdup(s);
    for (char *p = r; *p; p++) *p = (char)tolower((unsigned char)*p);
    return r;
}
static const char *rs_strip(const char *s) {
    while (*s && isspace((unsigned char)*s)) s++;
    size_t n = strlen(s);
    while (n && isspace((unsigned char)s[n - 1])) n--;
    char *r = rs_alloc(n + 1);
    memcpy(r, s, n);
    return r;
}
static bool rs_contains(const char *s, const char *sub) { return strstr(s, sub) != NULL; }
static bool rs_startswith(const char *s, const char *p) { return strncmp(s, p, strlen(p)) == 0; }
static bool rs_endswith(const char *s, const char *p) {
    size_t a = strlen(s), b = strlen(p);
    return b <= a && memcmp(s + a - b, p, b) == 0;
}
static int64_t rs_find(const char *s, const char *sub) {
    const char *p = strstr(s, sub);
    return p ? (int64_t)(p - s) : -1;
}
static const char *rs_replace(const char *s, const char *a, const char *b) {
    size_t la = strlen(a), lb = strlen(b);
    if (la == 0) return rs_strdup(s);
    size_t cnt = 0;
    for (const char *p = s; (p = strstr(p, a)); p += la) cnt++;
    char *r = rs_alloc(strlen(s) + cnt * (lb > la ? lb - la : 0) + 1), *w = r;
    const char *p = s, *q;
    while ((q = strstr(p, a))) {
        memcpy(w, p, (size_t)(q - p)); w += q - p;
        memcpy(w, b, lb); w += lb;
        p = q + la;
    }
    strcpy(w, p);
    return r;
}
static const char *rs_repeat(const char *s, int64_t n) {
    if (n <= 0) return "";
    size_t l = strlen(s);
    char *r = rs_alloc(l * (size_t)n + 1);
    for (int64_t i = 0; i < n; i++) memcpy(r + (size_t)i * l, s, l);
    return r;
}
static int64_t rs_parse_int(const char *s) {
    char *end;
    errno = 0;
    long long v = strtoll(s, &end, 10);
    while (*end && isspace((unsigned char)*end)) end++;
    if (end == s || *end || errno) rs_panic("invalid literal for int(): \"%s\"", s);
    return (int64_t)v;
}
static double rs_parse_float(const char *s) {
    char *end;
    double v = strtod(s, &end);
    while (*end && isspace((unsigned char)*end)) end++;
    if (end == s || *end) rs_panic("invalid literal for float64(): \"%s\"", s);
    return v;
}
static int64_t rs_ord(const char *s) {
    if (strlen(s) != 1) rs_panic("ord() expects a single-byte string");
    return (unsigned char)s[0];
}
static const char *rs_chr(int64_t c) {
    if (c < 0 || c > 255) rs_panic("chr() argument out of range (0..255)");
    char *r = rs_alloc(2);
    r[0] = (char)c;
    return r;
}

/* I/O */
static const char *rs_input(const char *prompt) {
    fputs(prompt, stdout);
    fflush(stdout);
    rs_sb b = {0};
    int c, any = 0;
    while ((c = getchar()) != EOF) {
        any = 1;
        if (c == '\n') break;
        char t[2] = {(char)c, 0};
        rs_sb_cat(&b, t);
    }
    if (!any) rs_panic("EOF when reading a line");
    if (b.len && b.buf[b.len - 1] == '\r') b.buf[--b.len] = 0;
    return b.buf ? b.buf : "";
}
static const char *rs_read_file(const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) rs_panic("cannot read file '%s'", path);
    rs_sb b = {0};
    char buf[4096];
    size_t n;
    while ((n = fread(buf, 1, sizeof buf - 1, f)) > 0) { buf[n] = 0; rs_sb_cat(&b, buf); }
    fclose(f);
    return b.buf ? b.buf : "";
}
static void rs_write_file(const char *path, const char *text) {
    FILE *f = fopen(path, "wb");
    if (!f) rs_panic("cannot write file '%s'", path);
    fputs(text, f);
    fclose(f);
}

/* random / time */
static uint64_t rs_rng = 0;
static void rs_seed(int64_t s) { rs_rng = (uint64_t)s * 2685821657736338717ULL + 1442695040888963407ULL; }
static uint64_t rs_next(void) {
    if (!rs_rng) rs_seed((int64_t)time(NULL) ^ (int64_t)clock());
    rs_rng ^= rs_rng >> 12; rs_rng ^= rs_rng << 25; rs_rng ^= rs_rng >> 27;
    return rs_rng * 2685821657736338717ULL;
}
static double rs_random(void) { return (double)(rs_next() >> 11) * (1.0 / 9007199254740992.0); }
static int64_t rs_randint(int64_t a, int64_t b) {
    if (b < a) rs_panic("randint(): empty range");
    return a + (int64_t)(rs_next() % ((uint64_t)(b - a) + 1));
}
static double rs_now(void) {
    struct timespec ts;
    timespec_get(&ts, TIME_UTC);
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}
static void rs_sleep(double sec) {
    if (sec <= 0) return;
    fflush(stdout);
#ifdef _WIN32
    Sleep((DWORD)(sec * 1000));
#else
    struct timespec ts = {(time_t)sec, (long)((sec - (double)(time_t)sec) * 1e9)};
    nanosleep(&ts, NULL);
#endif
}
