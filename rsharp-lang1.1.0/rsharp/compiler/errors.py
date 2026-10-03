class RSharpError(Exception):
    def __init__(self, msg, line=0, col=0):
        super().__init__(msg)
        self.msg, self.line, self.col = msg, line, col
        self.file = None


def format_error(e, filename, source):
    out = f"{filename}:{e.line}:{e.col}: error: {e.msg}"
    lines = source.splitlines()
    if 1 <= e.line <= len(lines):
        out += f"\n    {lines[e.line - 1]}\n    {' ' * max(e.col - 1, 0)}^"
    return out
