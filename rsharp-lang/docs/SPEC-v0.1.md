# R# Language Specification v0.1

Status: **implemented subset**. This document describes exactly what the v0.1 compiler
accepts. Everything else in the R# design (classes, generics, async, packages, ...) is
*planned, not implemented*; the compiler rejects it with a clear error.

## 1. Files and tools
Source files use `.rsharp` (UTF-8). CLI: `rsharp run|build|check|emit-c|test`.
`rsharp file.rsharp` is shorthand for `run`. Compile errors print `file:line:col: error: msg`
with a caret and exit 1. Runtime panics print `panic: ...` to stderr and exit 101.

## 2. Program structure
A file is a sequence of function declarations and statements. Top-level statements run in
order (the "script"); afterwards `fn main()` runs if it exists (`main` takes no parameters
and returns nothing). So both of these work:

    print("Hello, world!");
    fn main() { print("Hello, world!"); }

Functions may be called before they are declared. Functions cannot see top-level `let`/`mut`
variables; they can see top-level `const`s declared *above* them.

## 3. Lexical structure
Comments `//` and `/* */`. Identifiers `[A-Za-z_][A-Za-z0-9_]*`. Integer literals (decimal, `0x`
hex, `_` separators), float literals (`1.5`, `2e3`). Strings `"..."` with escapes
`\n \t \r \\ \" \0`; interpolated strings `$"x = {x + 1}"` (`{{`/`}}` for literal braces).
Keywords: `fn let mut const if else while for in return break continue true false`.
Reserved for future versions (using them is an error): `struct class interface enum match import
from pub async await try catch finally throw unsafe using defer null this new static abstract sealed
public private protected implements extends spawn namespace`.
Semicolons are required after simple statements.

## 4. Types
`int` (alias `int64`, 64-bit signed), `float64`, `bool`, `string`, `void`, and arrays `T[]`
(`int[]`, `string[][]`). Other spec types (`int8`..`uint64`, `float32`, `char`, `byte`, `any`,
`never`, optionals `T?`) are **not implemented**.
There are **no implicit conversions**. `1 + 2.0` is an error; use `float64(1) + 2.0`.
Conversions: `int(x)` (truncates a float; panics if out of range), `float64(x)`, `str(x)`.

## 5. Variables
    let x = 1;          // immutable binding, type inferred
    mut y: int = 2;     // mutable
    const N = 10;       // immutable; at top level it is a global visible to later functions
Variables must be initialized. Redeclaring a name in the *same* scope is an error; shadowing
in an inner block is allowed.

## 6. Functions
    fn add(a: int, b: int) -> int { return a + b; }
    fn square(x: int) -> int => x * x;
    fn hello() { print("hi"); }          // no `->` means void
Parameters must be annotated; they are immutable. Recursion is allowed. A non-void function
must return on every path (checked). Functions are **not** first-class values yet (no arrow
functions or closures in v0.1).

## 7. Expressions
Precedence (low to high): `||`, `&&`, `== !=`, `< <= > >=`, `+ -`, `* / %`, unary `- !`,
postfix call/index/member. Operand types must match exactly.
- `int`: `+ - * / %` are **checked**; overflow, divide-by-zero panic. `/` truncates toward zero.
- `float64`: IEEE-754 (`1.0/0.0` is `inf`).
- `string`: `+` concatenates; `== != < ...` compare bytewise. `s.length`/`len(s)` is the **byte**
  length (UTF-8) in v0.1.
- `&&`, `||` short-circuit. Conditions must be `bool` (no truthiness).
- **Evaluation order is left to right**, including call arguments and operands.
- `==`/`!=` on arrays is not supported yet.

## 8. Arrays
    mut xs = [1, 2, 3];      xs.push(4);      xs[0] = 9;      print(xs.length, len(xs));
Arrays are heap objects with **reference semantics** (`mut b = a;` aliases). Indexing is bounds
checked (panic). `push`, element assignment, and `+=` on elements require the root variable to be
declared `mut` (so function parameters, being immutable, cannot be mutated through).
An empty literal needs a type: `let e: int[] = [];`.

## 9. Statements
`if / else if / else`, `while`, `for x in array`, `for i in lo..hi` (half-open, `hi` evaluated once),
`break`, `continue`, `return`, blocks, assignment (`= += -= *= /= %=`), expression statements.
Conditions need no parentheses; bodies always need braces.

## 10. Built-ins
`print(a, b, ...)` space-separated + newline (floats print shortest round-trip, with `.0`;
arrays print as `[1, 2]`, strings inside arrays are quoted), `len`, `int`, `float64`, `str`.

## 11. Memory
v0.1 has no garbage collector: strings and arrays are allocated and reclaimed at process exit.
Fine for scripts and tools, not for long-running programs. (GC / ownership is future work.)

## 12. Implementation notes
Pipeline: lexer -> parser -> AST -> name resolution + type check (annotated AST) -> C11 -> `gcc -O2`
-> native executable. The planned LLVM IR backend is not started. Requires `gcc` (or `$CC`) with
GNU extensions (statement expressions).
