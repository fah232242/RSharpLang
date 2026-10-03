"""Native standard modules (implemented in the C runtime). "num" params accept int or float64."""
GAME = {
    "delta": ([], "float64", "rs_game_delta()"),
    "fixed_delta": ([], "float64", "rs_game_fixed_delta()"),
    "frame": ([], "int", "rs_game_frame()"),
    "seconds": ([], "float64", "rs_game_seconds()"),
    "fps": ([], "float64", "rs_game_fps()"),
    "quit": ([], "void", "rs_game_quit()"),
    "max_frames": (["int"], "void", "rs_game_max_frames({0})"),
    "target_fps": (["int"], "void", "rs_game_target_fps({0})"),
    "realtime": (["bool"], "void", "rs_game_realtime({0})"),
    "window": (["int", "int"], "void", "rs_fb_window({0}, {1})"),
    "width": ([], "int", "rs_fb_width()"),
    "height": ([], "int", "rs_fb_height()"),
    "clear": (["int", "int", "int"], "void", "rs_fb_clear({0}, {1}, {2})"),
    "pixel": (["int", "int", "int", "int", "int"], "void", "rs_fb_pixel({0}, {1}, {2}, {3}, {4})"),
    "fill_rect": (["int"] * 7, "void", "rs_fb_rect({0}, {1}, {2}, {3}, {4}, {5}, {6})"),
    "circle": (["int"] * 6, "void", "rs_fb_circle({0}, {1}, {2}, {3}, {4}, {5})"),
    "line": (["int"] * 7, "void", "rs_fb_line({0}, {1}, {2}, {3}, {4}, {5}, {6})"),
    "pixel_at": (["int", "int"], "int", "rs_fb_get({0}, {1})"),
    "save_frame": (["string"], "void", "rs_fb_save({0})"),
}
FUNCS = {
    "game": GAME,
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
