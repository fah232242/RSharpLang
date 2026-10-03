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

    def test_fn_sees_earlier_globals_only(self):
        check(parse("let g = 1; fn f() -> int => g;"))
        with self.assertRaisesRegex(RSharpError, "undefined variable"):
            check(parse("fn f() -> int => g; let g = 1;"))


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
        self.assertIn("rsharp 1.2.0", self.cli("--version").stdout)

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


class Game(unittest.TestCase):
    def test_framebuffer_needs_window(self):
        r = run("import game;\ngame.clear(0, 0, 0);")
        self.assertEqual(r.returncode, 101)
        self.assertIn("game.window", r.stderr)

    def test_save_frame_writes_valid_ppm(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, "f.ppm")
            r = run(f'import game;\ngame.window(4, 2);\ngame.clear(1, 2, 3);\ngame.save_frame("{out}");')
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(out, "rb") as fh:
                data = fh.read()
            self.assertTrue(data.startswith(b"P6\n4 2\n255\n"))
            self.assertEqual(data[len(b"P6\n4 2\n255\n"):][:3], bytes([1, 2, 3]))
            self.assertEqual(len(data), len(b"P6\n4 2\n255\n") + 4 * 2 * 3)

    def test_drawing_is_clipped_not_crashing(self):
        r = run("import game;\ngame.window(3, 3);\ngame.fill_rect(-5, -5, 100, 100, 9, 9, 9);\n"
                "game.circle(100, 100, 5, 1, 1, 1);\ngame.line(-9, -9, 20, 20, 1, 2, 3);\nprint(game.pixel_at(2, 2));")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "66051\n")  # line drawn last: (1<<16)|(2<<8)|3

    def test_bad_window_size_panics(self):
        self.assertEqual(run("import game;\ngame.window(0, 5);").returncode, 101)

    def test_unlimited_loop_stops_on_quit(self):
        r = run('import game;\ngame "Q";\nfn update(d: float64) { if game.frame() == 99 { game.quit(); } }\n'
                'fn shutdown() { print(game.frame()); }')
        self.assertEqual(r.stdout, "100\n")


class Robustness(unittest.TestCase):
    """Malformed input must produce a diagnostic (RSharpError) and never a Python crash."""

    def test_random_garbage_never_crashes(self):
        import random
        from rsharp.compiler.loader import Loader
        from rsharp.compiler.codegen import generate
        rng = random.Random(1234)
        seeds = ["fn f(a: int) -> int { return a + 1; }", "struct P { x: int } let p = P { x: 1 };",
                 'let m = {"a": [1, 2]}; for k, v in m { print(k); }', 'print($"x{1 + }");']
        alphabet = list("(){}[];:,.=+-*/<>!\"'#$ \nabcPxyz012") + ["fn ", "let ", "mut ", "struct ", "game ", "import ", "for ", "in "]
        for i in range(400):
            base = rng.choice(seeds)
            chars = list(base)
            for _ in range(rng.randint(1, 6)):
                pos = rng.randrange(len(chars) + 1)
                if rng.random() < 0.5 and chars:
                    del chars[min(pos, len(chars) - 1)]
                else:
                    chars.insert(pos, rng.choice(alphabet))
            src = "".join(chars)
            try:
                generate(check(Loader().load_main(None, src)))
            except RSharpError:
                pass
            except RecursionError:
                self.fail(f"recursion crash on {src!r}")
            except Exception as e:
                self.fail(f"{type(e).__name__}: {e} on {src!r}")

    def test_deeply_nested_input_does_not_crash(self):
        r = run("print(" + "(" * 3000 + "1" + ")" * 3000 + ");")
        self.assertIn(r.returncode, (0, 1, 70))
        self.assertNotIn("Traceback", r.stderr)


class GameProject(unittest.TestCase):
    def test_new_game_runs(self):
        env = dict(os.environ, PYTHONPATH=os.path.abspath(ROOT))
        with tempfile.TemporaryDirectory() as td:
            def cli(*a, cwd=td):
                return subprocess.run([sys.executable, "-m", "rsharp", *a], cwd=cwd, env=env, capture_output=True, text=True)
            self.assertEqual(cli("pkg", "new", "game", "Demo").returncode, 0)
            proj = os.path.join(td, "Demo")
            r = cli("run", cwd=proj)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("started Demo", r.stdout)
            self.assertTrue(os.path.isfile(os.path.join(proj, "last_frame.ppm")))
            self.assertTrue(os.path.isdir(os.path.join(proj, "assets", "textures")))
