# R# game development (v0.3, headless)

What exists today is a **real but small, headless** game runtime. There is **no window, GPU, audio or
input yet** (that needs native libraries such as SDL2/OpenGL and an FFI, neither of which R# has).
Games run deterministically, render with a software framebuffer, and export frames as PPM images.

## A game
    import game;
    game "My Game";                 # marks this program as a game (enables the loop)

    mut x = 0.0;                    # top-level variables are globals visible to functions below them
    fn start()              { game.window(320, 180); game.max_frames(120); }
    fn fixed_update(dt: float64) { x += 50.0 * dt; }       # fixed timestep (default 1/60 s)
    fn update(dt: float64)  { }                            # once per frame
    fn draw()               { game.clear(0, 0, 0); game.circle(int(x), 90, 8, 255, 200, 0); }
    fn shutdown()           { game.save_frame("out.ppm"); }

Hooks (all optional, but at least `update` or `draw` is required; wrong signatures are compile errors):
`start()`, `update(delta: float64)`, `fixed_update(delta: float64)`, `draw()`, `shutdown()`.
The loop runs until `game.quit()` or `game.max_frames(n)` frames. Time is simulated by default
(`delta = 1/target_fps`, no sleeping), so runs are reproducible and fast; `game.realtime(true)` uses the
wall clock and sleeps to hold `target_fps`.

## `game` module
Timing: `delta() fixed_delta() frame() seconds() fps() quit() max_frames(n) target_fps(n) realtime(b)`.
Software 2D (colors are ints 0-255, drawing is clipped): `window(w,h) width() height() clear(r,g,b)
pixel(x,y,r,g,b) fill_rect(x,y,w,h,r,g,b) circle(cx,cy,radius,r,g,b) line(x0,y0,x1,y1,r,g,b)
pixel_at(x,y) -> 0xRRGGBB  save_frame(path)`. Drawing before `game.window` panics with a clear message.

## Structs (new language feature)
    struct Player { name: string, pos: Vec2, hp: int, tags: string[] }
    mut p = Player { name: "Ann", pos: vec.vec2(0.0, 0.0), hp: 50, tags: [] };
    p.pos.x = 3.0;  p.hp -= 5;  pts[i].y = 9.0;  by_name["a"].hp = 1;
Structs are **value types** (assignment and passing copy). Fields are mutable only through a `mut`
variable. They may hold scalars, other (earlier-declared) structs, arrays and maps; they print as
`Name(x=1.0, ...)`. Struct names are global across modules and start with an uppercase letter.
Not yet: methods/`impl`, default field values, `==`, recursive structs, generics, traits.

## Packages and tools
`vec` (Vec2/Vec3 math: `add2 sub2 scale2 dot2 len2 dist2 norm2 lerp2`, `add3 ... cross3 norm3`).
`sharpie new MyGame && cd MyGame && sharpie run` creates and runs a working game project
(`bin/sharpie` is a thin front-end for `rsharp pkg`; `sharpie add/remove/list/search/audit` work offline).
Example: `examples/bounce/main.rsharp` (fixed-timestep physics + software rendering).

## Not implemented (honest list)
Windowing, GPU/graphics backends, shaders (RSL), 3D, audio, input devices, ECS (`@component`/`@system`/
`Query`), scenes/prefabs, physics engine, animation, UI toolkit, networking/multiplayer, asset pipeline and
hot reload, profiler/debugger/editor, WebAssembly/mobile targets, traits/generics/closures/`match`,
an online registry and version resolver. Gameplay today is written with structs + arrays + functions.
Recommended next steps: methods on structs, closures/function values, an SDL2-backed window via a C FFI,
then a small ECS built on arrays of structs.
