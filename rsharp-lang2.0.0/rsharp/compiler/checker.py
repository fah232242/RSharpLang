"""Name resolution + type checking. Annotates AST nodes with `.ty` and resolved symbols."""
from . import ast as A
from .errors import RSharpError
from .natives import FUNCS, CONSTS


def is_arr(t):
    return isinstance(t, tuple) and t[0] == "array"


def is_map(t):
    return isinstance(t, tuple) and t[0] == "map"


def tstr(t):
    if isinstance(t, str):
        return t
    if t[0] == "struct":
        return t[1]
    return tstr(t[1]) + "[]" if t[0] == "array" else f"map<{tstr(t[1])}>"


class Sym:
    def __init__(self, name, ty, mutable, cname, is_global=False):
        self.name, self.ty, self.mutable, self.cname, self.is_global = name, ty, mutable, cname, is_global


class FnSig:
    def __init__(self, name, params, ret, cname):
        self.name, self.params, self.ret, self.cname = name, params, ret, cname


BUILTINS = {"print", "len", "int", "float64", "str", "range", "input", "abs", "min", "max", "sum",
            "sorted", "reversed", "round", "read_file", "write_file", "exit", "assert", "ord", "chr"}
NUMERIC = ("int", "float64")
SCALAR = ("int", "float64", "bool", "string")
SORTABLE = ("int", "float64", "string")
STR_METHODS = {
    "upper": ([], "string"), "lower": ([], "string"), "strip": ([], "string"),
    "contains": (["string"], "bool"), "startswith": (["string"], "bool"), "endswith": (["string"], "bool"),
    "replace": (["string", "string"], "string"), "split": (["string"], ("array", "string")),
    "find": (["string"], "int"), "join": ([("array", "string")], "string"),
}
EMPTY_TABLE = {"imports": {}, "froms": {}}


def fkey(mod, name):
    return f"{mod}::{name}" if mod else name


class Checker:
    def __init__(self, prog):
        self.prog = prog
        self.tables = getattr(prog, "module_imports", {None: EMPTY_TABLE})
        self.fns, self.global_consts, self.mod_consts, self.structs = {}, {}, {}, {}
        self.scopes, self.uid = [], 0
        self.cur_ret, self.in_fn, self.loops = None, False, 0
        self.cur_mod, self.cur_file = None, None

    def err(self, msg, n):
        raise RSharpError(msg, n.line, n.col)

    def table(self):
        return self.tables.get(self.cur_mod, EMPTY_TABLE)

    def enter(self, it):
        self.cur_mod, self.cur_file = getattr(it, "module", None), getattr(it, "file", None)

    def consts_for(self, mod):
        return self.global_consts if mod is None else self.mod_consts.setdefault(mod, {})

    def run(self):
        self.prog.game, self.prog.hooks = None, {}
        try:
            for it in self.prog.items:
                if isinstance(it, A.StructDecl):
                    self.enter(it)
                    self.register_struct(it)
            for it in self.prog.items:
                if isinstance(it, A.FnDecl):
                    self.enter(it)
                    self.register(it)
            self.cur_mod, self.cur_file = None, None
            m = self.fns.get("main")
            if m and (m.params or m.ret != "void"):
                raise RSharpError("'main' must take no parameters and return nothing", 1, 1)
            self.prog.has_main = m is not None
            self.check_game_hooks()
            script = [{}]
            for it in self.prog.items:
                self.enter(it)
                if isinstance(it, A.FnDecl):
                    self.check_fn(it)
                elif self.cur_mod is not None:
                    self.scopes = [dict(self.consts_for(self.cur_mod))]
                    self.stmt(it)
                else:
                    self.scopes = script
                    self.stmt(it)
        except RSharpError as e:
            if e.file is None:
                e.file = self.cur_file
            raise
        return self.prog

    # -- types, structs, game hooks
    def check_type(self, t, node):
        if isinstance(t, tuple):
            if t[0] == "struct":
                if t[1] not in self.structs:
                    self.err(f"unknown type '{t[1]}' (structs must be declared before use; recursive structs are not supported)", node)
            else:
                self.check_type(t[1], node)

    def register_struct(self, st):
        if st.name in self.structs:
            self.err(f"struct '{st.name}' is already defined", st)
        if not st.members:
            self.err(f"struct '{st.name}' needs at least one field", st)
        seen = set()
        for (fname, ft, l, c) in st.members:
            if fname in seen:
                raise RSharpError(f"duplicate field '{fname}'", l, c)
            seen.add(fname)
            if ft == "void":
                raise RSharpError("field cannot be void", l, c)
            self.check_type(ft, st)
        self.structs[st.name] = [(f[0], f[1]) for f in st.members]

    GAME_HOOKS = {"start": [], "update": ["float64"], "fixed_update": ["float64"], "draw": [], "shutdown": []}

    def check_game_hooks(self):
        game = any(isinstance(i, A.GameDecl) for i in self.prog.items)
        if not game:
            return
        for name, params in self.GAME_HOOKS.items():
            sig = self.fns.get(name)
            if sig is None:
                continue
            if sig.params != params or sig.ret != "void":
                want = f"fn {name}({', '.join('delta: float64' for _ in params)})"
                raise RSharpError(f"game hook must be declared as '{want}' (returning nothing)", 1, 1)
            self.prog.hooks[name] = sig
        if "update" not in self.prog.hooks and "draw" not in self.prog.hooks:
            raise RSharpError("a game needs at least update(delta) or draw()", 1, 1)

    # -- scopes
    def declare(self, name, ty, mutable, node, is_global=False):
        if name in self.scopes[-1]:
            self.err(f"'{name}' is already declared in this scope", node)
        self.uid += 1
        sym = Sym(name, ty, mutable, f"rs_{'g_' if is_global else ''}{name}_{self.uid}", is_global)
        self.scopes[-1][name] = sym
        return sym

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    # -- functions
    def register(self, fn):
        mod = self.cur_mod
        key = fkey(mod, fn.name)
        if key in self.fns:
            self.err(f"function '{fn.name}' is already defined", fn)
        if mod is None and fn.name in BUILTINS:
            self.err(f"'{fn.name}' is a built-in function and cannot be redefined", fn)
        seen = set()
        for (pn, pt, l, c) in fn.params:
            if pn in seen:
                raise RSharpError(f"duplicate parameter '{pn}'", l, c)
            seen.add(pn)
            if pt == "void":
                raise RSharpError("parameter cannot be void", l, c)
            self.check_type(pt, fn)
        self.check_type(fn.ret or "void", fn)
        cname = f"rs_f_{mod}__{fn.name}" if mod else f"rs_f_{fn.name}"
        fn.sig = FnSig(fn.name, [p[1] for p in fn.params], fn.ret or "void", cname)
        self.fns[key] = fn.sig

    def check_fn(self, fn):
        saved = (self.scopes, self.cur_ret, self.in_fn, self.loops)
        self.scopes = [dict(self.consts_for(self.cur_mod)), {}]
        self.cur_ret, self.in_fn, self.loops = fn.sig.ret, True, 0
        fn.param_syms = [self.declare(n, t, False, fn) for (n, t, _, _) in fn.params]
        self.block(fn.body)
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
            if s.declty:
                self.check_type(s.declty, s)
            if s.declty and vt != s.declty:
                self.err(f"cannot initialize '{s.name}' of type {tstr(s.declty)} with {tstr(vt)}", s.value)
            ty = s.declty or vt
            is_global = (not self.in_fn) and len(self.scopes) == 1
            s.sym = self.declare(s.name, ty, s.kind == "mut", s, is_global)
            if is_global:
                self.consts_for(self.cur_mod)[s.name] = s.sym
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
            if is_arr(it):
                elem = it[1]
            elif it == "string":
                elem = "string"
            elif is_map(it):
                elem = "string"
            else:
                self.err(f"cannot iterate over {tstr(it)}", s.iter)
            self.loop_body(s, [(s.var, elem, "sym")])
        elif isinstance(s, A.ForMap):
            it = self.expr(s.iter)
            if not is_map(it):
                self.err("'for k, v in ...' needs a map", s.iter)
            self.loop_body(s, [(s.kvar, "string", "ksym"), (s.vvar, it[1], "vsym")])
        elif isinstance(s, A.ForRange):
            self.expect_type(self.expr(s.lo), "int", s.lo, "range start")
            self.expect_type(self.expr(s.hi), "int", s.hi, "range end")
            if s.step is not None:
                self.expect_type(self.expr(s.step), "int", s.step, "range step")
            self.loop_body(s, [(s.var, "int", "sym")])
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
        elif isinstance(s, A.StructDecl):
            pass  # registered in the first pass
        elif isinstance(s, A.GameDecl):
            if self.cur_mod is not None:
                self.err("'game' can only be declared in the main program", s)
            if self.prog.game is not None:
                self.err("only one 'game' declaration is allowed", s)
            self.prog.game = s.title
        else:
            self.err("unsupported statement", s)

    def loop_body(self, s, vars_):
        self.scopes.append({})
        for (name, ty, attr) in vars_:
            setattr(s, attr, self.declare(name, ty, False, s))
        self.loops += 1
        self.block(s.body, new_scope=False)
        self.loops -= 1
        self.scopes.pop()

    def root_ident(self, e):
        while isinstance(e, (A.Index, A.Member, A.Slice)):
            e = e.obj
        return e if isinstance(e, A.Ident) else None

    def require_mutable(self, target, what):
        r = self.root_ident(target)
        if r is None or getattr(r, "sym", None) is None:
            self.err(f"cannot {what} this expression", target)
        if not r.sym.mutable:
            self.err(f"cannot {what} '{r.name}': it is immutable (declare it with 'mut')", target)

    def assign(self, s):
        tt = self.expr(s.target)
        if isinstance(s.target, A.Ident):
            self.require_mutable(s.target, "assign to")
        elif isinstance(s.target, A.Member):
            if not (isinstance(s.target.obj.ty, tuple) and s.target.obj.ty[0] == "struct") or getattr(s.target, "is_module", False):
                self.err("only struct fields can be assigned", s.target)
            self.require_mutable(s.target, "modify fields of")
        else:
            if s.target.obj.ty == "string":
                self.err("strings are immutable; build a new string instead", s.target)
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

    def module_of(self, e):
        """If `e` names an imported module (and is not shadowed by a variable), return its id."""
        if isinstance(e, A.Ident) and self.lookup(e.name) is None:
            return self.table()["imports"].get(e.name)
        return None

    def resolve_const(self, modid, member, node):
        if modid in CONSTS and member in CONSTS[modid]:
            ty, text = CONSTS[modid][member]
            node.cref = ("native", text)
            return ty
        sym = self.mod_consts.get(modid, {}).get(member)
        if sym is None:
            self.err(f"module '{modid}' has no constant '{member}'", node)
        node.cref = ("sym", sym)
        return sym.ty

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
                if not isinstance(p, str) and self.expr(p) == "void":
                    self.err("cannot interpolate a void value", p)
            return "string"
        if isinstance(e, A.Ident):
            e.sym, e.cref = self.lookup(e.name), None
            if e.sym is not None:
                return e.sym.ty
            fr = self.table()["froms"].get(e.name)
            if fr and (fr[0] in CONSTS or fr[0] in self.mod_consts) and \
                    (fr[1] in CONSTS.get(fr[0], {}) or fr[1] in self.mod_consts.get(fr[0], {})):
                return self.resolve_const(fr[0], fr[1], e)
            if e.name in self.table()["imports"]:
                self.err(f"'{e.name}' is a module; use '{e.name}.member'", e)
            if fkey(self.cur_mod, e.name) in self.fns or e.name in BUILTINS or fr:
                self.err(f"functions are not first-class values yet; call '{e.name}(...)'", e)
            self.err(f"undefined variable '{e.name}'", e)
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
        if isinstance(e, A.MapLit):
            return self.map_lit(e, expected)
        if isinstance(e, A.StructLit):
            fields = self.structs.get(e.name)
            if fields is None:
                self.err(f"unknown struct '{e.name}'", e)
            want = dict(fields)
            seen = set()
            for (fname, fx, l, c) in e.members:
                if fname not in want:
                    raise RSharpError(f"struct {e.name} has no field '{fname}'", l, c)
                if fname in seen:
                    raise RSharpError(f"field '{fname}' given twice", l, c)
                seen.add(fname)
                self.expect_type(self.expr(fx, want[fname]), want[fname], fx, f"field '{fname}'")
            missing = [n for n, _ in fields if n not in seen]
            if missing:
                self.err(f"missing field(s) in {e.name} literal: {', '.join(missing)}", e)
            return ("struct", e.name)
        if isinstance(e, A.Index):
            ot = self.expr(e.obj)
            if is_arr(ot):
                self.expect_type(self.expr(e.index), "int", e.index, "index")
                return ot[1]
            if ot == "string":
                self.expect_type(self.expr(e.index), "int", e.index, "index")
                return "string"
            if is_map(ot):
                self.expect_type(self.expr(e.index), "string", e.index, "map key")
                return ot[1]
            self.err(f"cannot index into {tstr(ot)}", e)
        if isinstance(e, A.Slice):
            ot = self.expr(e.obj)
            if not (is_arr(ot) or ot == "string"):
                self.err(f"cannot slice {tstr(ot)}", e)
            for b in (e.lo, e.hi):
                if b is not None:
                    self.expect_type(self.expr(b), "int", b, "slice bound")
            return ot
        if isinstance(e, A.Member):
            mod = self.module_of(e.obj)
            if mod is not None:
                e.is_module = True
                return self.resolve_const(mod, e.name, e)
            ot = self.expr(e.obj)
            if isinstance(ot, tuple) and ot[0] == "struct":
                for (fn_, ft) in self.structs[ot[1]]:
                    if fn_ == e.name:
                        return ft
                self.err(f"struct {ot[1]} has no field '{e.name}'", e)
            if e.name == "length" and (ot == "string" or is_arr(ot) or is_map(ot)):
                return "int"
            self.err(f"{tstr(ot)} has no property '{e.name}'", e)
        if isinstance(e, A.Call):
            return self.call(e)
        self.err("unsupported expression", e)

    def array_lit(self, e, expected):
        if not e.elems:
            if is_arr(expected):
                return expected
            self.err("cannot infer the element type of an empty array; add a type annotation", e)
        want = expected[1] if is_arr(expected) else None
        first = self.expr(e.elems[0], want)
        if first == "void":
            self.err("array elements cannot be void", e.elems[0])
        for x in e.elems[1:]:
            t = self.expr(x, first)
            if t != first:
                self.err(f"array elements must all be {tstr(first)}, found {tstr(t)}", x)
        return ("array", first)

    def map_lit(self, e, expected):
        if not e.keys:
            if is_map(expected):
                return expected
            self.err("cannot infer the type of an empty map; add a type annotation, e.g. map<int>", e)
        for k in e.keys:
            self.expect_type(self.expr(k), "string", k, "map key")
        want = expected[1] if is_map(expected) else None
        first = self.expr(e.values[0], want)
        if first == "void":
            self.err("map values cannot be void", e.values[0])
        for v in e.values[1:]:
            t = self.expr(v, first)
            if t != first:
                self.err(f"map values must all be {tstr(first)}, found {tstr(t)}", v)
        return ("map", first)

    def binary(self, e):
        op = e.op
        lt, rt = self.expr(e.left), self.expr(e.right)
        bad = f"cannot apply '{op}' to {tstr(lt)} and {tstr(rt)}"
        if op in ("in", "not in"):
            ok = (lt == "string" and rt == "string") or (is_arr(rt) and lt == rt[1] and lt in SCALAR) \
                or (is_map(rt) and lt == "string")
            if not ok:
                self.err(bad, e)
            return "bool"
        if op == "*" and {lt, rt} == {"string", "int"}:
            return "string"
        if lt != rt:
            hint = " (R# never converts numbers implicitly; use int(...) or float64(...))" \
                if {lt, rt} == {"int", "float64"} else ""
            self.err(bad + hint, e)
        if op in ("&&", "||"):
            if lt != "bool":
                self.err(bad, e)
            return "bool"
        if op in ("==", "!="):
            if lt not in SCALAR:
                self.err(f"'{op}' is not supported for {tstr(lt)} yet", e)
            return "bool"
        if op in ("<", "<=", ">", ">="):
            if lt not in SORTABLE:
                self.err(bad, e)
            return "bool"
        if op == "+" and lt == "string":
            return "string"
        if op == "%" and lt == "int":
            return "int"
        if op in ("+", "-", "*", "/", "**") and lt in NUMERIC:
            return lt
        self.err(bad, e)

    # -- calls
    def args_match(self, e, params, what):
        if len(e.args) != len(params):
            self.err(f"'{what}' expects {len(params)} argument(s), got {len(e.args)}", e)
        for a, pt in zip(e.args, params):
            self.expect_type(self.expr(a, pt), pt, a, f"argument to '{what}'")

    def call(self, e):
        c = e.callee
        if isinstance(c, A.Member):
            mod = self.module_of(c.obj)
            if mod is not None:
                return self.module_call(e, mod, c.name)
            return self.method(e)
        if not isinstance(c, A.Ident):
            self.err("only named functions can be called", e)
        name = c.name
        key = fkey(self.cur_mod, name)
        if key in self.fns:
            e.kind, e.sig = "user", self.fns[key]
            self.args_match(e, e.sig.params, name)
            return e.sig.ret
        fr = self.table()["froms"].get(name)
        if fr:
            return self.module_call(e, fr[0], fr[1])
        if name in BUILTINS:
            return self.builtin(e, name)
        self.err(f"undefined function '{name}'", c)

    def module_call(self, e, modid, member):
        if modid in FUNCS:
            sig = FUNCS[modid].get(member)
            if sig is None:
                self.err(f"module '{modid}' has no function '{member}'", e)
            params, ret, _ = sig
            if len(e.args) != len(params):
                self.err(f"'{modid}.{member}' expects {len(params)} argument(s), got {len(e.args)}", e)
            for a, p in zip(e.args, params):
                t = self.expr(a)
                if p == "num" and t not in NUMERIC or p != "num" and t != p:
                    self.err(f"argument to '{modid}.{member}' must be {'a number' if p == 'num' else p}, found {tstr(t)}", a)
            e.kind, e.native = "native", sig
            return ret
        sig = self.fns.get(fkey(modid, member))
        if sig is None:
            self.err(f"module '{modid}' has no function '{member}'", e)
        e.kind, e.sig = "user", sig
        self.args_match(e, sig.params, f"{modid}.{member}")
        return sig.ret

    def method(self, e):
        c = e.callee
        ot = self.expr(c.obj)
        name = c.name
        if ot == "string":
            if name not in STR_METHODS:
                self.err(f"string has no method '{name}'", c)
            params, ret = STR_METHODS[name]
            self.args_match(e, params, name)
            e.kind, e.mname = "smethod", name
            return ret
        if is_arr(ot):
            el = ot[1]
            specs = {"push": ([el], "void"), "append": ([el], "void"), "pop": ([], el),
                     "contains": ([el], "bool"), "reverse": ([], "void"), "sort": ([], "void"),
                     "extend": ([ot], "void"), "clear": ([], "void"), "copy": ([], ot)}
            if name not in specs:
                self.err(f"array has no method '{name}'", c)
            if name == "contains" and el not in SCALAR:
                self.err("contains() needs int, float64, bool or string elements", c)
            if name == "sort" and el not in SORTABLE:
                self.err(f"cannot sort {tstr(ot)}", c)
            if name in ("push", "append", "pop", "reverse", "sort", "extend", "clear"):
                self.require_mutable(c.obj, "push to" if name in ("push", "append") else f"call '{name}' on")
            params, ret = specs[name]
            self.args_match(e, params, name)
            e.kind, e.mname = "amethod", name
            return ret
        if is_map(ot):
            v = ot[1]
            specs = {"get": (["string", v], v), "keys": ([], ("array", "string")),
                     "values": ([], ("array", v)), "remove": (["string"], "void"), "clear": ([], "void")}
            if name not in specs:
                self.err(f"map has no method '{name}'", c)
            if name in ("remove", "clear"):
                self.require_mutable(c.obj, f"call '{name}' on")
            params, ret = specs[name]
            self.args_match(e, params, name)
            e.kind, e.mname = "mmethod", name
            return ret
        self.err(f"{tstr(ot)} has no methods", c)

    def builtin(self, e, name):
        args, e.kind = e.args, name
        ts = [self.expr(a) for a in args]
        for a, t in zip(args, ts):
            if t == "void":
                self.err("cannot use a void value as an argument", a)
        n = len(args)

        def arity(lo, hi=None):
            hi = lo if hi is None else hi
            if not lo <= n <= hi:
                want = str(lo) if lo == hi else f"{lo} to {hi}"
                self.err(f"'{name}' expects {want} argument(s), got {n}", e)

        if name == "print":
            return "void"
        if name == "len":
            arity(1)
            if ts[0] == "string" or is_arr(ts[0]) or is_map(ts[0]):
                return "int"
            self.err(f"len() needs a string, array or map, found {tstr(ts[0])}", args[0])
        if name in ("int", "float64"):
            arity(1)
            if ts[0] in ("int", "float64", "string"):
                return "int" if name == "int" else "float64"
            self.err(f"cannot convert {tstr(ts[0])} to {name}", args[0])
        if name == "str":
            arity(1)
            return "string"
        if name == "range":
            arity(1, 3)
            for a, t in zip(args, ts):
                self.expect_type(t, "int", a, "range() argument")
            return ("array", "int")
        if name == "input":
            arity(0, 1)
            if n:
                self.expect_type(ts[0], "string", args[0], "prompt")
            return "string"
        if name == "abs":
            arity(1)
            if ts[0] in NUMERIC:
                return ts[0]
            self.err(f"abs() needs a number, found {tstr(ts[0])}", args[0])
        if name in ("min", "max"):
            if n == 1 and is_arr(ts[0]) and ts[0][1] in SORTABLE:
                return ts[0][1]
            if n == 2 and ts[0] == ts[1] and ts[0] in SORTABLE:
                return ts[0]
            self.err(f"{name}() needs two values of the same type, or one array", e)
        if name == "sum":
            arity(1)
            if is_arr(ts[0]) and ts[0][1] in NUMERIC:
                return ts[0][1]
            self.err("sum() needs an int[] or float64[]", e)
        if name in ("sorted", "reversed"):
            arity(1)
            if not is_arr(ts[0]) or (name == "sorted" and ts[0][1] not in SORTABLE):
                self.err(f"{name}() needs an array{' of numbers or strings' if name == 'sorted' else ''}", args[0])
            return ts[0]
        if name == "round":
            arity(1)
            if ts[0] in NUMERIC:
                return "int"
            self.err("round() needs a number", args[0])
        if name == "read_file":
            arity(1)
            self.expect_type(ts[0], "string", args[0], "path")
            return "string"
        if name == "write_file":
            arity(2)
            for i in (0, 1):
                self.expect_type(ts[i], "string", args[i], "argument")
            return "void"
        if name == "exit":
            arity(1)
            self.expect_type(ts[0], "int", args[0], "exit code")
            return "void"
        if name == "assert":
            arity(1, 2)
            self.expect_type(ts[0], "bool", args[0], "assert condition")
            if n == 2:
                self.expect_type(ts[1], "string", args[1], "assert message")
            return "void"
        if name == "ord":
            arity(1)
            self.expect_type(ts[0], "string", args[0], "ord() argument")
            return "int"
        if name == "chr":
            arity(1)
            self.expect_type(ts[0], "int", args[0], "chr() argument")
            return "string"
        self.err(f"unsupported builtin {name}", e)


def check(prog):
    return Checker(prog).run()
