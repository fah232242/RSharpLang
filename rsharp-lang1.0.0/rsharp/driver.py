import os, subprocess, sys, tempfile
from .compiler.loader import Loader
from .compiler.checker import check
from .compiler.codegen import generate
from .compiler.errors import RSharpError, format_error


def compile_to_c(source, path=None):
    prog = Loader().load_main(path, source)
    return generate(check(prog))


def report(e, path, src):
    fp = e.file or path or "<input>"
    if fp != path:
        try:
            with open(fp, encoding="utf-8") as f:
                src = f.read()
        except OSError:
            pass
    print(format_error(e, os.path.relpath(fp) if os.path.isfile(fp) else fp, src), file=sys.stderr)


def build(path, out=None, emit_c=False):
    """Compile `path`. Returns executable path (or C source when emit_c). Raises RSharpError."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        c_src = compile_to_c(src, path)
    except RSharpError as e:
        report(e, path, src)
        raise
    if emit_c:
        return c_src
    out = out or os.path.splitext(os.path.basename(path))[0] + (".exe" if os.name == "nt" else "")
    with tempfile.TemporaryDirectory() as td:
        cpath = os.path.join(td, "out.c")
        with open(cpath, "w") as f:
            f.write(c_src)
        cc = os.environ.get("CC", "gcc")
        try:
            r = subprocess.run([cc, "-O2", "-std=gnu11", "-w", "-o", out, cpath, "-lm"],
                               capture_output=True, text=True)
        except FileNotFoundError:
            print(f"error: C compiler '{cc}' not found. Install gcc (or set $CC). See README.", file=sys.stderr)
            raise RuntimeError("no C compiler")
        if r.returncode != 0:
            print("internal compiler error: generated C failed to compile\n" + r.stderr, file=sys.stderr)
            raise RuntimeError("backend failure")
    return out
