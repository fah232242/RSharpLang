#!/bin/sh
# Installs an `rsharp` launcher into ~/.local/bin (make sure that directory is on your PATH).
ROOT="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.local/bin"
printf '#!/bin/sh\nPYTHONPATH="%s" exec python3 -m rsharp "$@"\n' "$ROOT" > "$HOME/.local/bin/rsharp"
chmod +x "$HOME/.local/bin/rsharp"
echo "installed ~/.local/bin/rsharp"
