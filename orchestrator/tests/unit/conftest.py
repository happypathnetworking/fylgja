"""Tier 1's Infrahub: recorded answers served through the SDK's own transport hook
(`sync_requester`), so the adapter's client runs whole, the SDK included, with no server."""

import copy
import json
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

DATA = Path(__file__).resolve().parents[1] / "data"
TOKEN = "sentinel-token"
ADDRESS = "http://infrahub.test"


class FakeInfrahub:
    """One Infrahub holding branches, each answering the recorded schema document (which a
    test may change) and whatever GraphQL answer a test sets: one fixed answer, or, for an
    operation named in `operations` (a branch's) or `default_operations` (the default
    branch's unnamed `/graphql`), what its function answers for the request (a body, or a
    status and a body). The object store answers `objects`, by storage id, each a status and
    bytes. Every request is kept, its path, its query, its headers and its GraphQL operation
    and variables."""

    def __init__(self):
        self.schema = json.loads((DATA / "schema" / "schema-26336e9.json").read_text())
        self.default_schema = None
        self.branches = {"main", "fylgja-fixture"}
        self.graphql = {"data": {}}
        self.graphql_status = 200
        self.schema_status = None
        self.schema_body = None
        self.operations: dict = {}
        self.default_operations: dict = {}
        self.objects: dict[str, tuple[int, bytes]] = {}
        self.requests: list[dict] = []

    def count(self, path: str) -> int:
        return sum(1 for r in self.requests if r["path"] == path)

    def served(self, operation: str) -> list[dict]:
        """Every GraphQL request of an operation, in order."""
        return [r for r in self.requests if r.get("operation") == operation]

    def _operation(self, table: dict, request: dict, branch: str):
        handler = table.get(request["operation"])
        if handler is None:
            return None
        answer = handler(request["variables"], request["query_text"], branch, request["query"])
        return answer if isinstance(answer, tuple) else (200, answer)

    def __call__(self, url, method, headers, timeout, payload=None):
        parts = urlsplit(url)
        query = parse_qs(parts.query, keep_blank_values=True)
        body = payload if isinstance(payload, dict) else {}
        self.requests.append(
            {"url": url, "path": unquote(parts.path), "raw_path": parts.path, "query": query,
             "headers": dict(headers), "payload": copy.deepcopy(payload),
             "operation": body.get("operationName"), "variables": copy.deepcopy(body.get("variables") or {}),
             "query_text": body.get("query", "")}
        )
        seen = self.requests[-1]
        request = httpx.Request(method.value, url)

        def answer(status, body):
            return httpx.Response(status, content=json.dumps(body).encode(), request=request)

        if headers.get("X-INFRAHUB-KEY") != TOKEN:
            return answer(401, {"errors": [{"message": "Invalid token", "extensions": {"code": 401}}]})
        if parts.path == "/api/schema" and "branch" not in query and self.default_schema is not None:
            return answer(200, self.default_schema)
        if parts.path == "/api/schema":
            branch = query.get("branch", ["main"])[0]
            if self.schema_status is not None:
                return httpx.Response(self.schema_status, content=self.schema_body, request=request)
            if branch not in self.branches:
                return answer(400, {"data": None, "errors": [{"message": f"Branch: {branch} not found.",
                                                              "extensions": {"code": 400}}]})
            return answer(200, self.schema)
        if parts.path.startswith("/api/storage/object/"):
            storage_id = unquote(parts.path.removeprefix("/api/storage/object/"))
            if storage_id not in self.objects:
                return answer(404, {"errors": [{"message": f"Unable to find the node {storage_id} / "
                                                           "StorageObject in the database."}]})
            status, content = self.objects[storage_id]
            return httpx.Response(status, content=content, request=request)
        if parts.path == "/graphql":
            answered = self._operation(self.default_operations, seen, "")
            if answered is None:
                return answer(418, {"errors": [{"message": f"unknown operation {seen['operation']}"}]})
            return answer(*answered)
        if parts.path.startswith("/graphql/"):
            branch = unquote(parts.path.removeprefix("/graphql/"))
            if branch not in self.branches:
                return answer(404, {"errors": [f"Branch: {branch} not found."]})
            answered = self._operation(self.operations, seen, branch)
            if answered is not None:
                return answer(*answered)
            return answer(self.graphql_status, self.graphql)
        return answer(404, {"errors": ["no route"]})


@pytest.fixture
def infrahub():
    return FakeInfrahub()


@pytest.fixture
def client_for(infrahub):
    """A client of the fake, for a branch and an `at`, with the fake's token or another."""
    from fylgja_orchestrator.adapters.infrahub.client import Client, Config

    def make(branch="fylgja-fixture", at="", token=TOKEN):
        return Client(Config(address=ADDRESS, token=token, branch=branch, at=at), requester=infrahub)

    return make
