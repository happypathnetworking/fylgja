"""A finding, in the core's one shape (`internal/findings`): the severity, the rule, the
object at fault and the message, and the step for a run's. The rule identifiers are
stable API, so every module that refuses something files it under the rule the core
would, worded as the core words it.

The document `findings 1` and its text form are T019's; this module holds what every
earlier module files a finding with, and Go's `%q`, which the words quote values by.
"""

from dataclasses import dataclass

REJECTION = "rejection"
"""Prevents any CTM, snapshot or bundle from being written."""

WARNING = "warning"
"""Reported, and prevents nothing."""

INFO = "info"
"""Something worth knowing, such as a recorded omission."""


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    object: str
    message: str
    step: str = ""


class Findings(list):
    """Findings gathered in one pass, never returned early: whoever fixes intent sees every
    problem at once."""

    def add(self, severity: str, rule: str, object: str, message: str) -> None:
        self.append(Finding(severity, rule, object, message))

    def reject(self, rule: str, object: str, message: str) -> None:
        self.add(REJECTION, rule, object, message)

    @property
    def rejected(self) -> bool:
        """Whether any finding is a rejection: what stops the command."""
        return any(f.severity == REJECTION for f in self)


_SHORT = {"\a": "\\a", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\v": "\\v"}


def quote(value: str) -> str:
    """value as Go's `%q` (strconv.Quote) writes it: double-quoted, the quote and the
    backslash escaped, a printable character kept, a control character by its short form or
    `\\x`, any other unprintable one by `\\u` or `\\U`. Python's `isprintable` is Go's
    `unicode.IsPrint`: letters, marks, numbers, punctuation and symbols, and the ASCII
    space. A lone surrogate, which Go never holds (it decodes one as U+FFFD), is written as
    U+FFFD."""
    out = ['"']
    for ch in value:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            ch = "\N{REPLACEMENT CHARACTER}"
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ch.isprintable():
            out.append(ch)
        elif ch in _SHORT:
            out.append(_SHORT[ch])
        elif ord(ch) < 0x80:
            out.append(f"\\x{ord(ch):02x}")
        elif ord(ch) <= 0xFFFF:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(f"\\U{ord(ch):08x}")
    out.append('"')
    return "".join(out)
