"""`docs/api.md` holds to API 1's OpenAPI document (formats/api-1.openapi.yaml): its `Method` table lists the
document's operations, its `Parameter` and `Header` tables the document's query parameters and headers, each
compared as sets, both ways; each `curl` example is a request the document declares and the server would accept, its
body and its answer valid under the document's schemas; and each status the page names is one the document gives."""

from __future__ import annotations

import json
import re
import shlex
from typing import Any

import httpx
from fake_api import ADDRESS, check_component, check_request, check_response, openapi
from pages import ROOT, blocks, rows, section, text, ticked

PAGE = "docs/api.md"
METHODS = ("get", "put", "post", "delete")


def _operations() -> set[tuple[str, str, str]]:
    """Each (METHOD, path, operationId) of the document."""
    return {
        (method.upper(), path, op["operationId"])
        for path, item in openapi()["paths"].items()
        for method, op in item.items()
        if method in METHODS
    }


def _resolved(node: dict[str, Any], kind: str) -> dict[str, Any]:
    """A node of `components/<kind>` or the node itself, a `$ref` followed."""
    if "$ref" in node:
        found: dict[str, Any] = openapi()["components"][kind][node["$ref"].rsplit("/", 1)[1]]
        return found
    return node


def _declared() -> tuple[set[str], set[str]]:
    """The query parameters the document declares, and its headers: every request header parameter and every
    response header."""
    queries: set[str] = set()
    headers: set[str] = set()
    for item in openapi()["paths"].values():
        for node in item.get("parameters", []):
            queries |= {p["name"] for p in [_resolved(node, "parameters")] if p["in"] == "query"}
        for method, op in item.items():
            if method not in METHODS:
                continue
            for node in op.get("parameters", []):
                p = _resolved(node, "parameters")
                (queries if p["in"] == "query" else headers if p["in"] == "header" else set()).add(p["name"])
            for response in op["responses"].values():
                headers |= set(_resolved(response, "responses").get("headers", {}))
    return queries, headers


def test_the_route_table_is_the_documents_operations() -> None:
    found = rows(section(text(PAGE), "## Routes"), "Method")
    assert found, "the parse is blind"
    listed = [(row[0].strip("`"), ticked(row[1])[0], ticked(row[2])[0]) for row in found]
    assert len(listed) == len(set(listed)), "an operation has one row"
    assert set(listed) == _operations()
    assert len(listed) == 18, "eighteen operations"


def test_the_parameters_and_headers_named_are_the_documents() -> None:
    page = text(PAGE)
    parameters = rows(section(page, "## Parameters"), "Parameter")
    headers = rows(section(page, "## Headers"), "Header")
    assert parameters and headers, "the parse is blind"
    queries, declared = _declared()
    assert queries == {"watch", "since_revision", "dry_run", "twin", "after"}, "the document's own parse"
    assert declared >= {"If-Match", "If-None-Match", "ETag", "Location"}, "the document's own parse"
    assert [ticked(row[0])[0] for row in parameters] == sorted(queries)
    assert [ticked(row[0])[0] for row in headers] == sorted(declared)


class Example:
    """A `curl` command of the page, the request it makes and the block that follows it."""

    def __init__(self, command: str, request: httpx.Request, info: str, lines: list[str], status_line: str) -> None:
        self.command, self.request, self.info, self.lines, self.status_line = command, request, info, lines, status_line


def _status_lines() -> list[str]:
    """For each `json` block of the page, in order, the nearest non-blank line before its fence."""
    lines = text(PAGE).splitlines()
    return [next(lines[j] for j in range(k - 1, -1, -1) if lines[j].strip())
            for k, line in enumerate(lines) if line.startswith("```json")]


def _examples() -> list[Example]:
    """Each `sh` block of one `curl` command (a backslash continues a line), with the block after it. The request is
    the method (`-X`, else `POST` with `--data`, else `GET`), the URL, the `-H` headers and the body (`--data`, or
    the file an `@` names, from the repository's root) the command gives."""
    found = []
    shown = blocks(text(PAGE))
    status_lines = _status_lines()
    for k, (info, lines) in enumerate(shown):
        command = " ".join(line.rstrip("\\").strip() for line in lines)
        if info != "sh" or not command.startswith("curl "):
            continue
        words = shlex.split(command)[1:]
        method, url, data, headers = None, None, None, {}
        i = 0
        while i < len(words):
            word = words[i]
            if word == "-X":
                method, i = words[i + 1], i + 2
            elif word in ("-H", "--header"):
                name, _, value = words[i + 1].partition(": ")
                headers[name], i = value, i + 2
            elif word in ("--data", "-d"):
                data, i = words[i + 1], i + 2
            elif word.startswith("-"):
                i += 1
            else:
                url, i = word, i + 1
        assert url is not None and url.startswith(f"http://{ADDRESS}/"), command
        content = b""
        if data is not None:
            content = (ROOT / data[1:]).read_bytes() if data.startswith("@") else data.encode()
        request = httpx.Request(method or ("POST" if data is not None else "GET"), url, headers=headers,
                                content=content)
        assert k + 1 < len(shown), command
        after_info, after_lines = shown[k + 1]
        ordinal = sum(1 for info_, _ in shown[:k + 1] if info_ == "json")
        status_line = status_lines[ordinal] if after_info == "json" else ""
        found.append(Example(command, request, after_info, after_lines, status_line))
    return found


def _answer(template: str, method: str, status: int, body: Any) -> httpx.Response:
    """What the server answers with `body`: the media type the document gives the status, first."""
    declared = openapi()["paths"][template][method]["responses"][str(status)]
    declared = _resolved(declared, "responses")
    media = next(iter(declared["content"]))
    return httpx.Response(status, headers={"content-type": media}, content=json.dumps(body).encode())


def test_each_example_is_valid_under_the_document() -> None:
    examples = _examples()
    assert len(examples) >= 4, "the parse is blind"
    answers: list[int] = []
    for example in examples:
        template, method = check_request(example.request)
        operation = openapi()["paths"][template][method]
        sent = example.request.headers
        if operation.get("security") != []:
            assert sent.get("authorization") == "Bearer $FYLGJA_API_TOKEN", example.command
        assert not [v for v in sent.values() if "Bearer" in v and v != "Bearer $FYLGJA_API_TOKEN"], example.command
        if example.info == "json":
            named = re.findall(r"\b[1-5]\d\d\b", example.status_line)
            status = int(named[0]) if named else next(int(s) for s in operation["responses"] if s.startswith("2"))
            check_response(template, method, _answer(template, method, status, json.loads("\n".join(example.lines))))
            answers.append(status)
        else:
            assert example.info == "text", example.command
            component = "Event" if template.endswith("/events") else "WatchEvent"
            data = [line[len("data: "):] for line in example.lines if line.startswith("data: ")]
            assert data, f"the parse is blind: {example.command}"
            for message in data:
                check_component(component, json.loads(message))
    assert len(answers) >= 4, "four answers at least"
    assert any(status >= 400 for status in answers), "one a problem document"


def test_each_status_the_page_names_is_the_documents() -> None:
    named = {int(n) for n in re.findall(r"`([1-5]\d\d)`", text(PAGE))}
    assert len(named) >= 8, "the parse is blind"
    given = {int(s) for item in openapi()["paths"].values() for op in item.values() if isinstance(op, dict)
             for s in op.get("responses", {})}
    assert named <= given, named - given
