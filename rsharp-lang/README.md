# R# (v0.1)

    sh bin/rsharp run examples/main.rsharp      # needs python3 and gcc
    sh bin/rsharp test tests                     # language tests
    python3 -m unittest tests.test_compiler      # compiler/CLI unit tests

See `docs/SPEC-v0.1.md` for exactly what the language supports today.

## Status (only tested things are marked done)
| Area | State |
|---|---|
| Lexer, parser, AST, type checker | done (v0.1 subset) |
| Native compile via C + gcc | done; LLVM backend not started |
| ints, floats, bools, strings, interpolation, arrays, if/while/for, functions, recursion | done |
| `run`, `build`, `check`, `emit-c`, `test` commands | done |
| structs, classes, interfaces, enums, modules, generics, match, closures | not started (v0.2/0.3) |
| async, exceptions, Result, optionals, unsafe/FFI, GC | not started |
| package manager (`pkg`), registry, official `@rsharp/*` packages | not started |
| fmt, lint, repl, doc, language server, VS Code extension, debugger | not started |
| WebAssembly / ARM64 / Windows / macOS | untested (only Linux x86-64 verified) |

Layout note: compiler stages are flat modules in `rsharp/compiler/` (not the per-stage directories
from the brief) until there is enough code to justify splitting them.
