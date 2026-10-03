/* R# runtime v0.1 -- prepended to every generated C file. */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <stdarg.h>

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
