import glob, os, subprocess, sys, tempfile
from . import VERSION
from .driver import build, compile_to_c, report
from .compiler.errors import RSharpError

USAGE = f"""R# {VERSION}
usage:
  rsharp <file.rsharp>                  compile and run a program
  rsharp run [file.rsharp]              same (no file: run the project's src/main.rsharp)
  rsharp build [file.rsharp] [-o out]   compile to a native executable
  rsharp check [file.rsharp]            type-check only
  rsharp emit-c <file.rsharp>           print the generated C
  rsharp repl                           interactive prompt
  rsharp test [dir]                     run *.rsharp tests ('// expect:' / '// expect-error:')
  rsharp pkg ...                        package manager (try: rsharp pkg)
  rsharp --version
Not implemented yet: fmt lint doc"""
NOT_YET = {"fmt", "lint", "doc"}


def project_main():
    from .pkg import find_project
    root = find_project()
    p = os.path.join(root, "src", "main.rsharp") if root else None
    return p if p and os.path.isfile(p) else None


def run_file(path):
    with tempfile.TemporaryDirectory() as td:
        exe = os.path.join(td, "prog.exe" if os.name == "nt" else "prog")
        build(path, exe)
        return subprocess.run([exe]).returncode


def run_tests(d):
    files = [f for f in sorted(glob.glob(os.path.join(d, "**", "*.rsharp"), recursive=True))
             if not os.path.basename(f).startswith("_")]
    failed = 0
    for f in files:
        src = open(f, encoding="utf-8").read()
        want = [l.split("// expect:", 1)[1][1:] for l in src.splitlines() if "// expect:" in l]
        errs = [l.split("// expect-error:", 1)[1].strip() for l in src.splitlines() if "// expect-error:" in l]
        with tempfile.TemporaryDirectory() as td:
            exe = os.path.join(td, "prog")
            if errs:
                try:
                    compile_to_c(src, f)
                    ok, msg = False, "expected a compile error"
                except RSharpError as e:
                    ok, msg = errs[0] in e.msg, f"error was: {e.msg}"
                except Exception as e:
                    ok, msg = False, f"internal compiler error: {type(e).__name__}: {e}"
            else:
                try:
                    build(f, exe)
                except (RSharpError, RuntimeError):
                    ok, msg = False, "compile failed"
                except Exception as e:
                    ok, msg = False, f"internal compiler error: {type(e).__name__}: {e}"
                else:
                    r = subprocess.run([exe], capture_output=True, text=True)
                    got = r.stdout.split("\n")
                    if got and got[-1] == "":
                        got.pop()
                    ok, msg = got == want, f"expected {want!r}, got {got!r}" + (f" stderr={r.stderr!r}" if r.stderr else "")
        print(("PASS " if ok else "FAIL ") + f + ("" if ok else "\n     " + msg))
        failed += not ok
    print(f"\n{len(files) - failed}/{len(files)} passed")
    return 1 if failed else 0


def depth(text):
    d, in_str, i = 0, False, 0
    while i < len(text):
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c in "([{":
            d += 1
        elif c in ")]}":
            d -= 1
        elif c == "#" or text.startswith("//", i):
            while i < len(text) and text[i] != "\n":
                i += 1
        i += 1
    return d


def repl():
    """Replay-based REPL: every entry is compiled together with the accepted history, and only
    the *new* output is shown. So entries must be deterministic (no input()/random/time)."""
    print(f"R# {VERSION} REPL. Expressions are echoed. Ctrl-D to exit. (Replays history each time; "
          "avoid input()/random/time.)")
    history, shown, buf = [], "", []
    base = os.getcwd()

    def attempt(candidate):
        src = "\n".join(history + [candidate]) + "\n"
        try:
            c = compile_to_c(src, os.path.join(base, "<repl>"))
        except RSharpError as e:
            return None, e
        with tempfile.TemporaryDirectory() as td:
            cp, exe = os.path.join(td, "o.c"), os.path.join(td, "o")
            open(cp, "w").write(c)
            r = subprocess.run([os.environ.get("CC", "gcc"), "-O1", "-std=gnu11", "-w", "-o", exe, cp, "-lm"],
                               capture_output=True, text=True)
            if r.returncode:
                return None, RSharpError("internal backend error", 0, 0)
            r = subprocess.run([exe], capture_output=True, text=True, stdin=subprocess.DEVNULL)
            return r, None

    while True:
        try:
            line = input("... " if buf else ">>> ")
        except EOFError:
            print()
            return 0
        buf.append(line)
        text = "\n".join(buf)
        if depth(text) > 0:
            continue
        buf = []
        t = text.strip()
        if not t:
            continue
        cands = [t]
        if not t.endswith((";", "}")):
            cands = [f"print({t});", t + ";"]
        last_err = None
        for cand in cands:
            r, err = attempt(cand)
            if err is None:
                break
            last_err = err
        else:
            print(f"error: {last_err.msg}" + (f" (col {last_err.col})" if last_err.line == len(history) + 1 else ""))
            continue
        out = r.stdout
        print(out[len(shown):] if out.startswith(shown) else out, end="")
        if r.returncode:
            print(r.stderr.strip())
            continue
        history.append(cand)
        shown = out


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help", "help"):
        print(USAGE)
        return 0 if a else 2
    if a[0] in ("--version", "-V"):
        print(f"rsharp {VERSION}")
        return 0
    cmd = a[0]
    if cmd in NOT_YET:
        print(f"rsharp {cmd}: not implemented yet (planned for a later milestone)", file=sys.stderr)
        return 2
    if cmd == "pkg":
        from .pkg import main as pkg_main
        return pkg_main(a[1:])
    if cmd == "repl":
        return repl()
    if cmd.endswith(".rsharp"):
        cmd, rest = "run", a
    else:
        rest = a[1:]
    try:
        if cmd == "test":
            return run_tests(rest[0] if rest else "tests")
        if cmd in ("run", "build", "check") and (not rest or rest[0].startswith("-")):
            p = project_main()
            if not p:
                print(f"rsharp {cmd}: no file given and no project (rsharp.toml + src/main.rsharp) found", file=sys.stderr)
                return 2
            rest = [p] + rest
        if not rest:
            print(USAGE, file=sys.stderr)
            return 2
        path = rest[0]
        if not os.path.isfile(path):
            print(f"rsharp: no such file: {path}", file=sys.stderr)
            return 2
        if cmd == "run":
            return run_file(path)
        if cmd == "build":
            out = rest[rest.index("-o") + 1] if "-o" in rest else None
            print(f"built {build(path, out)}")
            return 0
        if cmd == "check":
            src = open(path, encoding="utf-8").read()
            try:
                compile_to_c(src, path)
            except RSharpError as e:
                report(e, path, src)
                return 1
            print("ok")
            return 0
        if cmd == "emit-c":
            print(build(path, emit_c=True))
            return 0
    except RSharpError:
        return 1  # already reported
    except RuntimeError:
        return 70
    except Exception as e:  # compiler bug: report cleanly instead of a traceback
        print(f"internal compiler error: {type(e).__name__}: {e}\n(please report this with the program that triggered it)", file=sys.stderr)
        return 70
    print(f"rsharp: unknown command '{cmd}'\n{USAGE}", file=sys.stderr)
    return 2
