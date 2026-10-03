"""Name resolution + type checking. Annotates AST nodes with `.ty` and symbols."""
from . import ast as A
from .errors import RSharpError


def tstr(t):
    return t if isinstance(t, str) else tstr(t[1]) + "[]"


class Sym:
    def __init__(self, name, ty, mutable, cname, is_global=False):
        self.name, self.ty, self.mutable, self.cname, self.is_global = name, ty, mutable, cname, is_global


class FnSig:
    def __init__(self, name, params, ret, cname):
        self.name, self.params, self.ret, self.cname = name, params, ret, cname


BUILTINS = {"print", "len", "int", "float64", "str"}
NUMERIC = ("int", "float64")


class Checker:
    def __init__(self, prog):
        self.prog = prog
        self.fns, self.global_consts = {}, {}
        self.scopes, self.uid = [], 0
        self.cur_ret, self.in_fn, self.loops = None, False, 0

    def err(self, msg, n):
        raise RSharpError(msg, n.line, n.col)

    def run(self):
        for it in self.prog.items:
            if isinstance(it, A.FnDecl):
                self.register(it)
        m = self.fns.get("main")
        if m and (m.params or m.ret != "void"):
            raise RSharpError("'main' must take no parameters and return nothing", 1, 1)
        self.prog.has_main = m is not None
        self.scopes = [{}]
        for it in self.prog.items:
            if isinstance(it, A.FnDecl):
                self.check_fn(it)
            else:
                self.stmt(it)
        return self.prog

    # -- scopes
    def declare(self, name, ty, mutable, node, is_global=False):
        if name in self.scopes[-1]:
            self.err(f"'{name}' is already declared in this scope", node)
        self.uid += 1
        cname = f"rs_{'g_' if is_global else ''}{name}_{self.uid}"
        sym = Sym(name, ty, mutable, cname, is_global)
        self.scopes[-1][name] = sym
        return sym

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    # -- functions
    def register(self, fn):
        if fn.name in self.fns:
            self.err(f"function '{fn.name}' is already defined", fn)
        if fn.name in BUILTINS:
            self.err(f"'{fn.name}' is a built-in function and cannot be redefined", fn)
        ret = fn.ret or "void"
        seen = set()
        for (pn, pt, l, c) in fn.params:
            if pn in seen:
                raise RSharpError(f"duplicate parameter '{pn}'", l, c)
            seen.add(pn)
            if pt == "void":
                raise RSharpError("parameter cannot be void", l, c)
        fn.sig = FnSig(fn.name, [p[1] for p in fn.params], ret, f"rs_f_{fn.name}")
        self.fns[fn.name] = fn.sig

    def check_fn(self, fn):
        saved = (self.scopes, self.cur_ret, self.in_fn, self.loops)
        self.scopes = [dict(self.global_consts), {}]
        self.cur_ret, self.in_fn, self.loops = fn.sig.ret, True, 0
        fn.param_syms = [self.declare(n, t, False, fn) for (n, t, _, _) in fn.params]
        self.block(fn.body, new_scope=True)
        if fn.sig.ret != "void" and not self.always_returns(fn.body):
            self.err(f"function '{fn.name}' may finish without returning a {tstr(fn.sig.ret)}", fn)
        self.scopes, self.cur_ret, self.in_fn, self.loops = saved

    def always_returns(self, s):
        if isinstance(s, A.Block):
            return any(self.always_returns(x) for x in s.stmts)
        if isinstance(s, A.Return):
            return True
        if isinstance(s, A.If):
            return s.els is not None and self.always_returns(s.then) and self.always_returns(s.els)
        return False

    # -- statements
    def block(self, b, new_scope=True):
        if new_scope:
            self.scopes.append({})
        for s in b.stmts:
            self.stmt(s)
        if new_scope:
            self.scopes.pop()

    def stmt(self, s):
        if isinstance(s, A.VarDecl):
            vt = self.expr(s.value, s.declty)
            if vt == "void":
                self.err("cannot assign a void value to a variable", s.value)
            if s.declty and vt != s.declty:
                self.err(f"cannot initialize '{s.name}' of type {tstr(s.declty)} with {tstr(vt)}", s.value)
            ty = s.declty or vt
            top = (not self.in_fn) and len(self.scopes) == 1
            is_global = top and s.kind == "const"
            s.sym = self.declare(s.name, ty, s.kind == "mut", s, is_global)
            if is_global:
                self.global_consts[s.name] = s.sym
        elif isinstance(s, A.Assign):
            self.assign(s)
        elif isinstance(s, A.If):
            self.expect_type(self.expr(s.cond), "bool", s.cond, "condition")
            self.block(s.then)
            if s.els is not None:
                self.stmt(s.els) if isinstance(s.els, A.If) else self.block(s.els)
        elif isinstance(s, A.While):
            self.expect_type(self.expr(s.cond), "bool", s.cond, "condition")
            self.loops += 1
            self.block(s.body)
            self.loops -= 1
        elif isinstance(s, A.ForEach):
            it = self.expr(s.iter)
            if not (isinstance(it, tuple) and it[0] == "array"):
                self.err(f"can only iterate over arrays or ranges, not {tstr(it)}", s.iter)
            self.loop_body(s, it[1])
        elif isinstance(s, A.ForRange):
            self.expect_type(self.expr(s.lo), "int", s.lo, "range start")
            self.expect_type(self.expr(s.hi), "int", s.hi, "range end")
            self.loop_body(s, "int")
        elif isinstance(s, A.Return):
            if self.cur_ret is None:
                self.err("'return' outside of a function", s)
            if s.value is None:
                if self.cur_ret != "void":
                    self.err(f"must return a value of type {tstr(self.cur_ret)}", s)
            else:
                if self.cur_ret == "void":
                    self.err("function returns nothing; cannot return a value", s)
                self.expect_type(self.expr(s.value, self.cur_ret), self.cur_ret, s.value, "return value")
        elif isinstance(s, (A.Break, A.Continue)):
            if not self.loops:
                self.err(f"'{'break' if isinstance(s, A.Break) else 'continue'}' outside of a loop", s)
        elif isinstance(s, A.ExprStmt):
            self.expr(s.expr)
        elif isinstance(s, A.Block):
            self.block(s)
        else:
            self.err("unsupported statement", s)

    def loop_body(self, s, elem):
        self.scopes.append({})
        s.sym = self.declare(s.var, elem, False, s)
        self.loops += 1
        self.block(s.body, new_scope=False)
        self.loops -= 1
        self.scopes.pop()

    def root_ident(self, e):
        while isinstance(e, (A.Index, A.Member)):
            e = e.obj
        return e if isinstance(e, A.Ident) else None

    def require_mutable(self, target, what):
        r = self.root_ident(target)
        if r is None or r.sym is None:
            self.err(f"cannot {what} this expression", target)
        if not r.sym.mutable:
            self.err(f"cannot {what} '{r.name}': it is immutable (declare it with 'mut')", target)

    def assign(self, s):
        tt = self.expr(s.target)
        if isinstance(s.target, A.Ident):
            self.require_mutable(s.target, "assign to")
        else:
            self.require_mutable(s.target, "modify elements of")
        vt = self.expr(s.value, tt if s.op == "=" else None)
        if s.op == "=":
            if vt != tt:
                self.err(f"cannot assign {tstr(vt)} to {tstr(tt)}", s.value)
            return
        if vt != tt:
            self.err(f"'{s.op}' needs matching types, got {tstr(tt)} and {tstr(vt)}", s.value)
        ok = (tt == "string" and s.op == "+=") or (tt in NUMERIC and s.op != "%=") or (tt == "int" and s.op == "%=")
        if not ok:
            self.err(f"'{s.op}' cannot be applied to {tstr(tt)}", s)

    def expect_type(self, got, want, node, what):
        if got != want:
            self.err(f"{what} must be {tstr(want)}, found {tstr(got)}", node)

    # -- expressions
    def expr(self, e, expected=None):
        e.ty = self.expr_inner(e, expected)
        return e.ty

    def expr_inner(self, e, expected):
        if isinstance(e, A.IntLit):
            return "int"
        if isinstance(e, A.FloatLit):
            return "float64"
        if isinstance(e, A.StrLit):
            return "string"
        if isinstance(e, A.BoolLit):
            return "bool"
        if isinstance(e, A.Interp):
            for p in e.parts:
                if not isinstance(p, str):
                    t = self.expr(p)
                    if t == "void":
                        self.err("cannot interpolate a void value", p)
            return "string"
        if isinstance(e, A.Ident):
            e.sym = self.lookup(e.name)
            if e.sym is None:
                if e.name in self.fns or e.name in BUILTINS:
                    self.err(f"functions are not first-class values in v0.1; call '{e.name}(...)'", e)
                self.err(f"undefined variable '{e.name}'", e)
            return e.sym.ty
        if isinstance(e, A.Unary):
            t = self.expr(e.operand)
            if e.op == "-" and t in NUMERIC:
                return t
            if e.op == "!" and t == "bool":
                return t
            self.err(f"cannot apply '{e.op}' to {tstr(t)}", e)
        if isinstance(e, A.Binary):
            return self.binary(e)
        if isinstance(e, A.ArrayLit):
            return self.array_lit(e, expected)
        if isinstance(e, A.Index):
            ot = self.expr(e.obj)
            if not (isinstance(ot, tuple) and ot[0] == "array"):
                self.err(f"cannot index into {tstr(ot)}", e)
            self.expect_type(self.expr(e.index), "int", e.index, "index")
            return ot[1]
        if isinstance(e, A.Member):
            ot = self.expr(e.obj)
            if e.name == "length" and (ot == "string" or (isinstance(ot, tuple))):
                return "int"
            self.err(f"{tstr(ot)} has no property '{e.name}'", e)
        if isinstance(e, A.Call):
            return self.call(e)
        self.err("unsupported expression", e)

    def array_lit(self, e, expected):
        if not e.elems:
            if isinstance(expected, tuple):
                return expected
            self.err("cannot infer the element type of an empty array; add a type annotation", e)
        want = expected[1] if isinstance(expected, tuple) else None
        first = self.expr(e.elems[0], want)
        if first == "void":
            self.err("array elements cannot be void", e.elems[0])
        for x in e.elems[1:]:
            t = self.expr(x, first)
            if t != first:
                self.err(f"array elements must all be {tstr(first)}, found {tstr(t)}", x)
        return ("array", first)

    def binary(self, e):
        op = e.op
        lt, rt = self.expr(e.left), self.expr(e.right)
        bad = f"cannot apply '{op}' to {tstr(lt)} and {tstr(rt)}"
        if lt != rt:
            hint = " (R# never converts numbers implicitly; use int(...) or float64(...))" \
                if {lt, rt} == {"int", "float64"} else ""
            self.err(bad + hint, e)
        if op in ("&&", "||"):
            if lt != "bool":
                self.err(bad, e)
            return "bool"
        if op in ("==", "!="):
            if isinstance(lt, tuple) or lt == "void":
                self.err(f"'{op}' is not supported for {tstr(lt)} in v0.1", e)
            return "bool"
        if op in ("<", "<=", ">", ">="):
            if lt not in NUMERIC and lt != "string":
                self.err(bad, e)
            return "bool"
        if op == "+" and lt == "string":
            return "string"
        if op == "%" and lt == "int":
            return "int"
        if op != "%" and lt in NUMERIC:
            return lt
        self.err(bad, e)

    def call(self, e):
        c = e.callee
        if isinstance(c, A.Member):
            ot = self.expr(c.obj)
            if c.name == "push" and isinstance(ot, tuple):
                if len(e.args) != 1:
                    self.err("push expects exactly 1 argument", e)
                self.require_mutable(c.obj, "push to")
                self.expect_type(self.expr(e.args[0], ot[1]), ot[1], e.args[0], "pushed value")
                e.kind = "push"
                return "void"
            self.err(f"{tstr(ot)} has no method '{c.name}'", c)
        if not isinstance(c, A.Ident):
            self.err("only named functions can be called in v0.1", e)
        name = c.name
        if name in self.fns:
            sig = self.fns[name]
            if len(e.args) != len(sig.params):
                self.err(f"'{name}' expects {len(sig.params)} argument(s), got {len(e.args)}", e)
            for a, pt in zip(e.args, sig.params):
                self.expect_type(self.expr(a, pt), pt, a, f"argument to '{name}'")
            e.kind, e.sig = "user", sig
            return sig.ret
        if name in BUILTINS:
            e.kind = name
            ts = [self.expr(a) for a in e.args]
            for a, t in zip(e.args, ts):
                if t == "void":
                    self.err("cannot use a void value as an argument", a)
            if name == "print":
                return "void"
            if len(e.args) != 1:
                self.err(f"'{name}' expects exactly 1 argument", e)
            t = ts[0]
            if name == "len":
                if t == "string" or isinstance(t, tuple):
                    return "int"
                self.err(f"len() needs a string or array, found {tstr(t)}", e.args[0])
            if name == "int":
                if t in ("int", "float64"):
                    return "int"
                self.err(f"cannot convert {tstr(t)} to int", e.args[0])
            if name == "float64":
                if t in ("int", "float64"):
                    return "float64"
                self.err(f"cannot convert {tstr(t)} to float64", e.args[0])
            return "string"  # str
        self.err(f"undefined function '{name}'", c)


def check(prog):
    return Checker(prog).run()
