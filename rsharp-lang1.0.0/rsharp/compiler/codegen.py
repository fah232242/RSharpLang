"""Typed AST -> C11 source. gcc turns the C into a native executable."""
import os
from . import ast as A

RT = os.path.join(os.path.dirname(__file__), "..", "runtime", "rt.h")
CMP = {"==": "==", "!=": "!=", "<": "<", "<=": "<=", ">": ">", ">=": ">="}
INT_OPS = {"+": "rs_add", "-": "rs_sub", "*": "rs_mul"}


def mangle(t):
    return t if isinstance(t, str) else "Arr_" + mangle(t[1])


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


class CodeGen:
    def __init__(self, prog):
        self.prog = prog
        self.out, self.ind = [], 0
        self.tmp = 0
        self.arrays, self.helpers = set(), []
        self.globals = []

    # -- types
    def ctype(self, t):
        if t == "int":
            return "int64_t"
        if t == "float64":
            return "double"
        if t == "bool":
            return "bool"
        if t == "string":
            return "const char *"
        if t == "void":
            return "void"
        self.need_array(t)
        return mangle(t) + " *"

    def need_array(self, t):
        if t in self.arrays:
            return
        elem = t[1]
        if isinstance(elem, tuple):
            self.need_array(elem)
        self.arrays.add(t)
        n, ct = mangle(t), self.ctype(elem)
        self.helpers.append(f"""typedef struct {n} {{ int64_t len, cap; {ct} *data; }} {n};
static {n} *rs_lit_{n}(int64_t n, const {ct} *src) {{
    {n} *a = rs_alloc(sizeof({n}));
    a->len = a->cap = n;
    a->data = n ? rs_alloc((size_t)n * sizeof({ct})) : NULL;
    if (n) memcpy(a->data, src, (size_t)n * sizeof({ct}));
    return a;
}}
static void rs_push_{n}({n} *a, {ct} v) {{
    if (a->len == a->cap) {{
        a->cap = a->cap ? a->cap * 2 : 4;
        a->data = rs_realloc(a->data, (size_t)a->cap * sizeof({ct}));
    }}
    a->data[a->len++] = v;
}}
static {ct} *rs_at_{n}({n} *a, int64_t i, int line) {{
    if (i < 0 || i >= a->len) rs_panic_index(i, a->len, line);
    return &a->data[i];
}}
static const char *rs_str_{n}({n} *a) {{
    rs_sb b = {{0}};
    rs_sb_cat(&b, "[");
    for (int64_t i = 0; i < a->len; i++) {{
        if (i) rs_sb_cat(&b, ", ");
        rs_sb_cat(&b, {self.repr_fn(elem)}(a->data[i]));
    }}
    rs_sb_cat(&b, "]");
    return b.buf;
}}""")

    def repr_fn(self, t):
        return {"int": "rs_str_int", "float64": "rs_str_float", "bool": "rs_str_bool",
                "string": "rs_repr_string"}.get(t) or "rs_str_" + mangle(t)

    def str_expr(self, e):
        c = self.expr(e)
        t = e.ty
        if t == "string":
            return c
        if isinstance(t, tuple):
            self.need_array(t)
        return {"int": "rs_str_int", "float64": "rs_str_float", "bool": "rs_str_bool"}.get(t, "rs_str_" + mangle(t)) + f"({c})"

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
            ps = ", ".join(f"{self.ctype(t)}" for (_, t, _, _) in f.params) or "void"
            protos.append(f"static {self.ctype(f.sig.ret)} {f.sig.cname}({ps});")
        for f in fns:
            ps = ", ".join(f"{self.ctype(s.ty)} {s.cname}" for s in f.param_syms) or "void"
            self.w(f"static {self.ctype(f.sig.ret)} {f.sig.cname}({ps}) {{")
            self.ind += 1
            self.stmts(f.body.stmts)
            self.ind -= 1
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
    def stmts(self, ss):
        for s in ss:
            self.stmt(s)

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
            self.ind += 1
            self.stmts(s.stmts)
            self.ind -= 1
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
            lo, hi = self.newtmp(), self.newtmp()
            self.w("{")
            self.ind += 1
            self.w(f"int64_t {lo} = {self.expr(s.lo)};")
            self.w(f"int64_t {hi} = {self.expr(s.hi)};")
            self.w(f"for (int64_t {s.sym.cname} = {lo}; {s.sym.cname} < {hi}; {s.sym.cname}++) {{")
            self.body(s.body.stmts)
            self.w("}")
            self.ind -= 1
            self.w("}")
        elif isinstance(s, A.ForEach):
            arr, i = self.newtmp(), self.newtmp()
            self.w("{")
            self.ind += 1
            self.w(f"{self.ctype(s.iter.ty)}{arr} = {self.expr(s.iter)};")
            self.w(f"for (int64_t {i} = 0; {i} < {arr}->len; {i}++) {{")
            self.ind += 1
            self.w(f"{self.ctype(s.sym.ty)} {s.sym.cname} = {arr}->data[{i}];")
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

    def body(self, ss):
        self.ind += 1
        self.stmts(ss)
        self.ind -= 1

    def assign(self, s):
        t = s.target
        v = self.expr(s.value)
        vt = self.newtmp()
        self.w("{")
        self.ind += 1
        self.w(f"{self.ctype(s.value.ty)} {vt} = {v};")  # right-hand side first
        if isinstance(t, A.Ident):
            lv = t.sym.cname
        else:
            p = self.newtmp()
            n = mangle(t.obj.ty)
            self.w(f"{self.ctype(t.ty)} *{p} = rs_at_{n}({self.expr(t.obj)}, {self.expr(t.index)}, {t.line});")
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
                it = iter(names)
                acc = None
                for p in e.parts:
                    piece = c_escape(p) if isinstance(p, str) else next(it)
                    acc = piece if acc is None else f"rs_concat({acc}, {piece})"
                return acc or '""'
            return self.ordered(nodes, codes, build, ["const char *"] * len(nodes))
        if isinstance(e, A.Ident):
            return e.sym.cname
        if isinstance(e, A.Unary):
            o = self.expr(e.operand)
            if e.op == "!":
                return f"(!{o})"
            return f"rs_sub(0, {o})" if e.ty == "int" else f"(-{o})"
        if isinstance(e, A.Binary):
            a, b = self.expr(e.left), self.expr(e.right)
            if e.op in ("&&", "||"):
                return f"({a} {e.op} {b})"  # short-circuit: already ordered in C
            if e.op in CMP:
                if e.left.ty == "string":
                    f = lambda n: f"(strcmp({n[0]}, {n[1]}) {CMP[e.op]} 0)"
                else:
                    f = lambda n: f"({n[0]} {e.op} {n[1]})"
            else:
                f = lambda n: self.binop(e.op, e.left.ty, n[0], n[1], e.line)
            return self.ordered([e.left, e.right], [a, b], f)
        if isinstance(e, A.ArrayLit):
            n = mangle(e.ty)
            self.need_array(e.ty)
            if not e.elems:
                return f"rs_lit_{n}(0, NULL)"
            ct = self.ctype(e.ty[1])
            codes = [self.expr(x) for x in e.elems]
            return self.ordered(e.elems, codes,
                                lambda nm: f"rs_lit_{n}({len(nm)}, ({ct}[]){{{', '.join(nm)}}})")
        if isinstance(e, A.Index):
            return self.ordered([e.obj, e.index], [self.expr(e.obj), self.expr(e.index)],
                                lambda n: f"(*rs_at_{mangle(e.obj.ty)}({n[0]}, {n[1]}, {e.line}))")
        if isinstance(e, A.Member):  # .length
            return self.length(e.obj)
        if isinstance(e, A.Call):
            return self.call(e)
        raise AssertionError(e)

    def length(self, o):
        c = self.expr(o)
        return f"((int64_t)strlen({c}))" if o.ty == "string" else f"({c})->len"

    def call(self, e):
        k = e.kind
        if k == "user":
            return self.ordered(e.args, [self.expr(a) for a in e.args],
                                lambda n: f"{e.sig.cname}({', '.join(n)})")
        if k == "push":
            o, a = e.callee.obj, e.args[0]
            return self.ordered([o, a], [self.expr(o), self.expr(a)],
                                lambda n: f"rs_push_{mangle(o.ty)}({n[0]}, {n[1]})")
        if k == "len":
            return self.length(e.args[0])
        if k == "int":
            a = e.args[0]
            return f"rs_f2i({self.expr(a)})" if a.ty == "float64" else self.expr(a)
        if k == "float64":
            return f"((double){self.expr(e.args[0])})"
        if k == "str":
            return self.str_expr(e.args[0])
        if k == "print":
            parts = []
            for i, a in enumerate(e.args):
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
        raise AssertionError(k)


def generate(prog):
    return CodeGen(prog).generate()
