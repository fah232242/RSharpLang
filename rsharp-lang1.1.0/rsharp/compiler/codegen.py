"""Typed AST -> C11 (+GNU statement expressions). gcc turns the C into a native executable."""
import os
from . import ast as A
from .checker import is_arr, is_map

RT = os.path.join(os.path.dirname(__file__), "..", "runtime", "rt.h")
CMP = {"==", "!=", "<", "<=", ">", ">="}
INT_OPS = {"+": "rs_add", "-": "rs_sub", "*": "rs_mul"}
STR_FN = {"upper": "rs_upper", "lower": "rs_lower", "strip": "rs_strip", "contains": "rs_contains",
          "startswith": "rs_startswith", "endswith": "rs_endswith", "replace": "rs_replace",
          "split": "rs_split", "find": "rs_find"}


def mangle(t):
    if isinstance(t, str):
        return t
    return ("Arr_" if t[0] == "array" else "Map_") + mangle(t[1])


def c_escape(s):
    out = []
    for b in s.encode("utf-8"):
        ch = chr(b)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif 32 <= b < 127 and ch != "?":
            out.append(ch)
        else:
            out.append("\\%03o" % b)
    return '"' + "".join(out) + '"'


def has_call(e):
    if isinstance(e, A.Call):
        return True
    if isinstance(e, A.Node):
        return any(has_call(getattr(e, f)) for f in e.fields)
    if isinstance(e, list):
        return any(has_call(x) for x in e)
    return False


ARRAY_BASE = r"""
typedef struct @N@ { int64_t len, cap; @T@ *data; } @N@;
static @N@ *rs_lit_@N@(int64_t n, const @T@ *src) {
    @N@ *a = rs_alloc(sizeof(@N@));
    a->len = a->cap = n;
    a->data = n ? rs_alloc((size_t)n * sizeof(@T@)) : NULL;
    if (n) memcpy(a->data, src, (size_t)n * sizeof(@T@));
    return a;
}
static void rs_push_@N@(@N@ *a, @T@ v) {
    if (a->len == a->cap) {
        a->cap = a->cap ? a->cap * 2 : 4;
        a->data = rs_realloc(a->data, (size_t)a->cap * sizeof(@T@));
    }
    a->data[a->len++] = v;
}
static @T@ *rs_at_@N@(@N@ *a, int64_t i, int line) {
    int64_t j = i < 0 ? i + a->len : i;
    if (j < 0 || j >= a->len) rs_panic_index(i, a->len, line);
    return &a->data[j];
}
static @T@ rs_pop_@N@(@N@ *a) {
    if (!a->len) rs_panic("pop from empty array");
    return a->data[--a->len];
}
static void rs_clear_@N@(@N@ *a) { a->len = 0; }
static @N@ *rs_copy_@N@(@N@ *a) { return rs_lit_@N@(a->len, a->data); }
static void rs_extend_@N@(@N@ *a, @N@ *b) {
    int64_t n = b->len;
    for (int64_t i = 0; i < n; i++) rs_push_@N@(a, b->data[i]);
}
static void rs_reverse_@N@(@N@ *a) {
    for (int64_t i = 0, j = a->len - 1; i < j; i++, j--) { @T@ t = a->data[i]; a->data[i] = a->data[j]; a->data[j] = t; }
}
static @N@ *rs_reversed_@N@(@N@ *a) { @N@ *c = rs_copy_@N@(a); rs_reverse_@N@(c); return c; }
static @N@ *rs_slice_@N@(@N@ *a, int64_t lo, int64_t hi, int hl, int hh) {
    int64_t x, y;
    rs_norm_slice(a->len, lo, hi, hl, hh, &x, &y);
    return rs_lit_@N@(y - x, a->data + x);
}
static const char *rs_str_@N@(@N@ *a) {
    rs_sb b = {0};
    rs_sb_cat(&b, "[");
    for (int64_t i = 0; i < a->len; i++) {
        if (i) rs_sb_cat(&b, ", ");
        rs_sb_cat(&b, @REPR@(a->data[i]));
    }
    rs_sb_cat(&b, "]");
    return b.buf ? b.buf : "[]";
}
"""
ARRAY_SCALAR = r"""
static bool rs_contains_@N@(@N@ *a, @T@ v) {
    for (int64_t i = 0; i < a->len; i++) if (@EQ@) return true;
    return false;
}
"""
ARRAY_SORT = r"""
static void rs_sort_@N@(@N@ *a) { if (a->len > 1) qsort(a->data, (size_t)a->len, sizeof(@T@), @CMP@); }
static @N@ *rs_sorted_@N@(@N@ *a) { @N@ *c = rs_copy_@N@(a); rs_sort_@N@(c); return c; }
static @T@ rs_min_@N@(@N@ *a) {
    if (!a->len) rs_panic("min() of an empty array");
    @T@ r = a->data[0];
    for (int64_t i = 1; i < a->len; i++) r = rs_min_@E@(r, a->data[i]);
    return r;
}
static @T@ rs_max_@N@(@N@ *a) {
    if (!a->len) rs_panic("max() of an empty array");
    @T@ r = a->data[0];
    for (int64_t i = 1; i < a->len; i++) r = rs_max_@E@(r, a->data[i]);
    return r;
}
"""
ARRAY_SUM_INT = r"""
static int64_t rs_sum_@N@(@N@ *a) { int64_t s = 0; for (int64_t i = 0; i < a->len; i++) s = rs_add(s, a->data[i]); return s; }
static @N@ *rs_range_@N@(int64_t lo, int64_t hi, int64_t st) {
    if (st == 0) rs_panic("range() step must not be zero");
    @N@ *a = rs_lit_@N@(0, NULL);
    for (int64_t i = lo; st > 0 ? i < hi : i > hi; i += st) rs_push_@N@(a, i);
    return a;
}
"""
ARRAY_SUM_FLOAT = r"""
static double rs_sum_@N@(@N@ *a) { double s = 0; for (int64_t i = 0; i < a->len; i++) s += a->data[i]; return s; }
"""
ARRAY_STRING = r"""
static Arr_string *rs_split(const char *s, const char *sep) {
    size_t ls = strlen(sep);
    if (!ls) rs_panic("split(): empty separator");
    Arr_string *r = rs_lit_Arr_string(0, NULL);
    const char *p = s, *q;
    while ((q = strstr(p, sep))) {
        char *piece = rs_alloc((size_t)(q - p) + 1);
        memcpy(piece, p, (size_t)(q - p));
        rs_push_Arr_string(r, piece);
        p = q + ls;
    }
    rs_push_Arr_string(r, rs_strdup(p));
    return r;
}
static const char *rs_join_Arr_string(const char *sep, Arr_string *a) {
    rs_sb b = {0};
    for (int64_t i = 0; i < a->len; i++) {
        if (i) rs_sb_cat(&b, sep);
        rs_sb_cat(&b, a->data[i]);
    }
    return b.buf ? b.buf : "";
}
"""
MAP_BASE = r"""
typedef struct @N@ { int64_t len, cap; const char **keys; @V@ *vals; } @N@;
static int64_t rs_find_@N@(@N@ *m, const char *k) {
    for (int64_t i = 0; i < m->len; i++) if (strcmp(m->keys[i], k) == 0) return i;
    return -1;
}
static void rs_set_@N@(@N@ *m, const char *k, @V@ v) {
    int64_t i = rs_find_@N@(m, k);
    if (i >= 0) { m->vals[i] = v; return; }
    if (m->len == m->cap) {
        m->cap = m->cap ? m->cap * 2 : 4;
        m->keys = rs_realloc(m->keys, (size_t)m->cap * sizeof(char *));
        m->vals = rs_realloc(m->vals, (size_t)m->cap * sizeof(@V@));
    }
    m->keys[m->len] = k;
    m->vals[m->len++] = v;
}
static @N@ *rs_newmap_@N@(int64_t n, const char **ks, const @V@ *vs) {
    @N@ *m = rs_alloc(sizeof(@N@));
    for (int64_t i = 0; i < n; i++) rs_set_@N@(m, ks[i], vs[i]);
    return m;
}
static @V@ *rs_getp_@N@(@N@ *m, const char *k, int line) {
    int64_t i = rs_find_@N@(m, k);
    if (i < 0) rs_panic("key not found: \"%s\" (line %d)", k, line);
    return &m->vals[i];
}
static @V@ rs_getd_@N@(@N@ *m, const char *k, @V@ d) {
    int64_t i = rs_find_@N@(m, k);
    return i < 0 ? d : m->vals[i];
}
static bool rs_has_@N@(@N@ *m, const char *k) { return rs_find_@N@(m, k) >= 0; }
static void rs_remove_@N@(@N@ *m, const char *k) {
    int64_t i = rs_find_@N@(m, k);
    if (i < 0) return;
    for (int64_t j = i + 1; j < m->len; j++) { m->keys[j - 1] = m->keys[j]; m->vals[j - 1] = m->vals[j]; }
    m->len--;
}
static void rs_clear_@N@(@N@ *m) { m->len = 0; }
static Arr_string *rs_keys_@N@(@N@ *m) { return rs_lit_Arr_string(m->len, m->keys); }
static @AV@ *rs_values_@N@(@N@ *m) { return rs_lit_@AV@(m->len, m->vals); }
static const char *rs_str_@N@(@N@ *m) {
    rs_sb b = {0};
    rs_sb_cat(&b, "{");
    for (int64_t i = 0; i < m->len; i++) {
        if (i) rs_sb_cat(&b, ", ");
        rs_sb_cat(&b, rs_repr_string(m->keys[i]));
        rs_sb_cat(&b, ": ");
        rs_sb_cat(&b, @REPR@(m->vals[i]));
    }
    rs_sb_cat(&b, "}");
    return b.buf;
}
"""


class CodeGen:
    def __init__(self, prog):
        self.prog = prog
        self.out, self.ind, self.tmp = [], 0, 0
        self.types, self.helpers, self.globals = set(), [], []

    # -- types
    def ctype(self, t):
        base = {"int": "int64_t", "float64": "double", "bool": "bool", "string": "const char *", "void": "void"}
        if t in base:
            return base[t]
        self.need(t)
        return mangle(t) + " *"

    def ctype_nostar(self, t):
        return self.ctype(t)

    def sub(self, tpl, **kw):
        for k, v in kw.items():
            tpl = tpl.replace(f"@{k}@", v)
        return tpl

    def need(self, t):
        if t in self.types or isinstance(t, str):
            return
        elem = t[1]
        self.need(elem)
        if t[0] == "array":
            self.need_array(t, elem)
        else:
            self.need(("array", "string"))
            self.need(("array", elem))
            self.types.add(t)
            n = mangle(t)
            self.helpers.append(self.sub(MAP_BASE, N=n, V=self.ctype(elem), AV=mangle(("array", elem)),
                                         REPR=self.repr_fn(elem)))

    def need_array(self, t, elem):
        self.types.add(t)
        n, ct = mangle(t), self.ctype(elem)
        h = self.sub(ARRAY_BASE, N=n, T=ct, REPR=self.repr_fn(elem))
        if elem in ("int", "float64", "bool", "string"):
            eq = f"strcmp(a->data[i], v) == 0" if elem == "string" else "a->data[i] == v"
            h += self.sub(ARRAY_SCALAR, N=n, T=ct, EQ=eq)
        if elem in ("int", "float64", "string"):
            h += self.sub(ARRAY_SORT, N=n, T=ct, E=("float" if elem == "float64" else elem), CMP={"int": "rs_cmp_int", "float64": "rs_cmp_float", "string": "rs_cmp_string"}[elem])
        if elem == "int":
            h += self.sub(ARRAY_SUM_INT, N=n)
        if elem == "float64":
            h += self.sub(ARRAY_SUM_FLOAT, N=n)
        if elem == "string":
            h += ARRAY_STRING
        self.helpers.append(h)

    def str_fn(self, t):
        return {"int": "rs_str_int", "float64": "rs_str_float", "bool": "rs_str_bool"}.get(t) or "rs_str_" + mangle(t)

    def repr_fn(self, t):
        return "rs_repr_string" if t == "string" else self.str_fn(t)

    def str_expr(self, e):
        c = self.expr(e)
        if e.ty == "string":
            return c
        if not isinstance(e.ty, str):
            self.need(e.ty)
        return f"{self.str_fn(e.ty)}({c})"

    # -- emit helpers
    def w(self, line):
        self.out.append("    " * self.ind + line)

    def newtmp(self):
        self.tmp += 1
        return f"_t{self.tmp}"

    # -- program
    def generate(self):
        fns = [i for i in self.prog.items if isinstance(i, A.FnDecl)]
        protos = []
        for f in fns:
            ps = ", ".join(self.ctype(t) for (_, t, _, _) in f.params) or "void"
            protos.append(f"static {self.ctype(f.sig.ret)} {f.sig.cname}({ps});")
        for f in fns:
            ps = ", ".join(f"{self.ctype(s.ty)} {s.cname}" for s in f.param_syms) or "void"
            self.w(f"static {self.ctype(f.sig.ret)} {f.sig.cname}({ps}) {{")
            self.body(f.body.stmts)
            self.w("}")
            self.w("")
        self.w("static void rs_script(void) {")
        self.ind += 1
        for it in self.prog.items:
            if not isinstance(it, A.FnDecl):
                self.stmt(it)
        self.ind -= 1
        self.w("}")
        self.w("")
        self.w("int main(void) {")
        self.w("    rs_script();")
        if self.prog.has_main:
            self.w("    rs_f_main();")
        self.w("    fflush(stdout);")
        self.w("    return 0;")
        self.w("}")
        rt = open(RT).read()
        return "\n".join([rt, ""] + self.helpers + [""] + self.globals + [""] + protos + [""] + self.out) + "\n"

    # -- statements
    def body(self, ss):
        self.ind += 1
        for s in ss:
            self.stmt(s)
        self.ind -= 1

    def stmt(self, s):
        if isinstance(s, A.VarDecl):
            v = self.expr(s.value)
            if s.sym.is_global:
                self.globals.append(f"static {self.ctype(s.sym.ty)} {s.sym.cname};")
                self.w(f"{s.sym.cname} = {v};")
            else:
                self.w(f"{self.ctype(s.sym.ty)} {s.sym.cname} = {v};")
        elif isinstance(s, A.Assign):
            self.assign(s)
        elif isinstance(s, A.ExprStmt):
            self.w(f"{self.expr(s.expr)};")
        elif isinstance(s, A.Block):
            self.w("{")
            self.body(s.stmts)
            self.w("}")
        elif isinstance(s, A.If):
            self.w(f"if ({self.expr(s.cond)}) {{")
            self.body(s.then.stmts)
            if s.els is None:
                self.w("}")
            else:
                self.w("} else {")
                self.body(s.els.stmts if isinstance(s.els, A.Block) else [s.els])
                self.w("}")
        elif isinstance(s, A.While):
            self.w(f"while ({self.expr(s.cond)}) {{")
            self.body(s.body.stmts)
            self.w("}")
        elif isinstance(s, A.ForRange):
            lo, hi, st = self.newtmp(), self.newtmp(), self.newtmp()
            v = s.sym.cname
            self.w("{")
            self.ind += 1
            self.w(f"int64_t {lo} = {self.expr(s.lo)};")
            self.w(f"int64_t {hi} = {self.expr(s.hi)};")
            if s.step is None:
                self.w(f"for (int64_t {v} = {lo}; {v} < {hi}; {v}++) {{")
            else:
                self.w(f"int64_t {st} = {self.expr(s.step)};")
                self.w(f'if ({st} == 0) rs_panic("range() step must not be zero (line {s.line})");')
                self.w(f"for (int64_t {v} = {lo}; {st} > 0 ? {v} < {hi} : {v} > {hi}; {v} = (int64_t)((uint64_t){v} + (uint64_t){st})) {{")
            self.body(s.body.stmts)
            self.w("}")
            self.ind -= 1
            self.w("}")
        elif isinstance(s, A.ForEach):
            self.foreach(s)
        elif isinstance(s, A.ForMap):
            m, i = self.newtmp(), self.newtmp()
            self.w("{")
            self.ind += 1
            self.w(f"{self.ctype(s.iter.ty)}{m} = {self.expr(s.iter)};")
            self.w(f"for (int64_t {i} = 0; {i} < {m}->len; {i}++) {{")
            self.ind += 1
            self.w(f"const char *{s.ksym.cname} = {m}->keys[{i}];")
            self.w(f"{self.ctype(s.vsym.ty)} {s.vsym.cname} = {m}->vals[{i}];")
            self.ind -= 1
            self.body(s.body.stmts)
            self.w("}")
            self.ind -= 1
            self.w("}")
        elif isinstance(s, A.Return):
            self.w("return;" if s.value is None else f"return {self.expr(s.value)};")
        elif isinstance(s, A.Break):
            self.w("break;")
        elif isinstance(s, A.Continue):
            self.w("continue;")
        else:
            raise AssertionError(s)

    def foreach(self, s):
        it, i = self.newtmp(), self.newtmp()
        t = s.iter.ty
        self.w("{")
        self.ind += 1
        if t == "string":
            self.w(f"const char *{it} = {self.expr(s.iter)};")
            self.w(f"int64_t {i}n = (int64_t)strlen({it});")
            self.w(f"for (int64_t {i} = 0; {i} < {i}n; {i}++) {{")
            elem = f"rs_char_at({it}, {i}, {s.line})"
        else:
            self.w(f"{self.ctype(t)}{it} = {self.expr(s.iter)};")
            self.w(f"for (int64_t {i} = 0; {i} < {it}->len; {i}++) {{")
            elem = f"{it}->data[{i}]" if is_arr(t) else f"{it}->keys[{i}]"
        self.ind += 1
        self.w(f"{self.ctype(s.sym.ty)} {s.sym.cname} = {elem};")
        self.ind -= 1
        self.body(s.body.stmts)
        self.w("}")
        self.ind -= 1
        self.w("}")

    def assign(self, s):
        t = s.target
        v = self.expr(s.value)
        vt = self.newtmp()
        self.w("{")
        self.ind += 1
        self.w(f"{self.ctype(s.value.ty)} {vt} = {v};")  # right-hand side first
        if isinstance(t, A.Ident):
            lv = t.sym.cname
            rhs = vt if s.op == "=" else self.binop(s.op[0], t.ty, lv, vt, s.line)
            self.w(f"{lv} = {rhs};")
        elif is_map(t.obj.ty):
            n, m, k = mangle(t.obj.ty), self.newtmp(), self.newtmp()
            self.w(f"{self.ctype(t.obj.ty)}{m} = {self.expr(t.obj)};")
            self.w(f"const char *{k} = {self.expr(t.index)};")
            if s.op == "=":
                self.w(f"rs_set_{n}({m}, {k}, {vt});")
            else:
                cur = f"(*rs_getp_{n}({m}, {k}, {t.line}))"
                self.w(f"rs_set_{n}({m}, {k}, {self.binop(s.op[0], t.ty, cur, vt, s.line)});")
        else:
            p = self.newtmp()
            self.w(f"{self.ctype(t.ty)} *{p} = rs_at_{mangle(t.obj.ty)}({self.expr(t.obj)}, {self.expr(t.index)}, {t.line});")
            lv = f"(*{p})"
            rhs = vt if s.op == "=" else self.binop(s.op[0], t.ty, lv, vt, s.line)
            self.w(f"{lv} = {rhs};")
        self.ind -= 1
        self.w("}")

    # -- expressions
    def ordered(self, nodes, codes, build, ctypes=None):
        """R# evaluates operands left to right; C does not. When two or more operands
        contain calls, bind them to temporaries in order using a GNU statement expression."""
        if sum(1 for n in nodes if has_call(n)) < 2:
            return build(codes)
        decls, names = [], []
        for n, c, ct in zip(nodes, codes, ctypes or [self.ctype(n.ty) for n in nodes]):
            t = self.newtmp()
            decls.append(f"{ct} {t} = {c};")
            names.append(t)
        return "({ " + " ".join(decls) + " " + build(names) + "; })"

    def binop(self, op, ty, a, b, line):
        if ty == "string":
            return f"rs_concat({a}, {b})"
        if ty == "int":
            if op in INT_OPS:
                return f"{INT_OPS[op]}({a}, {b})"
            return f"rs_div({a}, {b}, {line})" if op == "/" else f"rs_mod({a}, {b}, {line})"
        return f"({a} {op} {b})"

    def expr(self, e):
        if isinstance(e, A.IntLit):
            return f"INT64_C({e.value})"
        if isinstance(e, A.FloatLit):
            r = repr(e.value)
            return r if any(c in r for c in ".e") else r + ".0"
        if isinstance(e, A.StrLit):
            return c_escape(e.value)
        if isinstance(e, A.BoolLit):
            return "true" if e.value else "false"
        if isinstance(e, A.Interp):
            nodes = [p for p in e.parts if not isinstance(p, str)]
            codes = [self.str_expr(p) for p in nodes]

            def build(names):
                it, acc = iter(names), None
                for p in e.parts:
                    piece = c_escape(p) if isinstance(p, str) else next(it)
                    acc = piece if acc is None else f"rs_concat({acc}, {piece})"
                return acc or '""'
            return self.ordered(nodes, codes, build, ["const char *"] * len(nodes))
        if isinstance(e, A.Ident):
            return self.const_ref(e) if e.cref else e.sym.cname
        if isinstance(e, A.Unary):
            o = self.expr(e.operand)
            if e.op == "!":
                return f"(!{o})"
            return f"rs_sub(0, {o})" if e.ty == "int" else f"(-{o})"
        if isinstance(e, A.Binary):
            return self.binary(e)
        if isinstance(e, A.ArrayLit):
            self.need(e.ty)
            n = mangle(e.ty)
            if not e.elems:
                return f"rs_lit_{n}(0, NULL)"
            ct = self.ctype(e.ty[1])
            return self.ordered(e.elems, [self.expr(x) for x in e.elems],
                                lambda nm: f"rs_lit_{n}({len(nm)}, ({ct}[]){{{', '.join(nm)}}})")
        if isinstance(e, A.MapLit):
            self.need(e.ty)
            n = mangle(e.ty)
            if not e.keys:
                return f"rs_newmap_{n}(0, NULL, NULL)"
            vt = self.ctype(e.ty[1])
            nodes = [x for kv in zip(e.keys, e.values) for x in kv]
            ctypes = ["const char *", vt] * len(e.keys)
            return self.ordered(nodes, [self.expr(x) for x in nodes],
                                lambda nm: f"rs_newmap_{n}({len(e.keys)}, (const char*[]){{{', '.join(nm[0::2])}}}, ({vt}[]){{{', '.join(nm[1::2])}}})",
                                ctypes)
        if isinstance(e, A.Index):
            t = e.obj.ty
            if t == "string":
                f = lambda n: f"rs_char_at({n[0]}, {n[1]}, {e.line})"
            elif is_map(t):
                f = lambda n: f"(*rs_getp_{mangle(t)}({n[0]}, {n[1]}, {e.line}))"
            else:
                f = lambda n: f"(*rs_at_{mangle(t)}({n[0]}, {n[1]}, {e.line}))"
            return self.ordered([e.obj, e.index], [self.expr(e.obj), self.expr(e.index)], f)
        if isinstance(e, A.Slice):
            parts = [e.obj] + ([e.lo] if e.lo else []) + ([e.hi] if e.hi else [])

            def build(n):
                it = iter(n)
                o = next(it)
                lo = next(it) if e.lo else "0"
                hi = next(it) if e.hi else "0"
                f = "rs_slice_str" if e.obj.ty == "string" else f"rs_slice_{mangle(e.obj.ty)}"
                return f"{f}({o}, {lo}, {hi}, {int(bool(e.lo))}, {int(bool(e.hi))})"
            return self.ordered(parts, [self.expr(x) for x in parts], build)
        if isinstance(e, A.Member):
            if getattr(e, "is_module", False):
                return self.const_ref(e)
            return self.length(e.obj)
        if isinstance(e, A.Call):
            return self.call(e)
        raise AssertionError(e)

    def const_ref(self, e):
        kind, v = e.cref
        return v if kind == "native" else v.cname

    def length(self, o):
        c = self.expr(o)
        return f"((int64_t)strlen({c}))" if o.ty == "string" else f"({c})->len"

    def binary(self, e):
        op, lt, rt = e.op, e.left.ty, e.right.ty
        a, b = self.expr(e.left), self.expr(e.right)
        if op in ("&&", "||"):
            return f"({a} {op} {b})"  # short-circuit: ordered in C already
        if op in ("in", "not in"):
            if rt == "string":
                f = lambda n: f"rs_contains({n[1]}, {n[0]})"
            elif is_arr(rt):
                self.need(rt)
                f = lambda n: f"rs_contains_{mangle(rt)}({n[1]}, {n[0]})"
            else:
                self.need(rt)
                f = lambda n: f"rs_has_{mangle(rt)}({n[1]}, {n[0]})"
            g = (lambda n: f"(!{f(n)})") if op == "not in" else f
            return self.ordered([e.left, e.right], [a, b], g)
        if op == "*" and "string" in (lt, rt) and lt != rt:
            sa = a if lt == "string" else b
            na = b if lt == "string" else a
            nodes = [e.left, e.right]
            return self.ordered(nodes, [a, b], lambda n: f"rs_repeat({n[0] if lt == 'string' else n[1]}, {n[1] if lt == 'string' else n[0]})")
        if op == "**":
            g = (lambda n: f"rs_ipow({n[0]}, {n[1]})") if lt == "int" else (lambda n: f"pow({n[0]}, {n[1]})")
            return self.ordered([e.left, e.right], [a, b], g)
        if op in CMP:
            if lt == "string":
                f = lambda n: f"(strcmp({n[0]}, {n[1]}) {op} 0)"
            else:
                f = lambda n: f"({n[0]} {op} {n[1]})"
        else:
            f = lambda n: self.binop(op, lt, n[0], n[1], e.line)
        return self.ordered([e.left, e.right], [a, b], f)

    def call(self, e):
        k = e.kind
        args = e.args
        if k == "user":
            return self.ordered(args, [self.expr(a) for a in args], lambda n: f"{e.sig.cname}({', '.join(n)})")
        if k == "native":
            params, _, fmt = e.native
            codes = [f"((double)({self.expr(a)}))" if p == "num" else self.expr(a) for a, p in zip(args, params)]
            return self.ordered(args, codes, lambda n: fmt.format(*n), ["double" if p == "num" else self.ctype(a.ty) for a, p in zip(args, params)])
        if k in ("smethod", "amethod", "mmethod"):
            return self.method(e)
        return self.builtin(e, k)

    def method(self, e):
        o, name, args = e.callee.obj, e.mname, e.args
        nodes = [o] + args
        codes = [self.expr(x) for x in nodes]
        t = o.ty
        if e.kind == "smethod":
            if name == "join":
                self.need(("array", "string"))
                return self.ordered(nodes, codes, lambda n: f"rs_join_Arr_string({n[0]}, {n[1]})")
            if name == "split":
                self.need(("array", "string"))
            return self.ordered(nodes, codes, lambda n: f"{STR_FN[name]}({', '.join(n)})")
        n = mangle(t)
        self.need(t)
        if e.kind == "amethod":
            fn = {"append": "push"}.get(name, name)
            return self.ordered(nodes, codes, lambda nm: f"rs_{fn}_{n}({', '.join(nm)})")
        fn = {"get": "getd"}.get(name, name)
        return self.ordered(nodes, codes, lambda nm: f"rs_{fn}_{n}({', '.join(nm)})")

    def builtin(self, e, k):
        args = e.args
        if k == "print":
            parts = []
            for i, a in enumerate(args):
                if i:
                    parts.append("rs_print_sp()")
                t = a.ty
                if t == "int":
                    parts.append(f"rs_print_int({self.expr(a)})")
                elif t == "float64":
                    parts.append(f"rs_print_float({self.expr(a)})")
                elif t == "bool":
                    parts.append(f"rs_print_bool({self.expr(a)})")
                else:
                    parts.append(f"rs_print_str({self.str_expr(a)})")
            parts.append("rs_print_nl()")
            return "(" + ", ".join(parts) + ")"
        codes = [self.expr(a) for a in args]
        t0 = args[0].ty if args else None
        if k == "len":
            return self.length(args[0])
        if k == "int":
            return {"float64": f"rs_f2i({codes[0]})", "string": f"rs_parse_int({codes[0]})"}.get(t0, codes[0])
        if k == "float64":
            return f"rs_parse_float({codes[0]})" if t0 == "string" else f"((double){codes[0]})"
        if k == "str":
            return self.str_expr(args[0])
        if k == "range":
            self.need(("array", "int"))
            c = (["INT64_C(0)"] + codes + ["INT64_C(1)"])[:3] if len(codes) == 1 else (codes + ["INT64_C(1)"])[:3]
            if len(codes) == 1:
                c = ["INT64_C(0)", codes[0], "INT64_C(1)"]
            return self.ordered(args, codes, lambda n: "rs_range_Arr_int(" + ", ".join(
                (["INT64_C(0)", n[0], "INT64_C(1)"] if len(n) == 1 else (n + ["INT64_C(1)"])[:3])) + ")")
        if k == "input":
            return f"rs_input({codes[0] if codes else chr(34) * 2})"
        if k == "abs":
            return f"rs_abs({codes[0]})" if t0 == "int" else f"fabs({codes[0]})"
        if k in ("min", "max"):
            if len(args) == 1:
                self.need(t0)
                return f"rs_{k}_{mangle(t0)}({codes[0]})"
            return self.ordered(args, codes, lambda n: f"rs_{k}_{t0 if t0 != 'float64' else 'float'}({n[0]}, {n[1]})")
        if k in ("sum", "sorted", "reversed"):
            self.need(t0)
            return f"rs_{k}_{mangle(t0)}({codes[0]})"
        if k == "round":
            return f"rs_f2i(rint({codes[0]}))" if t0 == "float64" else codes[0]
        if k == "read_file":
            return f"rs_read_file({codes[0]})"
        if k == "write_file":
            return self.ordered(args, codes, lambda n: f"rs_write_file({n[0]}, {n[1]})")
        if k == "exit":
            return f"rs_exit({codes[0]})"
        if k == "assert":
            return self.ordered(args, codes, lambda n: f"rs_assert({n[0]}, {n[1] if len(n) > 1 else chr(34) * 2}, {e.line})")
        if k == "ord":
            return f"rs_ord({codes[0]})"
        if k == "chr":
            return f"rs_chr({codes[0]})"
        raise AssertionError(k)


def generate(prog):
    return CodeGen(prog).generate()
