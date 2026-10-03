from . import ast as A
from .errors import RSharpError
from .lexer import tokenize

SCALARS = {"int": "int", "int64": "int", "float64": "float64", "bool": "bool",
           "string": "string", "void": "void"}
FUTURE_TYPES = {"uint", "int8", "int16", "int32", "uint8", "uint16", "uint32", "uint64",
                "float32", "char", "byte", "any", "never"}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%="}


class Parser:
    def __init__(self, toks):
        self.t, self.p = toks, 0

    # -- helpers
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
            items.append(self.fn_decl() if self.is_kw("fn") else self.statement())
        return A.Program(items)

    def parse_type(self):
        tok = self.expect_ident("type name")
        name = tok.value
        if name in FUTURE_TYPES:
            self.err(f"type '{name}' is not implemented in v0.1", tok)
        if name not in SCALARS:
            self.err(f"unknown type '{name}'", tok)
        ty = SCALARS[name]
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
                self.err(f"parameter '{pt.value}' needs a type annotation (v0.1 has no parameter inference)")
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
            if ret is not None and ret != "void":
                st = self.at(A.Return(e), start)
            else:
                st = self.at(A.ExprStmt(e), start)
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
                self.err("nested functions are not supported in v0.1")
            stmts.append(self.statement())
        self.p += 1
        return self.at(A.Block(stmts), start)

    def statement(self):
        c = self.cur
        if c.kind == "KW":
            k = c.value
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
            if not isinstance(e, (A.Ident, A.Index)):
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
        var = self.expect_ident("loop variable").value
        if not self.is_kw("in"):
            self.err(f"expected 'in', found {self.describe()}")
        self.p += 1
        first = self.expression()
        if self.eat_op(".."):
            hi = self.expression()
            return self.at(A.ForRange(var, first, hi, self.block()), c)
        return self.at(A.ForEach(var, first, self.block()), c)

    # -- expressions (precedence climbing)
    LEVELS = [["||"], ["&&"], ["==", "!="], ["<", "<=", ">", ">="], ["+", "-"], ["*", "/", "%"]]

    def expression(self, level=0):
        if level == len(self.LEVELS):
            return self.unary()
        left = self.expression(level + 1)
        while self.cur.kind == "OP" and self.cur.value in self.LEVELS[level]:
            tok = self.cur
            self.p += 1
            right = self.expression(level + 1)
            left = self.at(A.Binary(tok.value, left, right), tok)
        return left

    def unary(self):
        c = self.cur
        if c.kind == "OP" and c.value in ("-", "!"):
            self.p += 1
            return self.at(A.Unary(c.value, self.unary()), c)
        return self.postfix()

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
                i = self.expression()
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
        self.err(f"expected an expression, found {self.describe()}")


def parse(src):
    return Parser(tokenize(src)).parse_program()
