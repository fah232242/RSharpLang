import os
from . import ast as A
from .errors import RSharpError
from .lexer import tokenize

SCALARS = {"int": "int", "int64": "int", "float64": "float64", "bool": "bool",
           "string": "string", "void": "void"}
FUTURE_TYPES = {"uint", "int8", "int16", "int32", "uint8", "uint16", "uint32", "uint64",
                "float32", "char", "byte", "any", "never"}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%="}


def spec_name(spec):
    base = spec.rstrip("/").split("/")[-1]
    return os.path.splitext(base)[0]


class Parser:
    def __init__(self, toks):
        self.t, self.p = toks, 0

    @property
    def cur(self):
        return self.t[self.p]

    def err(self, msg, tok=None):
        tok = tok or self.cur
        raise RSharpError(msg, tok.line, tok.col)

    def is_op(self, v):
        return self.cur.kind == "OP" and self.cur.value == v

    def is_kw(self, v):
        return self.cur.kind == "KW" and self.cur.value == v

    def eat_op(self, v):
        if self.is_op(v):
            self.p += 1
            return True
        return False

    def expect_op(self, v, ctx=""):
        if not self.is_op(v):
            self.err(f"expected '{v}'{ctx}, found {self.describe()}")
        tok = self.cur
        self.p += 1
        return tok

    def expect_kw(self, v):
        if not self.is_kw(v):
            self.err(f"expected '{v}', found {self.describe()}")
        self.p += 1

    def expect_ident(self, what="identifier"):
        if self.cur.kind != "IDENT":
            self.err(f"expected {what}, found {self.describe()}")
        tok = self.cur
        self.p += 1
        return tok

    def describe(self):
        c = self.cur
        return "end of file" if c.kind == "EOF" else f"'{c.value}'" if c.kind in ("OP", "KW", "IDENT") else c.kind.lower()

    def at(self, node, tok):
        node.line, node.col = tok.line, tok.col
        return node

    # -- program
    def parse_program(self):
        items = []
        while self.cur.kind != "EOF":
            if self.is_kw("pub"):  # accepted; every module member is public in v0.2
                self.p += 1
            if self.is_kw("struct"):
                items.append(self.struct_decl())
            elif self.cur.kind == "IDENT" and self.cur.value == "game" and self.t[self.p + 1].kind == "STRING":
                c = self.cur
                self.p += 1
                title = self.cur.value
                self.p += 1
                self.eat_op(";")
                items.append(self.at(A.GameDecl(title), c))
            else:
                items.append(self.fn_decl() if self.is_kw("fn") else self.statement())
        return A.Program(items)

    def struct_decl(self):
        c = self.cur
        self.p += 1
        name = self.expect_ident("struct name").value
        if not name[0].isupper():
            self.err("struct names must start with an uppercase letter", c)
        self.expect_op("{")
        fields = []
        while not self.is_op("}"):
            f = self.expect_ident("field name")
            self.expect_op(":", " after field name")
            fields.append((f.value, self.parse_type(), f.line, f.col))
            if not (self.eat_op(",") or self.eat_op(";")):
                break
        self.expect_op("}", " at end of struct")
        return self.at(A.StructDecl(name, fields), c)

    def parse_type(self):
        tok = self.expect_ident("type name")
        name = tok.value
        if name == "map":
            self.expect_op("<", " after 'map'")
            inner = self.parse_type()
            if inner == "void":
                self.err("map<void> is not allowed", tok)
            self.expect_op(">", " to close map type")
            ty = ("map", inner)
        else:
            if name in FUTURE_TYPES:
                self.err(f"type '{name}' is not implemented yet", tok)
            if name in SCALARS:
                ty = SCALARS[name]
            elif name[0].isupper():
                ty = ("struct", name)  # validated by the checker
            else:
                self.err(f"unknown type '{name}'", tok)
        while self.is_op("["):
            self.p += 1
            self.expect_op("]", " in array type")
            if ty == "void":
                self.err("array of void is not allowed", tok)
            ty = ("array", ty)
        return ty

    def fn_decl(self):
        start = self.cur
        self.p += 1
        name = self.expect_ident("function name").value
        self.expect_op("(")
        params = []
        while not self.is_op(")"):
            pt = self.expect_ident("parameter name")
            if not self.is_op(":"):
                self.err(f"parameter '{pt.value}' needs a type annotation (no parameter inference yet)")
            self.p += 1
            params.append((pt.value, self.parse_type(), pt.line, pt.col))
            if not self.eat_op(","):
                break
        self.expect_op(")")
        ret = None
        if self.eat_op("->"):
            ret = self.parse_type()
        if self.eat_op("=>"):
            e = self.expression()
            self.expect_op(";")
            st = self.at(A.Return(e), start) if (ret is not None and ret != "void") else self.at(A.ExprStmt(e), start)
            body = self.at(A.Block([st]), start)
        else:
            body = self.block()
        return self.at(A.FnDecl(name, params, ret, body), start)

    # -- statements
    def block(self):
        start = self.expect_op("{")
        stmts = []
        while not self.is_op("}"):
            if self.cur.kind == "EOF":
                self.err("unclosed '{' (reached end of file)", start)
            if self.is_kw("fn"):
                self.err("nested functions are not supported yet")
            if self.is_kw("import") or self.is_kw("from"):
                self.err("imports must be at the top level")
            stmts.append(self.statement())
        self.p += 1
        return self.at(A.Block(stmts), start)

    def import_stmt(self):
        c = self.cur
        self.p += 1
        if c.value == "import":
            name_tok = self.expect_ident("module name")
            name, alias, spec = name_tok.value, None, None
            if self.is_kw("as"):
                self.p += 1
                alias = self.expect_ident("alias").value
            if self.is_kw("from"):
                self.p += 1
                if self.cur.kind != "STRING":
                    self.err("expected a quoted package path after 'from'")
                spec = self.cur.value
                self.p += 1
            self.expect_op(";")
            return self.at(A.Import(name, alias or name, None, spec), c)
        spec = None
        if self.cur.kind == "STRING":
            spec = self.cur.value
            name = spec_name(spec)
            self.p += 1
        else:
            name = self.expect_ident("module name").value
        self.expect_kw("import")
        names = []
        while True:
            n = self.expect_ident("name to import").value
            a = n
            if self.is_kw("as"):
                self.p += 1
                a = self.expect_ident("alias").value
            names.append((n, a))
            if not self.eat_op(","):
                break
        self.expect_op(";")
        return self.at(A.Import(name, None, names, spec), c)

    def statement(self):
        c = self.cur
        if c.kind == "KW":
            k = c.value
            if k in ("import", "from"):
                return self.import_stmt()
            if k in ("let", "mut", "const"):
                return self.var_decl()
            if k == "if":
                return self.if_stmt()
            if k == "while":
                self.p += 1
                cond = self.expression()
                return self.at(A.While(cond, self.block()), c)
            if k == "for":
                return self.for_stmt()
            if k == "return":
                self.p += 1
                v = None if self.is_op(";") else self.expression()
                self.expect_op(";")
                return self.at(A.Return(v), c)
            if k in ("break", "continue"):
                self.p += 1
                self.expect_op(";")
                return self.at(A.Break() if k == "break" else A.Continue(), c)
        if self.is_op("{"):
            return self.block()
        e = self.expression()
        if self.cur.kind == "OP" and self.cur.value in ASSIGN_OPS:
            op = self.cur.value
            if not isinstance(e, (A.Ident, A.Index, A.Member)):
                self.err("invalid assignment target")
            self.p += 1
            v = self.expression()
            self.expect_op(";")
            return self.at(A.Assign(e, op, v), c)
        self.expect_op(";", " at end of statement")
        return self.at(A.ExprStmt(e), c)

    def var_decl(self):
        c = self.cur
        self.p += 1
        name = self.expect_ident("variable name").value
        ty = None
        if self.eat_op(":"):
            ty = self.parse_type()
        if not self.is_op("="):
            self.err(f"expected '=' (variables must be initialized), found {self.describe()}")
        self.p += 1
        v = self.expression()
        self.expect_op(";")
        return self.at(A.VarDecl(c.value, name, ty, v), c)

    def if_stmt(self):
        c = self.cur
        self.p += 1
        cond = self.expression()
        then = self.block()
        els = None
        if self.is_kw("else"):
            self.p += 1
            els = self.if_stmt() if self.is_kw("if") else self.block()
        return self.at(A.If(cond, then, els), c)

    def for_stmt(self):
        c = self.cur
        self.p += 1
        v1 = self.expect_ident("loop variable").value
        v2 = None
        if self.eat_op(","):
            v2 = self.expect_ident("second loop variable").value
        self.expect_kw("in")
        first = self.expression()
        if v2 is not None:
            return self.at(A.ForMap(v1, v2, first, self.block()), c)
        if self.eat_op(".."):
            hi = self.expression()
            return self.at(A.ForRange(v1, first, hi, None, self.block()), c)
        if isinstance(first, A.Call) and isinstance(first.callee, A.Ident) and first.callee.name == "range":
            a = first.args
            if not 1 <= len(a) <= 3:
                self.err("range() takes 1 to 3 arguments", c)
            lo, hi, step = (self.at(A.IntLit(0), c), a[0], None) if len(a) == 1 else \
                (a[0], a[1], a[2] if len(a) == 3 else None)
            return self.at(A.ForRange(v1, lo, hi, step, self.block()), c)
        return self.at(A.ForEach(v1, first, self.block()), c)

    # -- expressions
    LEVELS = [["||"], ["&&"], "NOT", ["==", "!="], "CMP", ["+", "-"], ["*", "/", "%"]]

    def match_binop(self, L):
        c = self.cur
        if L == "CMP":
            if c.kind == "OP" and c.value in ("<", "<=", ">", ">="):
                self.p += 1
                return c.value, c
            if c.kind == "KW" and c.value == "in":
                self.p += 1
                return "in", c
            nxt = self.t[min(self.p + 1, len(self.t) - 1)]
            if c.kind == "KW" and c.value == "not" and nxt.kind == "KW" and nxt.value == "in":
                self.p += 2
                return "not in", c
            return None
        if c.kind == "OP" and c.value in L:
            self.p += 1
            return c.value, c
        return None

    def expression(self, level=0):
        if level == len(self.LEVELS):
            return self.unary()
        L = self.LEVELS[level]
        if L == "NOT":
            if self.is_kw("not"):
                tok = self.cur
                self.p += 1
                return self.at(A.Unary("!", self.expression(level)), tok)
            return self.expression(level + 1)
        left = self.expression(level + 1)
        while True:
            m = self.match_binop(L)
            if m is None:
                return left
            op, tok = m
            right = self.expression(level + 1)
            left = self.at(A.Binary(op, left, right), tok)

    def unary(self):
        c = self.cur
        if c.kind == "OP" and c.value in ("-", "!"):
            self.p += 1
            return self.at(A.Unary(c.value, self.unary()), c)
        base = self.postfix()
        if self.is_op("**"):
            tok = self.cur
            self.p += 1
            return self.at(A.Binary("**", base, self.unary()), tok)
        return base

    def postfix(self):
        e = self.primary()
        while True:
            c = self.cur
            if self.is_op("("):
                self.p += 1
                args = []
                while not self.is_op(")"):
                    args.append(self.expression())
                    if not self.eat_op(","):
                        break
                self.expect_op(")", " after arguments")
                e = self.at(A.Call(e, args), c)
            elif self.is_op("["):
                self.p += 1
                if self.eat_op(":"):
                    hi = None if self.is_op("]") else self.expression()
                    self.expect_op("]")
                    e = self.at(A.Slice(e, None, hi), c)
                else:
                    i = self.expression()
                    if self.eat_op(":"):
                        hi = None if self.is_op("]") else self.expression()
                        self.expect_op("]")
                        e = self.at(A.Slice(e, i, hi), c)
                    else:
                        self.expect_op("]")
                        e = self.at(A.Index(e, i), c)
            elif self.is_op("."):
                self.p += 1
                e = self.at(A.Member(e, self.expect_ident("member name").value), c)
            else:
                return e

    def primary(self):
        c = self.cur
        k = c.kind
        if k == "INT":
            self.p += 1
            return self.at(A.IntLit(c.value), c)
        if k == "FLOAT":
            self.p += 1
            return self.at(A.FloatLit(c.value), c)
        if k == "STRING":
            self.p += 1
            return self.at(A.StrLit(c.value), c)
        if k == "ISTRING":
            self.p += 1
            parts = []
            for part in c.value:
                if isinstance(part, str):
                    parts.append(part)
                else:
                    src, l, col = part
                    sub = Parser(tokenize(src, l, col))
                    e = sub.expression()
                    if sub.cur.kind != "EOF":
                        sub.err("unexpected token in interpolated expression")
                    parts.append(e)
            return self.at(A.Interp(parts), c)
        if k == "KW" and c.value in ("true", "false"):
            self.p += 1
            return self.at(A.BoolLit(c.value == "true"), c)
        if k == "IDENT":
            self.p += 1
            n1, n2 = self.t[self.p], self.t[min(self.p + 1, len(self.t) - 1)]
            if c.value[0].isupper() and n1.kind == "OP" and n1.value == "{" and n2.kind == "IDENT" \
                    and self.t[min(self.p + 2, len(self.t) - 1)].value == ":":
                self.p += 1
                fields = []
                while not self.is_op("}"):
                    f = self.expect_ident("field name")
                    self.expect_op(":", " after field name")
                    fields.append((f.value, self.expression(), f.line, f.col))
                    if not self.eat_op(","):
                        break
                self.expect_op("}", " at end of struct literal")
                return self.at(A.StructLit(c.value, fields), c)
            return self.at(A.Ident(c.value), c)
        if self.is_op("("):
            self.p += 1
            e = self.expression()
            self.expect_op(")")
            return e
        if self.is_op("["):
            self.p += 1
            elems = []
            while not self.is_op("]"):
                elems.append(self.expression())
                if not self.eat_op(","):
                    break
            self.expect_op("]", " at end of array literal")
            return self.at(A.ArrayLit(elems), c)
        if self.is_op("{"):
            self.p += 1
            keys, vals = [], []
            while not self.is_op("}"):
                keys.append(self.expression())
                self.expect_op(":", " between map key and value")
                vals.append(self.expression())
                if not self.eat_op(","):
                    break
            self.expect_op("}", " at end of map literal")
            return self.at(A.MapLit(keys, vals), c)
        self.err(f"expected an expression, found {self.describe()}")


def parse(src):
    return Parser(tokenize(src)).parse_program()
