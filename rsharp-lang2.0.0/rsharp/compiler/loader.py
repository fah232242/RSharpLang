"""Import resolution: finds module files, parses them, and merges everything into one Program
(module items first, in dependency order, tagged with .module and .file)."""
import os, re
from . import ast as A
from .errors import RSharpError
from .parser import parse

NATIVE = {"math", "random", "time", "game"}
BUNDLED = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "packages"))


def pkg_candidates(pkg, base):
    out = []
    d = os.path.abspath(base)
    while True:
        out.append(os.path.join(d, "rsharp_packages", pkg, "lib.rsharp"))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    out.append(os.path.join(BUNDLED, pkg, "lib.rsharp"))
    return out


class Loader:
    def __init__(self):
        self.mods, self.ids, self.order, self.tables, self.loading = {}, set(), [], {}, []

    def parse_file(self, path, src):
        try:
            return parse(src)
        except RSharpError as e:
            e.file = e.file or path
            raise

    def load_main(self, path, src):
        prog = self.parse_file(path, src)
        base = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
        self.tables[None] = self.resolve_imports(prog.items, base, path)
        prog.items = self.order + [i for i in prog.items if not isinstance(i, A.Import)]
        prog.module_imports = self.tables
        return prog

    def resolve_imports(self, items, base, file):
        table = {"imports": {}, "froms": {}}
        for it in items:
            if not isinstance(it, A.Import):
                continue
            try:
                modid = self.resolve(it, base)
                if it.names is None:
                    if it.alias in table["imports"]:
                        raise RSharpError(f"'{it.alias}' is already imported", it.line, it.col)
                    table["imports"][it.alias] = modid
                else:
                    for (n, a) in it.names:
                        if a in table["froms"]:
                            raise RSharpError(f"'{a}' is already imported", it.line, it.col)
                        table["froms"][a] = (modid, n)
            except RSharpError as e:
                e.file = e.file or file
                raise
        return table

    def resolve(self, it, base):
        name, spec = it.name, it.spec
        if spec is None and name in NATIVE:
            return name
        if spec and spec.startswith("."):
            cands = [os.path.join(base, spec), os.path.join(base, spec + ".rsharp")]
        elif spec:
            cands = pkg_candidates(spec.split("/")[-1], base)
        else:
            cands = [os.path.join(base, name + ".rsharp"), os.path.join(base, name, "lib.rsharp")] \
                + pkg_candidates(name, base)
        for c in cands:
            if os.path.isfile(c):
                return self.load_module(c, it)
        raise RSharpError(f"cannot find module '{spec or name}'", it.line, it.col)

    def load_module(self, path, it):
        ap = os.path.abspath(path)
        if ap in self.mods:
            return self.mods[ap]
        if ap in self.loading:
            raise RSharpError(f"circular import of '{it.name}'", it.line, it.col)
        self.loading.append(ap)
        with open(ap, encoding="utf-8") as f:
            prog = self.parse_file(ap, f.read())
        stem = os.path.splitext(os.path.basename(ap))[0]
        if stem == "lib":
            stem = os.path.basename(os.path.dirname(ap))
        modid = re.sub(r"\W", "_", stem)
        while modid in self.ids or modid in NATIVE:
            modid += "_"
        self.ids.add(modid)
        self.tables[modid] = self.resolve_imports(prog.items, os.path.dirname(ap), ap)
        for m in prog.items:
            if isinstance(m, A.Import):
                continue
            if isinstance(m, (A.FnDecl, A.StructDecl)) or (isinstance(m, A.VarDecl) and m.kind == "const"):
                m.module, m.file = modid, ap
                self.order.append(m)
            else:
                e = RSharpError("modules may only contain functions, structs, constants and imports", m.line, m.col)
                e.file = ap
                raise e
        self.loading.pop()
        self.mods[ap] = modid
        return modid
