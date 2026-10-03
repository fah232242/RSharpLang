from .errors import RSharpError

KEYWORDS = {"fn", "let", "mut", "const", "if", "else", "while", "for", "in",
            "return", "break", "continue", "true", "false", "import", "from", "as", "pub", "not", "struct"}
# Part of the R# design but not implemented in v0.1: reserved so they error clearly.
RESERVED = {"class", "interface", "enum", "match",
            "async", "await", "try", "catch", "finally", "throw", "unsafe", "using",
            "defer", "null", "this", "new", "static", "abstract", "sealed", "public",
            "private", "protected", "implements", "extends", "spawn", "namespace"}
OPS2 = ["==", "!=", "<=", ">=", "&&", "||", "+=", "-=", "*=", "/=", "%=", "->", "=>", "..", "**"]
OPS1 = "+-*/%=<>!(){}[],;:."
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"', "0": "\0"}


class Token:
    __slots__ = ("kind", "value", "line", "col")

    def __init__(self, kind, value, line, col):
        self.kind, self.value, self.line, self.col = kind, value, line, col

    def __repr__(self):
        return f"Token({self.kind},{self.value!r},{self.line}:{self.col})"


class Lexer:
    def __init__(self, src, line=1, col=1):
        self.s, self.i, self.line, self.col = src, 0, line, col

    def err(self, msg, line=None, col=None):
        raise RSharpError(msg, line or self.line, col or self.col)

    def adv(self, k=1):
        for _ in range(k):
            if self.s[self.i] == "\n":
                self.line += 1
                self.col = 1
            else:
                self.col += 1
            self.i += 1

    def tokens(self):
        s, toks = self.s, []
        while self.i < len(s):
            ch = s[self.i]
            if ch in " \t\r\n":
                self.adv()
            elif ch == "#" or s.startswith("//", self.i):
                while self.i < len(s) and s[self.i] != "\n":
                    self.adv()
            elif s.startswith("/*", self.i):
                l, c = self.line, self.col
                end = s.find("*/", self.i + 2)
                if end < 0:
                    self.err("unterminated block comment", l, c)
                self.adv(end + 2 - self.i)
            elif ch.isdigit():
                toks.append(self.number())
            elif ch.isalpha() or ch == "_":
                l, c, j = self.line, self.col, self.i
                while self.i < len(s) and (s[self.i].isalnum() or s[self.i] == "_"):
                    self.adv()
                w = s[j:self.i]
                if w in ("and", "or"):
                    toks.append(Token("OP", "&&" if w == "and" else "||", l, c))
                elif w in KEYWORDS:
                    toks.append(Token("KW", w, l, c))
                elif w in RESERVED:
                    self.err(f"'{w}' is reserved in R# but not implemented in v0.1", l, c)
                else:
                    toks.append(Token("IDENT", w, l, c))
            elif ch == '"':
                toks.append(self.string(False))
            elif ch == "$" and s.startswith('$"', self.i):
                toks.append(self.string(True))
            else:
                l, c = self.line, self.col
                two = s[self.i:self.i + 2]
                if two in OPS2:
                    self.adv(2)
                    toks.append(Token("OP", two, l, c))
                elif ch in OPS1:
                    self.adv()
                    toks.append(Token("OP", ch, l, c))
                elif ch == "?":
                    self.err("optional types / '?' are not implemented in v0.1")
                else:
                    self.err(f"unexpected character {ch!r}")
        toks.append(Token("EOF", None, self.line, self.col))
        return toks

    def number(self):
        s, l, c, j = self.s, self.line, self.col, self.i
        if s.startswith(("0x", "0X"), j):
            self.adv(2)
            while self.i < len(s) and (s[self.i] in "0123456789abcdefABCDEF_"):
                self.adv()
            txt = s[j + 2:self.i].replace("_", "")
            if not txt:
                self.err("invalid hex literal", l, c)
            return self.mkint(int(txt, 16), l, c)
        while self.i < len(s) and (s[self.i].isdigit() or s[self.i] == "_"):
            self.adv()
        is_float = False
        if self.i + 1 < len(s) and s[self.i] == "." and s[self.i + 1].isdigit():
            is_float = True
            self.adv()
            while self.i < len(s) and (s[self.i].isdigit() or s[self.i] == "_"):
                self.adv()
        if self.i < len(s) and s[self.i] in "eE":
            k = self.i + 1
            if k < len(s) and s[k] in "+-":
                k += 1
            if k < len(s) and s[k].isdigit():
                is_float = True
                self.adv(k - self.i)
                while self.i < len(s) and s[self.i].isdigit():
                    self.adv()
        txt = s[j:self.i].replace("_", "")
        if is_float:
            return Token("FLOAT", float(txt), l, c)
        return self.mkint(int(txt), l, c)

    def mkint(self, v, l, c):
        if v > 2**63 - 1:
            self.err("integer literal too large for int (64-bit)", l, c)
        return Token("INT", v, l, c)

    def string(self, interp):
        l, c = self.line, self.col
        s = self.s
        self.adv(2 if interp else 1)
        parts, buf = [], []

        def flush():
            if buf:
                parts.append("".join(buf))
                buf.clear()

        while True:
            if self.i >= len(s) or s[self.i] == "\n":
                self.err("unterminated string literal", l, c)
            ch = s[self.i]
            if ch == '"':
                self.adv()
                break
            if ch == "\\":
                if self.i + 1 >= len(s) or s[self.i + 1] not in ESCAPES:
                    self.err("invalid escape sequence")
                buf.append(ESCAPES[s[self.i + 1]])
                self.adv(2)
            elif interp and ch == "{":
                if s.startswith("{{", self.i):
                    buf.append("{")
                    self.adv(2)
                    continue
                el, ec = self.line, self.col + 1
                self.adv()
                depth, start, in_str = 1, self.i, False
                while depth:
                    if self.i >= len(s) or s[self.i] == "\n":
                        self.err("unterminated '{' in interpolated string", el, ec - 1)
                    d = s[self.i]
                    if in_str:
                        if d == "\\":
                            self.adv()
                        elif d == '"':
                            in_str = False
                    elif d == '"':
                        in_str = True
                    elif d == "{":
                        depth += 1
                    elif d == "}":
                        depth -= 1
                    self.adv()
                src = s[start:self.i - 1]
                if not src.strip():
                    self.err("empty expression in interpolated string", el, ec - 1)
                flush()
                parts.append((src, el, ec))
            elif interp and ch == "}":
                if s.startswith("}}", self.i):
                    buf.append("}")
                    self.adv(2)
                else:
                    self.err("single '}' in interpolated string (use '}}')")
            else:
                buf.append(ch)
                self.adv()
        flush()
        if interp:
            return Token("ISTRING", parts, l, c)
        return Token("STRING", "".join(parts), l, c)


def tokenize(src, line=1, col=1):
    return Lexer(src, line, col).tokens()
