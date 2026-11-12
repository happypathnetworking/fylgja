"""The example's rehearsal library (D-085, D-086): a change rehearsed on one twin through the core's client.

It imports the standard library, the core's client and model, and itself: no source, no workflow engine and nothing
of the core's server. A source answers the seam in `source`; a change's stages are planned by `plan`, in `planning`,
and rehearsed on one twin by `rehearse`, in `rehearsing`; a rehearsal's twin is named by `names`; the example's two
documents are validated and their findings made by `documents`, and its rules are `rules`; a rehearsal's report is
rendered from its document alone by `report`. The commands take one twin to a stage by `create` and `step`, and list
a change's stages by `stage_list`, in `commands`, each twin's stage kept in its `record`.
"""

from fylgja_orchestrator.rehearsal import commands, documents, planning, record, report, rules
from fylgja_orchestrator.rehearsal.commands import Listed, Made, create, stage_list, step
from fylgja_orchestrator.rehearsal.names import twin_name, twin_prefix
from fylgja_orchestrator.rehearsal.planning import plan, stamp
from fylgja_orchestrator.rehearsal.rehearsing import Limits, rehearse
from fylgja_orchestrator.rehearsal.report import Report, headline, render
from fylgja_orchestrator.rehearsal.source import Change, ChangeSource, Read, Stage

__all__ = [
    "Change",
    "ChangeSource",
    "Limits",
    "Listed",
    "Made",
    "Read",
    "Report",
    "Stage",
    "commands",
    "create",
    "documents",
    "headline",
    "plan",
    "planning",
    "record",
    "rehearse",
    "render",
    "report",
    "rules",
    "stage_list",
    "stamp",
    "step",
    "twin_name",
    "twin_prefix",
]
