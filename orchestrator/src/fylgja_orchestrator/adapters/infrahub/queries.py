"""The eleven queries the adapter sends, carried over from `internal/intent/queries.graphql`
(R-07, R-21), each a whole document: its operation, then the fragment it spreads.

Every one is a query: Fylgja never writes to Infrahub. Their roots are the mapping's two
(`DcimDevice`, `InterfacePhysical`), Fylgja's two kinds (`FylgjaStage`, `FylgjaProbe`) or
five of Infrahub's own units (`CoreProposedChange`, `CoreArtifactValidator`, `Branch`,
`InfrahubEvent`, `CoreGraphQLQueryGroup`); their fragments are on `CoreArtifactTarget`,
which the library's `DcimDevice` inherits and conformance holds it to, and the scope's tag
is read by the `tags__name__value` filter alone. Each query's reason is beside it in
queries.graphql, which `tests/unit/test_queries.py` holds these to token by token while it
stands.

Two differences from the Go documents, both of form. genqlient added `__typename` to every
selection of an abstract type itself; here it is written where the adapter reads it: on
the event's node, which tells a `NodeMutatedEvent` from Infrahub's other events, and on a
connector and its ends, as queries.graphql already writes it. And genqlient's directives,
comments there, are gone: the adapter decodes plain JSON, so a connector, an end, an
interface or a transformation of a kind the SDL does not name decodes as any other (the
reason for each `bind` in Go).

`at` is never part of a document: it is the URL's, sent on every query of a read iff the
operator supplied one (the client's). Every query is paged by `limit` and `offset`, 100 at
a time, but `IntentEvents`, which Infrahub refuses above 50, `BranchPoint` and
`ArtifactValidations`, which answer one page.
"""

ARTIFACT_FIELDS = """
fragment ArtifactFields on CoreArtifactTarget {
  artifacts {
    edges { node {
      name        { value }
      status      { value }
      content_type { value }
      checksum    { value }
      storage_id  { value }
      definition  { node { artifact_name { value } } }
    } }
  }
}
"""

DEVICES = (
    """
query Devices($tag: String!, $limit: Int!, $offset: Int!) {
  DcimDevice(tags__name__value: $tag, limit: $limit, offset: $offset) {
    count
    edges {
      node {
        id
        name { value }
        platform {
          node {
            name { value }
            manufacturer {
              node {
                name { value }
              }
            }
          }
        }
        ...ArtifactFields
      }
    }
  }
}
"""
    + ARTIFACT_FIELDS
)

PORTS = """
query Ports($devices: [ID], $limit: Int!, $offset: Int!) {
  InterfacePhysical(device__ids: $devices, limit: $limit, offset: $offset) {
    count
    edges {
      node {
        id
        name   { value }
        role   { value }
        status { value }
        device { node { id } }
        connector {
          node {
            __typename
            id
            ... on DcimCable { label { value } }
            connected_endpoints {
              count
              edges { node {
                __typename
                id
                ... on InterfacePhysical {
                  name   { value }
                  device { node { id } }
                }
              } }
            }
          }
        }
      }
    }
  }
}
"""

PROPOSED_CHANGES = """
query ProposedChanges(
  $branch: String,
  $limit: Int!,
  $offset: Int!
) {
  CoreProposedChange(state__value: "open", source_branch__value: $branch, limit: $limit, offset: $offset) {
    count
    edges { node {
      id
      name               { value }
      source_branch      { value }
      destination_branch { value }
      state              { value }
      is_draft           { value }
      fylgja_stages { edges { node {
        id
        label       { value updated_at }
        as_of       { value updated_at }
        description { value }
      } } }
    } }
  }
}
"""
"""An empty `$branch` is left out of the variables, which Infrahub reads as no filter, so
every open proposed change is listed; `""` would match none (verified 2026-10-16)."""

ORPHAN_STAGES = """
query OrphanStages($limit: Int!, $offset: Int!) {
  FylgjaStage(proposed_change__isnull: true, limit: $limit, offset: $offset) {
    count
    edges { node {
      id
      label { value updated_at }
      as_of { value updated_at }
    } }
  }
}
"""

BRANCH_POINT = """
query BranchPoint($name: String!) {
  Branch(name: $name) {
    name
    branched_from
    created_at
  }
}
"""

ARTIFACT_VALIDATIONS = """
query ArtifactValidations($id: ID!) {
  CoreArtifactValidator(proposed_change__ids: [$id]) {
    edges { node {
      completed_at { value }
      definition   { node { name { value } } }
    } }
  }
}
"""

ARTIFACT_STAMPS = """
fragment ArtifactStamps on CoreArtifactTarget {
  artifacts { edges { node {
    name     { value }
    checksum { value updated_at }
    definition { node { transformation {
      node { query { node { id } } }
    } } }
  } } }
}
"""

INTENT_STAMPS = (
    """
query IntentStamps($tag: String!, $limit: Int!, $offset: Int!) {
  DcimDevice(tags__name__value: $tag, limit: $limit, offset: $offset) {
    count
    edges {
      node_metadata { updated_at updated_by { id } created_at }
      node {
        id
        name { value }
        platform {
          node_metadata { updated_at updated_by { id } created_at }
          node {
            id
            name { value }
            manufacturer {
              node_metadata { updated_at updated_by { id } created_at }
              node {
                id
                name { value }
              }
            }
          }
        }
        interfaces { edges {
          node_metadata { updated_at updated_by { id } created_at }
          node { id }
        } }
        ...ArtifactStamps
      }
    }
  }
}
"""
    + ARTIFACT_STAMPS
)

PORT_STAMPS = """
query PortStamps($devices: [ID], $limit: Int!, $offset: Int!) {
  InterfacePhysical(device__ids: $devices, connector__isnull: false, limit: $limit, offset: $offset) {
    count
    edges { node {
      device { node { id } }
      connector {
        node_metadata { updated_at updated_by { id } created_at }
        node { id }
      }
    } }
  }
}
"""

QUERY_GROUPS = """
query QueryGroups($queries: [ID], $limit: Int!, $offset: Int!) {
  CoreGraphQLQueryGroup(group_type__value: "internal", query__ids: $queries, limit: $limit, offset: $offset) {
    count
    edges { node_metadata {
      created_by { id }
    } }
  }
}
"""

INTENT_EVENTS = """
query IntentEvents($branch: String!, $since: DateTime!, $limit: Int!, $offset: Int!) {
  InfrahubEvent(branches: [$branch], since: $since, order: DESC, limit: $limit, offset: $offset) {
    count
    edges { node {
      __typename
      event
      occurred_at
      primary_node { id kind }
      ... on NodeMutatedEvent {
        attributes    { name }
        relationships { name peer { id } }
      }
    } }
  }
}
"""

PROBES = """
query Probes($limit: Int!, $offset: Int!) {
  FylgjaProbe(limit: $limit, offset: $offset) {
    count
    edges { node {
      name        { value }
      format      { value }
      a_device    { value }
      a_interface { value }
      a_address   { value }
      a_gateway   { value }
      b_device    { value }
      b_interface { value }
      b_address   { value }
      b_gateway   { value }
    } }
  }
}
"""

ALL = {
    "Devices": DEVICES,
    "Ports": PORTS,
    "ProposedChanges": PROPOSED_CHANGES,
    "OrphanStages": ORPHAN_STAGES,
    "BranchPoint": BRANCH_POINT,
    "ArtifactValidations": ARTIFACT_VALIDATIONS,
    "IntentStamps": INTENT_STAMPS,
    "PortStamps": PORT_STAMPS,
    "QueryGroups": QUERY_GROUPS,
    "IntentEvents": INTENT_EVENTS,
    "Probes": PROBES,
}
"""Every query by its operation's name: the eleven."""

PAGE_SIZE = 100
"""How many objects one request fetches, and how many devices' ids one Ports or PortStamps
request filters by."""

EVENT_PAGE_SIZE = 50
"""InfrahubEvent's own limit: Infrahub refuses a larger one."""


def nodes(page: dict | None) -> list:
    """The nodes of one paginated answer, a null edge's node left out."""
    out = []
    for edge in (page or {}).get("edges") or []:
        node = (edge or {}).get("node")
        if node is not None:
            out.append(node)
    return out


def edges(page: dict | None) -> list:
    """The edges of one answer, each a dict."""
    return [edge for edge in (page or {}).get("edges") or [] if isinstance(edge, dict)]


def count(page: dict | None) -> int:
    value = (page or {}).get("count")
    return value if isinstance(value, int) else 0


def value(attribute) -> str:
    """An attribute's value as GraphQL answers it; null reads as "", as Go decoded it."""
    if not isinstance(attribute, dict):
        return ""
    v = attribute.get("value")
    return v if isinstance(v, str) else ""


def node_of(relationship):
    """A relationship's node, None when it is null."""
    if not isinstance(relationship, dict):
        return None
    node = relationship.get("node")
    return node if isinstance(node, dict) else None
