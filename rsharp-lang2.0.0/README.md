# R# (v1.2.0)

A small statically-typed language with Python-style syntax that compiles to native executables
(R# -> C -> gcc). **Read "How to run programs" below first.**

## How to run programs

You need **Python 3.11+** and a C compiler (**gcc**; or set `CC=clang`).
Install gcc: Ubuntu/Debian `sudo apt install gcc` - macOS `xcode-select --install` - Windows: use WSL
(recommended) or MinGW (Windows is untested).

    unzip rsharp-lang1.2.0.zip && cd rsharp-lang
    sh bin/rsharp examples/hello.rsharp          # compile + run one file
    sh bin/rsharp run examples/primes.rsharp     # same thing
    sh bin/rsharp build examples/primes.rsharp -o primes && ./primes   # make a native binary
    sh bin/rsharp repl                           # interactive prompt
    sh bin/rsharp test tests                     # run the test suite

Optional: `sh install.sh` puts an `rsharp` command in `~/.local/bin` so you can type `rsharp file.rsharp`.

### Projects and packages
    rsharp pkg new app myapp && cd myapp     # creates rsharp.toml + src/main.rsharp
    rsharp pkg add @rsharp/text              # vendors a bundled package, writes rsharp.lock
    rsharp run                               # runs src/main.rsharp
    rsharp pkg list | search | audit | remove NAME

## What the language looks like
    import math;
    from text import pad_left;                # packages: text, stats, algo (bundled)

    # comments with # or //
    fn main() {
        let xs = [5, 3, 8, 1];
        print(sorted(xs), xs[-1], xs[1:3], 3 in xs, 2 ** 10);
        mut ages = {"alice": 30};
        ages["bob"] = 25;
        for name, age in ages { print($"{name} is {age}"); }
        for i in range(0, 10, 3) { print(i, math.sqrt(i)); }
    }
Python-style features: `and/or/not`, `in`, `**`, slicing, negative indexes, `range`, string/array/map
methods, `input()`, f-style `$"..."` strings, `import x as y`, `from x import a, b`, modules = files.
See `docs/SPEC-v0.1.md` (core), `docs/PYTHON-STYLE.md` (v0.2) and `docs/GAME.md` (v0.3: structs, game loop, 2D software renderer).

### Games (headless: no window yet)
    sh bin/sharpie new MyGame && cd MyGame && sh ../bin/sharpie run   # structs + game loop + frame export
    sh bin/rsharp examples/bounce/main.rsharp                          # writes bounce_last_frame.ppm

## Status (only tested things are marked done)
| Area | State |
|---|---|
| Lexer, parser, type checker, C backend (native via gcc) | done |
| ints, floats, bools, strings, arrays, `map<V>` (string keys), loops, functions | done |
| Modules/imports, bundled packages (`text`, `stats`, `algo`), native `math`/`random`/`time` | done |
| `rsharp pkg` init/new/add/remove/list/search/update/audit with `rsharp.lock` checksums | done (offline only) |
| REPL (replay-based, see limits) | done |
| structs, classes, traits, enums, `match`, generics, closures, `Option`/`Result` | not started |
| async, threads, exceptions, `unsafe`/pointers, FFI, GC | not started |
| online registry, `pkg publish`, dependency resolver with version ranges, git deps | not started |
| fmt, lint, doc, language server, debugger, LLVM/WASM backends | not started |

Known limits: no garbage collector (memory freed at exit); maps are string-keyed with linear lookup;
strings are bytes (indexing is ASCII-oriented); the REPL re-runs history each entry, so avoid
`input()`/`random`/`time` in it; tested on Linux x86-64 only.
