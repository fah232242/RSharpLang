class Node:
    fields = ()

    def __init__(self, *args, line=0, col=0):
        assert len(args) == len(self.fields), (type(self).__name__, args)
        for f, v in zip(self.fields, args):
            setattr(self, f, v)
        self.line, self.col, self.ty = line, col, None

    def __repr__(self):
        return f"{type(self).__name__}({', '.join(repr(getattr(self, f)) for f in self.fields)})"


def node(name, *fields):
    return type(name, (Node,), {"fields": fields})


Program = node("Program", "items")
FnDecl = node("FnDecl", "name", "params", "ret", "body")  # params: [(name, type, line, col)]
Block = node("Block", "stmts")
VarDecl = node("VarDecl", "kind", "name", "declty", "value")
Assign = node("Assign", "target", "op", "value")
If = node("If", "cond", "then", "els")
While = node("While", "cond", "body")
ForEach = node("ForEach", "var", "iter", "body")
ForRange = node("ForRange", "var", "lo", "hi", "body")
Return = node("Return", "value")
Break = node("Break")
Continue = node("Continue")
ExprStmt = node("ExprStmt", "expr")

IntLit = node("IntLit", "value")
FloatLit = node("FloatLit", "value")
StrLit = node("StrLit", "value")
BoolLit = node("BoolLit", "value")
Interp = node("Interp", "parts")  # parts: str | Expr
Ident = node("Ident", "name")
Unary = node("Unary", "op", "operand")
Binary = node("Binary", "op", "left", "right")
Call = node("Call", "callee", "args")
Index = node("Index", "obj", "index")
Member = node("Member", "obj", "name")
ArrayLit = node("ArrayLit", "elems")
