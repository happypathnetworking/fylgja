# The schema's entities

Fylgja reads intent only through its generics, `schema/fylgja-generics.yaml`, never through
a concrete kind. The diagram shows each generic with every attribute it declares, each of
which the read queries, typed by its Infrahub kind, and the relationships between them with
their cardinalities; beside them stand Fylgja's two concrete kinds, the contract singleton
and the stage (`schema/fylgja-stage.yaml`) with the proposed change it belongs to, and
Infrahub's own address generic, which an interface's `addresses` point at. Names are as the
YAML spells them.

The reference schema, `schema/reference.yaml`, implements the four generics with four
concrete kinds for an install with no model of its own: `NetworkPlatform`,
`NetworkDevice`, `NetworkInterface` and `NetworkLink`. `NetworkDevice` also inherits
Infrahub's `CoreArtifactTarget`, which contract `0.2` demands of every kind implementing
`FylgjaDevice`, so that Infrahub can render the device's configuration artifact and the
read can find it. An organisation with a model of its own adds `inherit_from` to its own
kinds instead. Nobody implements `FylgjaContract` or `FylgjaStage`: the contract holds the
version the read checks first, and a stage, branch-agnostic and loaded on the default
branch, marks a moment of Infrahub's own `CoreProposedChange`, whose `fylgja_stages` the
same file adds, by a label unique within it ([D-045](../decisions.md#d-045)); the
proposed change's source branch is the branch a mark's read is on.

```mermaid
erDiagram
    FylgjaPlatform ||--o{ FylgjaDevice : "platform"
    FylgjaDevice ||--o{ FylgjaInterface : "interfaces / device"
    FylgjaInterface |o--o{ FylgjaInterface : "parent"
    FylgjaLink |o--|{ FylgjaInterface : "endpoints (exactly two) / link"
    FylgjaInterface }o--o{ BuiltinIPAddress : "addresses"
    CoreProposedChange ||--o{ FylgjaStage : "fylgja_stages / proposed_change"

    FylgjaPlatform {
        Text vendor "required"
        Text nos "required: srlinux, eos, ..."
        Text version "optional"
        Text model "optional"
    }
    FylgjaDevice {
        Text name UK "required; the containerlab node name"
        Text role "optional"
        Text site "optional"
    }
    FylgjaInterface {
        Text name "required; production naming"
        Dropdown iftype "required: physical, loopback, svi, subinterface"
        Boolean mgmt_only "default false; never cabled"
        Boolean enabled "default true"
    }
    BuiltinIPAddress {
        IPHost address "Infrahub's own generic"
    }
    FylgjaContract {
        Text version "required; singleton"
    }
    FylgjaStage {
        Text label UK "required; no '/' and no whitespace; unique within its proposed change"
        DateTime as_of "optional; the reference's at, else the label's write stamp"
        Text description "optional"
    }
    CoreProposedChange {
        Text source_branch "Infrahub's own kind; the stage's branch"
    }
```
