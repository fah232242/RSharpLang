import os, subprocess, sys, tempfile, unittest
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
from rsharp.compiler.lexer import tokenize
from rsharp.compiler.parser import parse
from rsharp.compiler.checker import check
from rsharp.compiler.errors import RSharpError
from rsharp.compiler import ast as A


def run(src):
    with tempfile.TemporaryDirectory() as td:
        f = os.path.join(td, "p.rsharp")
        with open(f, "w") as fh:
            fh.write(src)
        return subprocess.run([sys.executable, "-m", "rsharp", "run", f], cwd=ROOT,
                              capture_output=True, text=True)


class Lexer(unittest.TestCase):
    def kinds(self, s):
        return [t.kind for t in tokenize(s)][:-1]

    def test_basic(self):
        self.assertEqual(self.kinds("let x = 1_000 + 2.5e3;"),
                         ["KW", "IDENT", "OP", "INT", "OP", "FLOAT", "OP"])

    def test_range_not_float(self):
        t = tokenize("1..5")
        self.assertEqual([(x.kind, x.value) for x in t[:3]], [("INT", 1), ("OP", ".."), ("INT", 5)])

    def test_comments_and_positions(self):
        t = tokenize("// c\n/* x\ny */ foo")
        self.assertEqual((t[0].value, t[0].line, t[0].col), ("foo", 3, 6))

    def test_hex(self):
        self.assertEqual(tokenize("0xFF")[0].value, 255)

    def test_int_too_large(self):
        with self.assertRaises(RSharpError):
            tokenize("9223372036854775808")

    def test_bad_escape(self):
        with self.assertRaises(RSharpError):
            tokenize(r'"\q"')

    def test_interp_parts(self):
        t = tokenize('$"a{x}b{{c}}"')[0]
        self.assertEqual(t.kind, "ISTRING")
        self.assertEqual(t.value[0], "a")
        self.assertEqual(t.value[1][0], "x")
        self.assertEqual(t.value[2], "b{c}")


class Parser(unittest.TestCase):
    def test_precedence(self):
        e = parse("let x = 1 + 2 * 3;").items[0].value
        self.assertEqual(e.op, "+")
        self.assertEqual(e.right.op, "*")

    def test_expr_fn_desugars(self):
        f = parse("fn sq(x: int) -> int => x * x;").items[0]
        self.assertIsInstance(f.body.stmts[0], A.Return)

    def test_missing_semicolon(self):
        with self.assertRaises(RSharpError):
            parse("let x = 1")

    def test_param_needs_type(self):
        with self.assertRaises(RSharpError):
            parse("fn f(x) {}")

    def test_future_type(self):
        with self.assertRaisesRegex(RSharpError, "not implemented"):
            parse("let x: int32 = 1;")

    def test_error_position(self):
        try:
            parse("let x = ;")
        except RSharpError as e:
            self.assertEqual((e.line, e.col), (1, 9))


class Checker(unittest.TestCase):
    def test_types_annotated(self):
        p = check(parse("let a = [1.5];"))
        self.assertEqual(p.items[0].value.ty, ("array", "float64"))

    def test_main_signature(self):
        with self.assertRaises(RSharpError):
            check(parse("fn main(x: int) {}"))

    def test_builtin_redefine(self):
        with self.assertRaises(RSharpError):
            check(parse("fn print() {}"))

    def test_fn_cannot_see_script_let(self):
        with self.assertRaisesRegex(RSharpError, "undefined variable"):
            check(parse("let g = 1; fn f() -> int => g;"))


class Runtime(unittest.TestCase):
    def test_div_zero_panics(self):
        r = run("let z = 0;\nprint(1 / z);")
        self.assertEqual(r.returncode, 101)
        self.assertIn("division by zero (line 2)", r.stderr)

    def test_mod_zero_panics(self):
        self.assertEqual(run("let z = 0;\nprint(1 % z);").returncode, 101)

    def test_index_oob_panics(self):
        r = run("let a = [1, 2];\nlet i = 5;\nprint(a[i]);")
        self.assertEqual(r.returncode, 101)
        self.assertIn("index 5 out of bounds for length 2", r.stderr)

    def test_negative_index_panics(self):
        self.assertEqual(run("let a = [1];\nlet i = 0 - 2;\nprint(a[i]);").returncode, 101)

    def test_overflow_panics(self):
        r = run("mut x = 9223372036854775807;\nx += 1;\nprint(x);")
        self.assertEqual(r.returncode, 101)
        self.assertIn("overflow", r.stderr)

    def test_stdout_flushed_before_panic(self):
        r = run('print("before");\nlet z = 0;\nprint(1 / z);')
        self.assertEqual(r.stdout, "before\n")

    def test_float_to_int_range(self):
        self.assertEqual(run("print(int(1e30));").returncode, 101)

    def test_float_div_zero_is_ieee(self):
        self.assertEqual(run("let z = 0.0;\nprint(1.0 / z);").stdout, "inf\n")

    def test_compile_error_exit_code_and_format(self):
        r = run("let x = ;")
        self.assertEqual(r.returncode, 1)
        self.assertIn("p.rsharp:1:9: error:", r.stderr)
        self.assertIn("^", r.stderr)

    def test_hello(self):
        self.assertEqual(run('fn main() {\n    print("Hello, world!");\n}').stdout, "Hello, world!\n")

    def test_milestone_sum(self):
        self.assertEqual(run("fn main() {\n let x = 10;\n let y = 20;\n print(x + y);\n}").stdout, "30\n")


class Cli(unittest.TestCase):
    def cli(self, *a):
        return subprocess.run([sys.executable, "-m", "rsharp", *a], cwd=ROOT, capture_output=True, text=True)

    def test_version(self):
        self.assertIn("rsharp 0.2.0", self.cli("--version").stdout)

    def test_unimplemented_commands_are_honest(self):
        for c in ("fmt", "lint", "doc"):
            r = self.cli(c)
            self.assertEqual(r.returncode, 2)
            self.assertIn("not implemented", r.stderr)

    def test_build_produces_executable(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "hello")
            r = self.cli("build", "examples/hello.rsharp", "-o", out)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(subprocess.run([out], capture_output=True, text=True).stdout, "Hello, world!\n")

    def test_missing_file(self):
        self.assertEqual(self.cli("run", "nope.rsharp").returncode, 2)


if __name__ == "__main__":
    unittest.main()


class PkgAndRepl(unittest.TestCase):
    def cli(self, *a, cwd=None, inp=None):
        env = dict(os.environ, PYTHONPATH=os.path.abspath(ROOT))
        return subprocess.run([sys.executable, "-m", "rsharp", *a], cwd=cwd or ROOT, env=env,
                              capture_output=True, text=True, input=inp)

    def test_project_flow(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(self.cli("pkg", "new", "app", "demo", cwd=td).returncode, 0)
            proj = os.path.join(td, "demo")
            self.assertEqual(self.cli("pkg", "add", "@rsharp/text", cwd=proj).returncode, 0)
            with open(os.path.join(proj, "src", "main.rsharp"), "w") as f:
                f.write('import text;\nprint(text.pad_left("5", 3, "0"));\n')
            self.assertEqual(self.cli("run", cwd=proj).stdout, "005\n")
            self.assertTrue(os.path.isfile(os.path.join(proj, "rsharp.lock")))
            self.assertEqual(self.cli("pkg", "audit", cwd=proj).returncode, 0)
            with open(os.path.join(proj, "rsharp_packages", "text", "lib.rsharp"), "a") as f:
                f.write("// tampered\n")
            self.assertEqual(self.cli("pkg", "audit", cwd=proj).returncode, 1)

    def test_unknown_package_is_honest(self):
        with tempfile.TemporaryDirectory() as td:
            self.cli("pkg", "new", "app", "d", cwd=td)
            r = self.cli("pkg", "add", "nope", cwd=os.path.join(td, "d"))
            self.assertEqual(r.returncode, 1)
            self.assertIn("registry", r.stderr)

    def test_repl(self):
        r = self.cli("repl", inp="let x = 10;\nx * 5\n")
        self.assertIn("50", r.stdout)

    def test_error_in_module_names_the_module_file(self):
        with tempfile.TemporaryDirectory() as td:
            with open(os.path.join(td, "bad.rsharp"), "w") as f:
                f.write("fn f() -> int => 1 + \"a\";\n")
            with open(os.path.join(td, "main.rsharp"), "w") as f:
                f.write("import bad;\nprint(bad.f());\n")
            r = self.cli("run", os.path.join(td, "main.rsharp"))
            self.assertEqual(r.returncode, 1)
            self.assertIn("bad.rsharp:1:", r.stderr)
