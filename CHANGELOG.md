# Changelog

What each release changed for a user, newest first, and its known limits ([D-106](design/decisions.md#d-106)). A
release's section is headed `## <version> - <date>`, `unreleased` standing in the date until the commit that is tagged
dates it.

## 1.0.0rc1 - unreleased

The first release. The three distributions, `fylgja-core`, `fylgja-infrahub` and `fylgja-netbox`, are published
as wheels at one version, each built from this repository alone: a release on PyPI, a candidate on TestPyPI.

What 1.0 holds, and what it does not, is stated on [one page](docs/compatibility.md): the API and the formats at version 1, the
four commands with their options and exit statuses, and the names of the variables they read are held within major
version 1, and the example orchestrator, the make targets and the scripts are not.

Not published: an image, a source distribution and the example orchestrator.

A store with twins in it is not carried across an upgrade: destroy the twins before upgrading.

### Known limits

Written with the candidate: none is recorded yet.
