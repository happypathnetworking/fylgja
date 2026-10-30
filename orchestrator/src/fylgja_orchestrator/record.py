"""The orchestrator's record and store (data-model §8; R-09; FR-021): files, no database.

Under `FYLGJA_ORCHESTRATOR_ROOT` (default `local/orchestrator`):

- `snapshots/<id>.json`, every snapshot the orchestrator takes, filed once by `os.link` from
  a temporary sibling, as the core's `snapshot.DirStore` files them: an entry is whole or
  absent, never overwritten, and a second take of the same snapshot writes nothing;
- `twin.json`, the one record of the twin the orchestrator last drove: the stage it created
  or stepped the twin to, that stage's snapshot id and the flow run that did it, written
  whole by the create, step and rehearse flows.

The record is read beside the core's `twin.show` and trusted only while the show's
`record.snapshot_id` is the record's: the core's `twin.json` `12` names no stage, so this is
what the stage list's twin row, the step's default target, `stage.twin.moved` and the
reclaim read. Distrusted, the list files `record.twin.stale` and marks no twin row, and a
step given no stage is refused `step.target.required`. The reclaim reads the record's flow
run from the platform (`GET /api/flow_runs/{id}`) to tell a twin its own dead rehearsal
left from the operator's.
"""

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .adapters.infrahub import snapshot as snapshots
from .adapters.infrahub import stages as stage_rules
from .core import CoreFailure
from .documents.findings import INFO, REJECTION, Document, Finding

ENV_ROOT = "FYLGJA_ORCHESTRATOR_ROOT"
DEFAULT_ROOT = "local/orchestrator"

RECORD_VERSION = "1"
RECORD_FILE = "twin.json"
SNAPSHOTS_DIR = "snapshots"

FLOW_CREATE = "twin-create"
FLOW_STEP = "twin-step"
FLOW_REHEARSE = "twin-rehearse"
FLOWS = (FLOW_CREATE, FLOW_STEP, FLOW_REHEARSE)
"""The flows that write the record (R-09)."""

TERMINAL_DEAD = ("FAILED", "CRASHED", "CANCELLED")
"""A flow run's states that leave its twin to be reclaimed: it ended without its destroy's
word. `COMPLETED` is not among them, since a rehearsal that completed destroyed its twin, and
a twin standing at its snapshot after it is another's."""

ENV_PLATFORM = "PREFECT_API_URL"
ENV_PLATFORM_AUTH = "PREFECT_API_AUTH_STRING"
PLATFORM_TIMEOUT_S = 10.0

RULE_RECORD_TWIN_STALE = "record.twin.stale"
RULE_STEP_TARGET_REQUIRED = "step.target.required"
RULE_PLATFORM_UNREACHABLE = "platform.unreachable"
STEP_START = "start"


class RecordError(ValueError):
    """A store entry or a record this module will not take: a snapshot entry whose body hashes
    to another id, or a twin.json that is no record of this version. Its words name the path."""


def root(environ: Mapping[str, str] | None = None) -> Path:
    """The orchestrator's state root: FYLGJA_ORCHESTRATOR_ROOT, else local/orchestrator."""
    environ = os.environ if environ is None else environ
    return Path(environ.get(ENV_ROOT) or DEFAULT_ROOT)


# The record.


@dataclass(frozen=True)
class StageRef:
    """The stage the twin was created or stepped to: its proposed change's branch and its
    label, and the (branch, at) it resolved to; `branch` is that resolution's."""

    branch: str
    label: str
    at: str


@dataclass(frozen=True)
class ChangeRef:
    """The proposed change the stage is of."""

    id: str
    branch: str


@dataclass(frozen=True)
class Record:
    """The orchestrator's twin.json, version 1."""

    stage: StageRef
    proposed_change: ChangeRef
    snapshot_id: str
    flow_run_id: str
    flow: str
    written_at: str

    @property
    def ref(self) -> str:
        """The stage as `<branch>/<label>`, the proposed change's branch."""
        return f"{self.proposed_change.branch}/{self.stage.label}"

    def to_dict(self) -> dict:
        """The record as twin.json holds it, in data-model §8's order."""
        return {
            "record_version": RECORD_VERSION,
            "stage": {"branch": self.stage.branch, "label": self.stage.label, "at": self.stage.at},
            "proposed_change": {"id": self.proposed_change.id, "branch": self.proposed_change.branch},
            "snapshot_id": self.snapshot_id,
            "flow_run_id": self.flow_run_id,
            "flow": self.flow,
            "written_at": self.written_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Record":
        stage, change = d["stage"], d["proposed_change"]
        return cls(StageRef(stage["branch"], stage["label"], stage["at"]),
                   ChangeRef(change["id"], change["branch"]),
                   d["snapshot_id"], d["flow_run_id"], d["flow"], d["written_at"])


def new_record(stage: StageRef, proposed_change: ChangeRef, snapshot_id: str, flow_run_id: str, flow: str,
               now: datetime | None = None) -> Record:
    """A record written now, held to its shape: a flow of the three, a snapshot id."""
    if flow not in FLOWS:
        raise ValueError(f"{flow!r} writes no record: the record is {', '.join(FLOWS)}'s")
    if not snapshots.is_id(snapshot_id):
        raise ValueError(f"{snapshot_id!r} is not a snapshot id: 64 lowercase hex characters")
    now = (now or datetime.now(UTC)).astimezone(UTC)
    return Record(stage, proposed_change, snapshot_id, flow_run_id, flow,
                  now.strftime("%Y-%m-%dT%H:%M:%S.%fZ"))


# The store.


class Store:
    """The orchestrator's directory: its snapshots by id and its one record."""

    def __init__(self, path: Path | str):
        self.root = Path(path)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Store":
        return cls(root(environ))

    @property
    def snapshots(self) -> Path:
        return self.root / SNAPSHOTS_DIR

    @property
    def record_path(self) -> Path:
        return self.root / RECORD_FILE

    def path(self, snapshot_id: str) -> Path:
        """The entry for an id. Anything but an id is never joined to the directory."""
        if not snapshots.is_id(snapshot_id):
            raise RecordError(f"{snapshot_id!r} is not a snapshot id: 64 lowercase hex characters")
        return self.snapshots / f"{snapshot_id}.json"

    def _entry(self, snapshot_id: str) -> dict | None:
        """The entry for an id, verified to hash to it; None when absent."""
        path = self.path(snapshot_id)
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return None
        try:
            snap = snapshots.unmarshal(data)
        except snapshots.SnapshotError as e:
            raise RecordError(f"{path} is not a snapshot: {e}") from None
        if snap["snapshot_id"] != snapshot_id:
            raise RecordError(f"{path} hashes to {snap['snapshot_id']}, not {snapshot_id}")
        return snap

    def put(self, snapshot: dict) -> tuple[str, bool]:
        """Files a snapshot under the id its body hashes to and returns the id and whether this
        take wrote it. An entry already there is verified and kept, never rewritten, so the
        first take's observed_at is the one kept; a corrupt one is refused, not replaced. An
        absent one is written to a temporary sibling and linked into place: a link, not a
        rename, since a rename replaces a file a concurrent take linked first."""
        data = snapshots.marshal(snapshot)
        snapshot_id = snapshot["snapshot_id"]
        if self._entry(snapshot_id) is not None:
            return snapshot_id, False
        self.snapshots.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".fylgja-snapshot-", dir=self.snapshots)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o644)
            try:
                os.link(tmp, self.path(snapshot_id))
            except FileExistsError:
                if self._entry(snapshot_id) is not None:
                    return snapshot_id, False
                raise
        finally:
            Path(tmp).unlink(missing_ok=True)
        return snapshot_id, True

    def has(self, snapshot_id: str) -> bool:
        """Whether an entry for the id exists and hashes to it: a corrupt entry is none."""
        try:
            return self._entry(snapshot_id) is not None
        except RecordError:
            return False

    def fetch(self, snapshot_id: str) -> dict:
        """The entry for an id, verified; FileNotFoundError when absent."""
        snap = self._entry(snapshot_id)
        if snap is None:
            raise FileNotFoundError(f"snapshot {snapshot_id} is not in the store at {self.snapshots}")
        return snap

    def read_record(self) -> Record | None:
        """The record, None when there is none; a twin.json that is no record of version 1 is
        a RecordError naming it."""
        path = self.record_path
        try:
            d = json.loads(path.read_bytes())
        except FileNotFoundError:
            return None
        except ValueError as e:
            raise RecordError(f"{path} is not a record: {e}") from None
        if not isinstance(d, dict) or d.get("record_version") != RECORD_VERSION:
            version = d.get("record_version") if isinstance(d, dict) else None
            raise RecordError(f"{path} declares record_version {version!r}; this build reads {RECORD_VERSION!r}")
        try:
            return Record.from_dict(d)
        except (KeyError, TypeError) as e:
            raise RecordError(f"{path} is not a record: it lacks {e}") from None

    def write_record(self, record: Record) -> None:
        """Writes the record whole: a temporary sibling renamed into place, so twin.json is
        the last record or the one before it, never half of one."""
        self.root.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(record.to_dict(), indent=2) + "\n").encode()
        fd, tmp = tempfile.mkstemp(prefix=".fylgja-record-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.chmod(tmp, 0o644)
            os.replace(tmp, self.record_path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def clear_record(self) -> None:
        """Removes the record: the twin the orchestrator last drove names no stage (a create
        from a branch), so no record describes it. Nothing when there is none."""
        self.record_path.unlink(missing_ok=True)


# The trust.


def shown_snapshot(show) -> str | None:
    """The snapshot twin.show's record names: `show.record.snapshot_id` of its document (or
    of the show block itself), None when no twin is recorded or the record names none."""
    if isinstance(show, Document):
        show = show.blocks.get("show")
    if not isinstance(show, dict):
        return None
    record = show.get("record")
    if not isinstance(record, dict):
        return None
    return record.get("snapshot_id") or None


def trusted(record: Record | None, show) -> bool:
    """Whether the record is trusted: twin.show's record names the record's snapshot."""
    return record is not None and shown_snapshot(show) == record.snapshot_id


def _distrust(record: Record, show) -> str:
    other = shown_snapshot(show)
    names = f"snapshot {other}" if other else "no snapshot, since no twin is recorded"
    return (f"the orchestrator's record names snapshot {record.snapshot_id} from stage {record.ref}, and twin show's "
            f"record names {names}")


def stale(store: Store, record: Record | None, show) -> Finding | None:
    """record.twin.stale (info), naming the record, when there is a record and it is not
    trusted: the stage list then marks no twin row and says why. None otherwise."""
    if record is None or trusted(record, show):
        return None
    return Finding(INFO, RULE_RECORD_TWIN_STALE, str(store.record_path),
                   f"{_distrust(record, show)}; the record is not trusted, so no stage is marked as the twin's")


def target_required(record: Record | None, show) -> Finding | None:
    """step.target.required (error, exit 1) at step start for a step given no --stage while
    the record is not trusted: there is no stage to take the next of. None when trusted."""
    if trusted(record, show):
        return None
    if record is None:
        why = "the orchestrator holds no record of a twin"
    else:
        why = f"{_distrust(record, show)}, so the record is not trusted"
    return Finding(REJECTION, RULE_STEP_TARGET_REQUIRED, "--stage",
                   f"{why}, and there is no stage to take the next of; give --stage <branch>/<label>", STEP_START)


def shown_record(show) -> dict:
    """twin.show's record block, {} when no twin is recorded."""
    if isinstance(show, Document):
        show = show.blocks.get("show")
    record = show.get("record") if isinstance(show, dict) else None
    return record if isinstance(record, dict) else {}


def view(record: Record, show, ch: "stage_rules.Change | None" = None) -> "stage_rules.RecordView":
    """The record as the stages' rules read it (`stages.RecordView`): its stage and proposed
    change, the branch and at it resolved to, the scope and state twin.show's record names.
    The record carries no at's source: a derived stage's follows from its label, and a
    mark's is the mark's as `ch`, the record's proposed change as the flow found it, lists
    it, "" for a mark since deleted. The core's record names no stage, so a diverged twin's
    target is not known."""
    shown = shown_record(show)
    label = record.stage.label
    if label == stage_rules.LABEL_BRANCH_POINT:
        at_source = stage_rules.AT_BRANCH_POINT
    elif label == stage_rules.LABEL_HEAD:
        at_source = stage_rules.AT_HEAD
    else:
        at_source = ""
        if ch is not None and ch.proposed_change.id == record.proposed_change.id:
            st = ch.first(label)
            at_source = st.at_source if st is not None else ""
    return stage_rules.RecordView(
        stage_rules.RecordChange(record.proposed_change.id, record.proposed_change.branch), label,
        record.stage.branch, record.stage.at, at_source, shown.get("scope") or "",
        shown.get("state") or "ready")


# The reclaim.


def reclaimable(record: Record | None, show, flow_run: dict | None) -> bool:
    """Whether the twin standing is the record's own dead rehearsal's, to be destroyed with
    rehearsal.twin.reclaimed: the record's flow is twin-rehearse, its flow run as the
    platform answers it (`flow_run`, None for a 404 after the platform's retention) is in a
    dead terminal state, and twin.show names the record's snapshot. Anything else is the
    host held (host.twin.present), never reclaimed."""
    if record is None or record.flow != FLOW_REHEARSE or not trusted(record, show):
        return False
    if flow_run is None:
        return True
    state = flow_run.get("state") or {}
    return state.get("type") in TERMINAL_DEAD


def read_flow_run(flow_run_id: str, environ: Mapping[str, str] | None = None,
                  transport: httpx.BaseTransport | None = None) -> dict | None:
    """The platform's flow run (`GET /api/flow_runs/{id}` at PREFECT_API_URL, under
    PREFECT_API_AUTH_STRING's basic auth when set), None when it answers 404. A platform that
    does not answer, or answers otherwise, is platform.unreachable; no sentence names the
    credential."""
    environ = os.environ if environ is None else environ
    base, auth = platform_of(environ)
    if not base:
        raise CoreFailure(RULE_PLATFORM_UNREACHABLE, ENV_PLATFORM,
                          f"{ENV_PLATFORM} is not set, so the orchestrator's platform cannot be asked for flow run "
                          f"{flow_run_id}")
    try:
        with httpx.Client(transport=transport, trust_env=False, timeout=PLATFORM_TIMEOUT_S) as http:
            resp = http.get(f"{base}/flow_runs/{flow_run_id}", auth=auth)
    except httpx.TransportError as e:
        raise CoreFailure(RULE_PLATFORM_UNREACHABLE, base,
                          f"the orchestrator's platform at {base} did not answer: {e or type(e).__name__}") from None
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise CoreFailure(RULE_PLATFORM_UNREACHABLE, base, f"the orchestrator's platform at {base} answered "
                          f"{resp.status_code} {resp.reason_phrase} for flow run {flow_run_id}".rstrip())
    try:
        return resp.json()
    except ValueError:
        raise CoreFailure(RULE_PLATFORM_UNREACHABLE, base, f"the orchestrator's platform at {base} answered flow "
                          f"run {flow_run_id} with no JSON") from None


def platform_of(environ: Mapping[str, str]) -> tuple[str, tuple[str, str] | None]:
    """The platform's API address, PREFECT_API_URL without a trailing slash ("" when unset),
    and PREFECT_API_AUTH_STRING's basic auth, None when unset."""
    base = (environ.get(ENV_PLATFORM) or "").rstrip("/")
    auth = None
    if creds := environ.get(ENV_PLATFORM_AUTH):
        user, _, password = creds.partition(":")
        auth = (user, password)
    return base, auth


def check_platform(environ: Mapping[str, str], transport: httpx.BaseTransport | None = None) -> None:
    """Whether the platform PREFECT_API_URL names answers this process's credential, before a
    flow is run on it: `GET /version` under PREFECT_API_AUTH_STRING's basic auth, which the
    server's authentication guards and `/health` does not (research §1.2). Nothing when it
    answers 200 or when PREFECT_API_URL is unset (Prefect's ephemeral server then); else
    platform.unreachable naming the address, never the credential."""
    base, auth = platform_of(environ)
    if not base:
        return
    try:
        with httpx.Client(transport=transport, trust_env=False, timeout=PLATFORM_TIMEOUT_S) as http:
            resp = http.get(f"{base}/version", auth=auth)
    except httpx.TransportError as e:
        raise CoreFailure(RULE_PLATFORM_UNREACHABLE, base,
                          f"the orchestrator's platform at {base} did not answer: {e or type(e).__name__}; "
                          f"make prefect-server starts it") from None
    if resp.status_code != 200:
        why = f"{resp.status_code} {resp.reason_phrase}".rstrip()
        if resp.status_code == 401:
            why += f"; {ENV_PLATFORM_AUTH} must be the credential the platform was started with"
        raise CoreFailure(RULE_PLATFORM_UNREACHABLE, base, f"the orchestrator's platform at {base} answered {why}")
