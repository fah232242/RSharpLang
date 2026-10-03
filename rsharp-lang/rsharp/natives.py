"""Native standard modules (implemented in the C runtime). "num" params accept int or float64."""
FUNCS = {
    "math": {
        "sqrt": (["num"], "float64", "sqrt({0})"),
        "pow": (["num", "num"], "float64", "pow({0}, {1})"),
        "floor": (["num"], "int", "rs_f2i(floor({0}))"),
        "ceil": (["num"], "int", "rs_f2i(ceil({0}))"),
        "sin": (["num"], "float64", "sin({0})"),
        "cos": (["num"], "float64", "cos({0})"),
        "tan": (["num"], "float64", "tan({0})"),
        "atan2": (["num", "num"], "float64", "atan2({0}, {1})"),
        "log": (["num"], "float64", "log({0})"),
        "log10": (["num"], "float64", "log10({0})"),
        "exp": (["num"], "float64", "exp({0})"),
        "hypot": (["num", "num"], "float64", "hypot({0}, {1})"),
        "gcd": (["int", "int"], "int", "rs_gcd({0}, {1})"),
    },
    "random": {
        "random": ([], "float64", "rs_random()"),
        "randint": (["int", "int"], "int", "rs_randint({0}, {1})"),
        "seed": (["int"], "void", "rs_seed({0})"),
    },
    "time": {
        "now": ([], "float64", "rs_now()"),
        "sleep": (["num"], "void", "rs_sleep({0})"),
    },
}
CONSTS = {
    "math": {"pi": ("float64", "3.141592653589793"), "e": ("float64", "2.718281828459045"),
             "tau": ("float64", "6.283185307179586"), "inf": ("float64", "INFINITY")},
}
