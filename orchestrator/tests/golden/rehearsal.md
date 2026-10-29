## Fylgja rehearsed proposed change "fylgja-test-golden-41263" on fylgja-test-golden-41263, scope tag:fylgja

Run `fylgja-rehearse 01a188df-b883-70f8-8999-bc18b484dc1f`, stages resolved at 2026-10-29T18:15:11Z. Status **nonconforming**. 74.5s of the 2580s deadline (ceiling 3600s).

| stage | at | snapshot | bundle | step | wait | verify | loss | new verification failures | verdict |
|---|---|---|---|---|---|---|---|---|---|
| fylgja-test-golden-41263/branch-point | 2026-10-29T18:09:04.039194Z | — | — | | | | — | | refused (scope.empty) |
| fylgja-test-golden-41263/seeded | 2026-10-29T18:11:38.471611+00:00 | 78232019… | ce705cdb… | created | settled after 4.4s | 15 held, 0 failed, 0 skipped | — | — | baseline |
| fylgja-test-golden-41263/third-link | 2026-10-29T18:11:50.425111+00:00 | 5cbbe593… | 61665b99… | stepped | settled after 5.5s | 19 held, 0 failed, 0 skipped | — | none | passed |
| fylgja-test-golden-41263/bad-port | 2026-10-29T18:12:11.745240+00:00 | cc81016f… | 0b8af687… | diverged at push | settled after 5.5s | 19 held, 0 failed, 0 skipped | — | none | failed |
| fylgja-test-golden-41263/head | 2026-10-29T18:12:10.636975+00:00 | 8b986a10… | 4215a6c2… | | | | — | | not reached |

```mermaid
flowchart TD
  s0["fylgja-test-golden-41263/branch-point<br/>refused"]
  s1["fylgja-test-golden-41263/seeded<br/>baseline"]
  s2["fylgja-test-golden-41263/third-link<br/>passed"]
  s3["fylgja-test-golden-41263/bad-port<br/>failed"]
  s4["fylgja-test-golden-41263/head<br/>not reached"]
  s0 -. "not computed" .-> s1
  s1 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s2
  s2 -- "~n1 (mapping); artifacts n1" --> s3
  s3 -- "unchanged" --> s4
  classDef failed stroke:#d32f2f,stroke-width:3px
  class s3 failed
```

**Findings**:

- `push.refused` n1
- `rehearsal.stage.failed` fylgja-test-golden-41263/bad-port
- `scope.empty` tag:fylgja
- `step.diverged` 01a188e0-a0b7-78e2-9cb0-2c7bf655c46f

**Stages** (Infrahub's view does not show them):

- `fylgja-test-golden-41263/branch-point` main at 2026-10-29T18:09:04.039194Z (branch point)
- `fylgja-test-golden-41263/seeded` fylgja-test-golden-41263 at 2026-10-29T18:11:38.471611+00:00 (written) "seeded"
- `fylgja-test-golden-41263/third-link` fylgja-test-golden-41263 at 2026-10-29T18:11:50.425111+00:00 (written) "third link"
- `fylgja-test-golden-41263/bad-port` fylgja-test-golden-41263 at 2026-10-29T18:12:11.745240+00:00 (written) "a port SR Linux refuses"
- `fylgja-test-golden-41263/head` fylgja-test-golden-41263 at 2026-10-29T18:12:10.636975+00:00 (head)

**Warnings**:

- `artifact.interface.unrepresented` n1:ethernet-1/99 (stages bad-port, head)

**Baseline findings** (reported, failing nothing): none

**Reproduce by hand**:

```
fylgja twin create --stage fylgja-test-golden-41263/seeded --scope tag:fylgja
fylgja twin step --stage fylgja-test-golden-41263/third-link --allow-restart
fylgja twin step --stage fylgja-test-golden-41263/bad-port --allow-restart
fylgja twin verify
fylgja twin destroy
```

*To fit what Infrahub keeps of a comment (4092 bytes), each finding is named by its identifier and object alone, and the table each step by its outcome and its new verification failures by the first few; fylgja-twin's message is the whole report as text.*

*Fidelity is asserted, not measured: the twin's containers forward in software and keep their own timing; a loss figure is the container's, never a hardware forwarder's.*
