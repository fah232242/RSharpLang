"""`rsharp pkg`: a small *offline* package manager.
Packages come from (a) the official packages bundled with the compiler, or (b) local paths.
There is no online registry yet; commands that need one say so."""
import hashlib, json, os, shutil, sys
try:
    import tomllib
except ImportError:  # python < 3.11
    tomllib = None

BUNDLED = os.path.join(os.path.dirname(__file__), "packages")
MANIFEST = "rsharp.toml"
LOCK = "rsharp.lock"
NO_REGISTRY = ("the online registry (packages.rsharp.dev) does not exist yet; "
               "only bundled @rsharp/* packages and --path dependencies are available")


def load_toml(path):
    if tomllib is None:
        raise SystemExit("rsharp pkg needs Python 3.11+ (tomllib)")
    with open(path, "rb") as f:
        return tomllib.load(f)


def q(v):
    return json.dumps(v)  # valid TOML basic string


def dump_manifest(m):
    out = ["[package]"]
    for k, v in m.get("package", {}).items():
        out.append(f"{k} = {json.dumps(v)}")
    for sec in ("dependencies", "dev-dependencies"):
        if sec in m:
            out += ["", f"[{sec}]"]
            for k, v in m[sec].items():
                if isinstance(v, dict):
                    out.append(f"{k} = {{ " + ", ".join(f"{a} = {q(b)}" for a, b in v.items()) + " }")
                else:
                    out.append(f"{k} = {q(v)}")
    return "\n".join(out) + "\n"


def find_project(start="."):
    d = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(d, MANIFEST)):
            return d
        if os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)


def need_project():
    root = find_project()
    if not root:
        raise SystemExit(f"error: no {MANIFEST} found (run 'rsharp pkg init' first)")
    return root


def dir_checksum(d):
    h = hashlib.sha256()
    for r, _, fs in sorted(os.walk(d)):
        for f in sorted(fs):
            p = os.path.join(r, f)
            h.update(os.path.relpath(p, d).replace(os.sep, "/").encode())
            h.update(open(p, "rb").read())
    return "sha256:" + h.hexdigest()


def bundled_names():
    return sorted(n for n in os.listdir(BUNDLED) if os.path.isfile(os.path.join(BUNDLED, n, "lib.rsharp")))


def bundled_meta(name):
    return load_toml(os.path.join(BUNDLED, name, MANIFEST))["package"]


TEMPLATES = {
    "app": ("src/main.rsharp", 'print("Hello from R#!");\n'),
    "library": ("src/lib.rsharp", 'fn greet(name: string) -> string => $"Hello, {name}!";\n'),
}


def scaffold(root, name, kind):
    os.makedirs(os.path.join(root, "src"), exist_ok=True)
    os.makedirs(os.path.join(root, "tests"), exist_ok=True)
    rel, body = TEMPLATES[kind]
    m = {"package": {"name": name, "version": "0.1.0", "description": f"My R# {kind}", "license": "MIT"},
         "dependencies": {}}
    with open(os.path.join(root, MANIFEST), "w") as f:
        f.write(dump_manifest(m))
    path = os.path.join(root, rel)
    if not os.path.exists(path):
        with open(path, "w") as f:
            f.write(body)
    if kind == "library":
        t = os.path.join(root, "tests", f"test_{name}.rsharp")
        if not os.path.exists(t):
            with open(t, "w") as f:
                f.write(f'import {name} from "../src/lib";\nprint({name}.greet("R#"));  // expect: Hello, R#!\n')
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write("rsharp_packages/\n*.exe\n")


def write_lock(root):
    m = load_toml(os.path.join(root, MANIFEST))
    pkgs = []
    vend = os.path.join(root, "rsharp_packages")
    for name, spec in {**m.get("dependencies", {}), **m.get("dev-dependencies", {})}.items():
        d = os.path.join(vend, name)
        if os.path.isdir(d):
            ver = load_toml(os.path.join(d, MANIFEST))["package"].get("version", "0") if os.path.isfile(os.path.join(d, MANIFEST)) else "0"
            src = "path:" + spec["path"] if isinstance(spec, dict) else "bundled"
            pkgs.append({"name": name, "version": ver, "source": src, "checksum": dir_checksum(d)})
    with open(os.path.join(root, LOCK), "w") as f:
        json.dump({"lock_version": 1, "packages": pkgs}, f, indent=2)
        f.write("\n")


def vendor(root, name, src_dir):
    dst = os.path.join(root, "rsharp_packages", name)
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src_dir, dst)


def main(a):
    if not a:
        print("usage: rsharp pkg init|new|add|remove|update|list|search|audit [args]\n"
              "  init                      create rsharp.toml in the current directory\n"
              "  new [app|library] NAME    create a project directory\n"
              "  add NAME [--path DIR]     add a bundled (@rsharp/NAME) or local package\n"
              "  remove NAME | update | list | search TERM | audit\n"
              "  publish                   not implemented (no registry yet)")
        return 2
    cmd, rest = a[0], a[1:]
    if cmd == "init":
        if os.path.exists(MANIFEST):
            print(f"{MANIFEST} already exists", file=sys.stderr)
            return 1
        scaffold(".", os.path.basename(os.getcwd()).replace("-", "_") or "app", "app")
        print(f"created {MANIFEST} and src/main.rsharp")
        return 0
    if cmd == "new":
        kind = "app"
        if rest and rest[0] in ("app", "library", "lib", "server", "cli"):
            kind, rest = rest[0], rest[1:]
        if kind == "lib":
            kind = "library"
        if kind in ("server", "cli"):
            print(f"template '{kind}' needs @rsharp/{'http' if kind == 'server' else 'cli'}, which is not implemented yet", file=sys.stderr)
            return 2
        if not rest:
            print("usage: rsharp pkg new [app|library] NAME", file=sys.stderr)
            return 2
        name = rest[0]
        if os.path.exists(name):
            print(f"'{name}' already exists", file=sys.stderr)
            return 1
        scaffold(name, name.replace("-", "_"), kind)
        print(f"created {kind} '{name}'. Next: cd {name} && rsharp run" if kind == "app" else f"created {kind} '{name}'")
        return 0
    if cmd == "search":
        term = (rest[0] if rest else "").lower()
        hits = [(n, bundled_meta(n).get("description", "")) for n in bundled_names()]
        hits = [h for h in hits if term in h[0] or term in h[1].lower()]
        for n, d in hits:
            print(f"@rsharp/{n:<10} {d}")
        if not hits:
            print(f"no bundled package matches '{term}' ({NO_REGISTRY})")
        return 0
    if cmd == "add":
        root = need_project()
        if not rest:
            print("usage: rsharp pkg add NAME [--path DIR]", file=sys.stderr)
            return 2
        name, m = rest[0], load_toml(os.path.join(find_project(), MANIFEST))
        dev = "--dev" in rest
        if "--path" in rest:
            src = os.path.abspath(rest[rest.index("--path") + 1])
            lib = os.path.join(src, "src") if os.path.isfile(os.path.join(src, "src", "lib.rsharp")) else src
            if not os.path.isfile(os.path.join(lib, "lib.rsharp")):
                print(f"error: {src} has no lib.rsharp (or src/lib.rsharp)", file=sys.stderr)
                return 1
            spec = {"path": os.path.relpath(src, root)}
            tmp = os.path.join(root, "rsharp_packages", name)
            vendor(root, name, lib)
        else:
            base = name.split("/")[-1]
            if base not in bundled_names():
                print(f"error: package '{name}' not found; {NO_REGISTRY}", file=sys.stderr)
                return 1
            vendor(root, base, os.path.join(BUNDLED, base))
            name, spec = base, bundled_meta(base).get("version", "0.0.0")
        m.setdefault("dev-dependencies" if dev else "dependencies", {})[name] = spec
        with open(os.path.join(root, MANIFEST), "w") as f:
            f.write(dump_manifest(m))
        write_lock(root)
        print(f"added {name} ({spec if isinstance(spec, str) else 'path ' + spec['path']})")
        return 0
    if cmd == "remove":
        root = need_project()
        if not rest:
            print("usage: rsharp pkg remove NAME", file=sys.stderr)
            return 2
        name = rest[0].split("/")[-1]
        m = load_toml(os.path.join(root, MANIFEST))
        found = False
        for sec in ("dependencies", "dev-dependencies"):
            found |= m.get(sec, {}).pop(name, None) is not None
        if not found:
            print(f"error: '{name}' is not a dependency", file=sys.stderr)
            return 1
        shutil.rmtree(os.path.join(root, "rsharp_packages", name), ignore_errors=True)
        with open(os.path.join(root, MANIFEST), "w") as f:
            f.write(dump_manifest(m))
        write_lock(root)
        print(f"removed {name}")
        return 0
    if cmd == "list":
        root = need_project()
        m = load_toml(os.path.join(root, MANIFEST))
        print(f"{m['package']['name']} {m['package'].get('version', '')}")
        for sec in ("dependencies", "dev-dependencies"):
            for n, s in m.get(sec, {}).items():
                print(f"  {n} {s if isinstance(s, str) else 'path ' + s['path']}{' (dev)' if sec != 'dependencies' else ''}")
        return 0
    if cmd == "update":
        root = need_project()
        m = load_toml(os.path.join(root, MANIFEST))
        for sec in ("dependencies", "dev-dependencies"):
            for n, s in m.get(sec, {}).items():
                if isinstance(s, str) and n in bundled_names():
                    vendor(root, n, os.path.join(BUNDLED, n))
                    m[sec][n] = bundled_meta(n).get("version", s)
                    print(f"updated {n} -> {m[sec][n]}")
        with open(os.path.join(root, MANIFEST), "w") as f:
            f.write(dump_manifest(m))
        write_lock(root)
        print("(only bundled packages can be updated; " + NO_REGISTRY + ")")
        return 0
    if cmd == "audit":
        root = need_project()
        lock = os.path.join(root, LOCK)
        if not os.path.isfile(lock):
            print("no rsharp.lock; nothing to audit")
            return 0
        bad = 0
        for p in json.load(open(lock))["packages"]:
            d = os.path.join(root, "rsharp_packages", p["name"])
            ok = os.path.isdir(d) and dir_checksum(d) == p["checksum"]
            print(f"  {'ok      ' if ok else 'MODIFIED'} {p['name']} {p['version']}")
            bad += not ok
        print("integrity check only: there is no security-advisory database yet, so known "
              "vulnerabilities cannot be reported.")
        return 1 if bad else 0
    if cmd == "publish":
        print("rsharp pkg publish: not implemented (" + NO_REGISTRY + ")", file=sys.stderr)
        return 2
    print(f"unknown pkg command '{cmd}'", file=sys.stderr)
    return 2
