# Compiler facts

One file per fixture, `<name>.facts.json`. Each holds what the frozen Go core's compiler
produced for the network in `testdata/blueprint/<name>.json`, reduced to facts that hold whatever the
bundle's format is:
- the nodes, with their platform package and config digest;
- the links, in production interface names;
- the interface mapping;
- probe hosts;
- omissions and lossy rows;
- counts.

The new core's compiler is correct on a fixture when its bundle states the same facts
([D-001](../../design/decisions.md#d-001), [D-002](../../design/decisions.md#d-002)). Byte
equality with the old bundles is not the target, since the formats changed.

The facts were exported once, at the repository cut, from the Go compiler's golden bundles,
which stay in the archived repository.

`testdata/blueprint/three-node-unmanaged.json` is `three-node` with `n2`'s configuration removed
([D-048](../../design/decisions.md#d-048)). The compile, push and API tests use it. It has no Go
facts, since the Go compiler had no such case.
