"""fylgja-core-server, the console script (`core/pyproject.toml`): SIGTERM ends it from the first
0.2 s of the process.

In a container the server is PID 1, which ignores a signal it has no handler for, and the import
of the server's modules takes about two seconds there (verified-facts.md, "The core's image"),
all of it before `main` installs its own handler. So this module imports `signal` alone, installs
a handler that exits 143, nothing being open yet, and only then imports the server and runs its
`main`, whose own handler replaces this one before anything is opened.

`python -m fylgja_core.server` runs the server's `__main__` without it: for the development host,
where the server is not PID 1 and SIGTERM's default action ends it during the import.
"""

import signal


def _terminated(signum: int, frame: object) -> None:
    raise SystemExit(143)


def main() -> int:
    signal.signal(signal.SIGTERM, _terminated)
    from fylgja_core.server.__main__ import main as serve  # only now: its import is the two seconds

    return serve()
