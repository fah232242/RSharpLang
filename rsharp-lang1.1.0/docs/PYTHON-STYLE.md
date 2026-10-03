# R# v0.2: Python-style layer

New since v0.1 (all covered by tests in `tests/`):

- Syntax: `#` comments, `and`/`or`/`not`, `x in y`, `x not in y`, `**`, `a[i:j]` slices, negative
  indexes (`xs[-1]`), `for i in range(a, b, step)`, `for k, v in map`, `for ch in string`, `"ab" * 3`.
- Types: `map<V>` (string keys, insertion-ordered): `{"a": 1}`, `m["k"]`, `m["k"] = v`, `m.get(k, d)`,
  `m.keys()`, `m.values()`, `m.remove(k)`, `k in m`, `len(m)`. Empty map needs a type: `let m: map<int> = {};`
- Builtins: `len int float64 str range input abs min max sum sorted reversed round read_file write_file exit assert ord chr`
  (`round` is banker's rounding like Python; `int("42")`/`float64("1.5")` parse strings).
- String methods: `upper lower strip contains startswith endswith replace split find join`
  (`", ".join(parts)`). Array methods: `push append pop contains reverse sort extend clear copy`.
- Modules: `import m;` `import m as n;` `from m import a, b as c;` `import m from "@rsharp/m";`
  Resolution order: native (`math`, `random`, `time`), `./m.rsharp`, `./m/lib.rsharp`,
  `rsharp_packages/m/lib.rsharp` (searching parent dirs), bundled packages. `pub` is accepted; all module
  members are currently public. Modules may contain only functions, consts and imports.
- Native modules: `math` (sqrt pow floor ceil sin cos tan atan2 log log10 exp hypot gcd, pi e tau inf),
  `random` (random randint seed), `time` (now sleep). `math` functions accept int or float64.
- Bundled packages: `text`, `stats`, `algo` (written in R# itself).

Deliberate differences from Python: no implicit numeric conversion (`1 + 2.0` is an error), conditions
must be `bool`, integer overflow panics, `/` on ints truncates (there is no `//`, since `//` is a comment),
`true`/`false` lowercase, statements end with `;`, braces instead of indentation.
