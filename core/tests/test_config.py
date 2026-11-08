"""Settings come from FYLGJA_* variables; a missing or malformed one is refused by name."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from fylgja_core import config

FULL = {
    "FYLGJA_STORE": "/var/lib/fylgja",
    "FYLGJA_TOKENS": "/etc/fylgja/tokens",
    "FYLGJA_PACKAGES": "/opt/psp:/opt/probes",
    "FYLGJA_LISTEN": "0.0.0.0:9000",
    "FYLGJA_DRIVER": "containerlab",
    "FYLGJA_WORKERS": "2",
    "FYLGJA_STEP_WAIT_S": "90",
    "FYLGJA_RESYNC_S": "600",
}
REQUIRED = ("FYLGJA_STORE", "FYLGJA_TOKENS", "FYLGJA_PACKAGES")
S3 = {**FULL, "FYLGJA_STORE": "s3://fylgja/dev/core", "FYLGJA_S3_ENDPOINT": "http://s3.example.internal:7070",
      "FYLGJA_S3_ACCESS_KEY": "AKIDEXAMPLE", "FYLGJA_S3_SECRET_KEY": "fixture-secret-not-a-credential",
      "FYLGJA_LEASE": "fylgja-core", "FYLGJA_DRIVER": "clabernetes", "FYLGJA_CLABERNETES_NAMESPACE": "c9s",
      "FYLGJA_POD_CIDR": "198.51.100.0/24"}
"""A whole environment for an object store: held by a Lease, on the clabernetes driver (D-061, D-062)."""
KEYS = (S3["FYLGJA_S3_ACCESS_KEY"], S3["FYLGJA_S3_SECRET_KEY"])
S3_REQUIRED = ("FYLGJA_S3_ENDPOINT", "FYLGJA_S3_ACCESS_KEY", "FYLGJA_S3_SECRET_KEY")


def location(environ: dict[str, str]) -> config.S3Location:
    store = config.from_environ(environ).store
    assert isinstance(store, config.S3Location)
    return store


def same(a: config.S3Location, b: config.S3Location) -> bool:
    """`a == b` as a bool, so a failure prints the two reprs and never pytest's field-by-field
    account, which would print a differing key."""
    return a == b


def test_settings_from_a_full_environment() -> None:
    assert config.from_environ(FULL) == config.Settings(
        store=Path("/var/lib/fylgja"),
        listen=("0.0.0.0", 9000),
        driver="containerlab",
        workers=2,
        step_wait_s=90,
        resync_s=600,
        packages=(Path("/opt/psp"), Path("/opt/probes")),
        tokens=Path("/etc/fylgja/tokens"),
    )


def test_defaults() -> None:
    env = {k: FULL[k] for k in REQUIRED}
    s = config.from_environ(env)
    assert (s.listen, s.driver, s.workers, s.step_wait_s) == (("127.0.0.1", 7650), "containerlab", 4, 180)


@pytest.mark.parametrize("variable", REQUIRED)
def test_each_missing_required_variable_is_named(variable: str) -> None:
    env = {k: v for k, v in FULL.items() if k != variable}
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ(env)
    assert e.value.variable == variable
    assert variable in str(e.value)


def test_an_empty_required_variable_counts_as_missing() -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**FULL, "FYLGJA_STORE": ""})
    assert e.value.variable == "FYLGJA_STORE"


@pytest.mark.parametrize("workers", ["x", "0", "-1", "2.5"])
def test_workers_must_be_an_integer_of_one_or_more(workers: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**FULL, "FYLGJA_WORKERS": workers})
    assert e.value.variable == "FYLGJA_WORKERS"
    assert workers not in str(e.value)


@pytest.mark.parametrize("listen", ["7650", "h1:", "h1:abc", "h1:0", "h1:70000", ":80"])
def test_listen_must_be_host_and_port(listen: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**FULL, "FYLGJA_LISTEN": listen})
    assert e.value.variable == "FYLGJA_LISTEN"
    assert listen not in str(e.value)


def test_an_unknown_driver_is_refused_naming_the_variable_and_the_served_names() -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**FULL, "FYLGJA_DRIVER": "zz9"})
    assert e.value.variable == "FYLGJA_DRIVER"
    assert "clabernetes, containerlab" in str(e.value)
    assert "zz9" not in str(e.value)


def test_a_missing_variable_files_settings_missing() -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({})
    assert e.value.rule == "settings.missing"


@pytest.mark.parametrize("wait", ["abc", "0", "-1", "1.5"])
def test_the_step_wait_must_be_an_integer_of_one_or_more(wait: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**FULL, "FYLGJA_STEP_WAIT_S": wait})
    assert e.value.variable == "FYLGJA_STEP_WAIT_S" and e.value.rule == config.RULE_MISSING
    assert wait not in str(e.value)


def test_the_resync_is_300_by_default_and_refused_below_one() -> None:
    assert config.from_environ({k: FULL[k] for k in REQUIRED}).resync_s == 300
    assert config.from_environ({**FULL, "FYLGJA_RESYNC_S": "1"}).resync_s == 1
    for resync in ["abc", "0", "-1", "1.5"]:
        with pytest.raises(config.Misconfigured) as e:
            config.from_environ({**FULL, "FYLGJA_RESYNC_S": resync})
        assert e.value.variable == "FYLGJA_RESYNC_S" and e.value.rule == config.RULE_MISSING
        assert str(e.value) == "FYLGJA_RESYNC_S: is not an integer of 1 or more"


def test_an_s3_store_is_a_location() -> None:
    # Every value holding a key is built outside an assert: pytest's account of a failed one
    # prints the arguments of each call in it.
    access_key, secret_key = KEYS
    got = location(S3)
    expected = config.S3Location("fylgja", "dev/core", "http://s3.example.internal:7070", "us-east-1",
                                 access_key, secret_key, None)
    assert same(got, expected)
    got = location({**S3, "FYLGJA_S3_REGION": "eu-west-1", "FYLGJA_S3_CA": "/etc/ca.pem"})
    expected = config.S3Location("fylgja", "dev/core", "http://s3.example.internal:7070", "eu-west-1",
                                 access_key, secret_key, Path("/etc/ca.pem"))
    assert same(got, expected)
    assert config.DEFAULT_S3_REGION == "us-east-1"


def test_a_bucket_alone_and_a_trailing_slash() -> None:
    stores = ("s3://fylgja", "s3://fylgja/", "s3://fylgja/p/")
    found = [location({**S3, "FYLGJA_STORE": store}) for store in stores]
    assert [(f.bucket, f.prefix, str(f)) for f in found] == [
        ("fylgja", "", "s3://fylgja"), ("fylgja", "", "s3://fylgja"), ("fylgja", "p", "s3://fylgja/p")]
    slashed = location({**S3, "FYLGJA_S3_ENDPOINT": "http://s3.example.internal:7070/"})
    assert slashed.endpoint == "http://s3.example.internal:7070"


def test_the_scheme_is_read_without_regard_to_case() -> None:
    found = location({**S3, "FYLGJA_STORE": "S3://fylgja/dev"})
    assert (found.bucket, found.prefix, str(found)) == ("fylgja", "dev", "s3://fylgja/dev")


def test_the_keys_are_in_no_repr_and_no_str() -> None:
    settings = config.from_environ(S3)
    store = location(S3)
    assert str(store) == "s3://fylgja/dev/core"
    assert all(key not in text for key in KEYS for text in (repr(settings), repr(store), str(store)))


@pytest.mark.parametrize("variable", S3_REQUIRED)
def test_each_missing_s3_variable_is_named(variable: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({k: v for k, v in S3.items() if k != variable})
    assert e.value.variable == variable and e.value.rule == config.RULE_MISSING
    assert str(e.value) == f"{variable}: is not set, and FYLGJA_STORE names an object store"


@pytest.mark.parametrize("store", ["s3://", "s3://ab", "s3://Bucket", "s3://fylgja//p", "s3://fylgja/../x",
                                   "s3:/fylgja", "s3:fylgja"])
def test_a_malformed_s3_store_names_the_variable(store: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**S3, "FYLGJA_STORE": store})
    assert e.value.variable == "FYLGJA_STORE"
    # The whole message is the rule, so it holds no value: `s3://` alone is in the rule's own text.
    assert str(e.value) == "FYLGJA_STORE: is not a directory or s3://<bucket>[/<prefix>]"


@pytest.mark.parametrize("endpoint", ["versity:7070", "ftp://h", "http://", "http://user:pw@h", "http://h/path",
                                      "http://h?x=1", "http://h:port", "http://h:0", "http://[::1]:7070",
                                      "http://[v1.fe]:7070"])
def test_a_malformed_endpoint_names_the_variable(endpoint: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**S3, "FYLGJA_S3_ENDPOINT": endpoint})
    assert e.value.variable == "FYLGJA_S3_ENDPOINT"
    # The whole message is the rule, so it holds no value: `http://` alone is in the rule's own text.
    assert str(e.value) == "FYLGJA_S3_ENDPOINT: is not an http:// or https:// URL of a host and an optional port"


def test_a_directory_store_reads_no_s3_variable() -> None:
    settings = config.from_environ({**FULL, "FYLGJA_S3_ENDPOINT": "nonsense"})
    assert settings == config.from_environ(FULL) and settings.store == Path("/var/lib/fylgja")


SITE = {"FYLGJA_CLABERNETES_NAMESPACE": "c9s", "FYLGJA_POD_CIDR": "10.244.0.0/16"}
CLABERNETES = {**FULL, "FYLGJA_DRIVER": "clabernetes", **SITE}


def test_the_clabernetes_driver_reads_its_namespace_and_the_pod_cidr() -> None:
    s = config.from_environ(CLABERNETES)
    assert (s.driver, s.clabernetes_namespace, s.pod_cidr) == ("clabernetes", "c9s", "10.244.0.0/16")


@pytest.mark.parametrize("variable", sorted(SITE))
@pytest.mark.parametrize("unset", [None, ""], ids=["absent", "empty"])
def test_each_site_variable_the_clabernetes_driver_needs_is_named_when_missing(
    variable: str, unset: str | None
) -> None:
    env = {k: v for k, v in CLABERNETES.items() if k != variable}
    if unset is not None:
        env[variable] = unset
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ(env)
    assert e.value.variable == variable and e.value.rule == config.RULE_MISSING
    assert str(e.value) == f"{variable}: is not set, and FYLGJA_DRIVER=clabernetes needs it"


def test_the_site_variables_are_none_unset_under_the_local_driver() -> None:
    s = config.from_environ(FULL)
    assert (s.driver, s.clabernetes_namespace, s.pod_cidr) == ("containerlab", None, None)


@pytest.mark.parametrize("driver", ["containerlab", "clabernetes"])
@pytest.mark.parametrize("cidr", ["10.244.0.1/16", "fd00::/48", "pods", "10.244.0.0"])
def test_a_pod_cidr_set_must_be_an_ipv4_network_in_cidr_form(driver: str, cidr: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**CLABERNETES, "FYLGJA_DRIVER": driver, "FYLGJA_POD_CIDR": cidr})
    assert e.value.variable == "FYLGJA_POD_CIDR"
    assert str(e.value) == "FYLGJA_POD_CIDR: is not an IPv4 network in CIDR form"


@pytest.mark.parametrize("driver", ["containerlab", "clabernetes"])
@pytest.mark.parametrize("namespace", ["C9S", "a.b", "c" * 64, "-c9s", "c9s-"])
def test_a_clabernetes_namespace_set_must_be_a_namespace_name(driver: str, namespace: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**CLABERNETES, "FYLGJA_DRIVER": driver, "FYLGJA_CLABERNETES_NAMESPACE": namespace})
    assert e.value.variable == "FYLGJA_CLABERNETES_NAMESPACE"
    assert str(e.value) == "FYLGJA_CLABERNETES_NAMESPACE: is not a namespace name"


def test_a_namespace_of_63_characters_is_one_and_a_pod_cidr_is_kept_in_its_canonical_form() -> None:
    s = config.from_environ({**CLABERNETES, "FYLGJA_CLABERNETES_NAMESPACE": "c" * 63,
                             "FYLGJA_POD_CIDR": "10.244.0.0/255.255.0.0"})
    assert (s.clabernetes_namespace, s.pod_cidr) == ("c" * 63, "10.244.0.0/16")


TLS = {"FYLGJA_TLS_CERT": "/etc/fylgja/tls/tls.crt", "FYLGJA_TLS_KEY": "/etc/fylgja/tls/tls.key"}
NOT_A_LEASE = "FYLGJA_LEASE: is not a Kubernetes object name: lower-case letters, digits, - and ."


def test_the_lease_and_the_tls_pair_are_read() -> None:
    s = config.from_environ({**FULL, "FYLGJA_LEASE": "fylgja-core", **TLS})
    assert (s.lease, s.tls) == ("fylgja-core", (Path("/etc/fylgja/tls/tls.crt"), Path("/etc/fylgja/tls/tls.key")))


@pytest.mark.parametrize("unset", [None, ""], ids=["absent", "empty"])
def test_no_lease_and_no_tls_unless_they_are_set(unset: str | None) -> None:
    env = dict(FULL) if unset is None else {**FULL, "FYLGJA_LEASE": unset, "FYLGJA_TLS_CERT": unset,
                                            "FYLGJA_TLS_KEY": unset}
    s = config.from_environ(env)
    assert (s.lease, s.tls) == (None, None)


@pytest.mark.parametrize(("set_", "other"), [("FYLGJA_TLS_CERT", "FYLGJA_TLS_KEY"),
                                             ("FYLGJA_TLS_KEY", "FYLGJA_TLS_CERT")])
@pytest.mark.parametrize("unset", [None, ""], ids=["absent", "empty"])
def test_one_of_the_tls_pair_alone_is_refused_naming_the_one_not_set(set_: str, other: str, unset: str | None) -> None:
    env = {**FULL, set_: TLS[set_]}
    if unset is not None:
        env[other] = unset
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ(env)
    assert e.value.variable == other and e.value.rule == config.RULE_MISSING
    assert str(e.value) == f"{other}: is not set, and {set_} is: the two are set together or not at all"


@pytest.mark.parametrize("lease", ["fylgja-core", "fylgja.core-1", "0", "a" * 253],
                         ids=["fylgja-core", "fylgja.core-1", "0", "253-characters"])
def test_a_lease_is_a_kubernetes_object_name_of_at_most_253_characters(lease: str) -> None:
    assert config.from_environ({**FULL, "FYLGJA_LEASE": lease}).lease == lease


@pytest.mark.parametrize("lease", ["Not_A_Name", "a" * 254, "Fylgja", "-fylgja", "fylgja-", "fylgja..core",
                                   ".fylgja", "fylgja.", "fylgja core", "fylgja/core", "fylgja-.core", "fylgja.-core"],
                         ids=["Not_A_Name", "254-characters", "upper-case", "leading-dash", "trailing-dash",
                              "empty-label", "leading-dot", "trailing-dot", "space", "slash", "label-ends-in-a-dash",
                              "label-begins-with-a-dash"])
def test_a_lease_that_is_no_kubernetes_object_name_is_refused(lease: str) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**FULL, "FYLGJA_LEASE": lease})
    assert e.value.variable == "FYLGJA_LEASE" and e.value.rule == config.RULE_MISSING
    # The whole message is the rule, so it holds no value.
    assert str(e.value) == NOT_A_LEASE


def test_an_s3_store_held_by_a_lease_on_the_clabernetes_driver_is_accepted() -> None:
    s = config.from_environ(S3)
    assert isinstance(s.store, config.S3Location)
    assert (s.lease, s.driver, s.clabernetes_namespace, s.pod_cidr) == (
        "fylgja-core", "clabernetes", "c9s", "198.51.100.0/24")


S3_RULED_OUT = [
    ({k: v for k, v in S3.items() if k != "FYLGJA_LEASE"}, "FYLGJA_LEASE",
     "FYLGJA_LEASE: is not set, and an s3:// store is held for one core by a Lease alone"),
    ({**S3, "FYLGJA_LEASE": ""}, "FYLGJA_LEASE",
     "FYLGJA_LEASE: is not set, and an s3:// store is held for one core by a Lease alone"),
    ({**S3, "FYLGJA_DRIVER": "containerlab"}, "FYLGJA_DRIVER",
     "FYLGJA_DRIVER: names a driver that keeps its files in the store's directory, and FYLGJA_STORE names none"),
    ({k: v for k, v in S3.items() if k != "FYLGJA_DRIVER"}, "FYLGJA_DRIVER",  # the default driver, containerlab
     "FYLGJA_DRIVER: names a driver that keeps its files in the store's directory, and FYLGJA_STORE names none"),
]


@pytest.mark.parametrize(("environ", "variable", "message"), S3_RULED_OUT,
                         ids=["lease-absent", "lease-empty", "containerlab", "driver-absent"])
def test_an_s3_store_without_a_lease_or_with_a_driver_that_needs_a_directory_is_refused(
    environ: dict[str, str], variable: str, message: str
) -> None:
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ(environ)
    assert e.value.variable == variable and e.value.rule == config.RULE_MISSING
    # No value in the message, a key least of all: each is looked for where a failure prints none of them.
    text = str(e.value)
    assert not any(value in text for value in KEYS)
    assert not any(environ[name] in text for name in ("FYLGJA_STORE", "FYLGJA_S3_ENDPOINT", "FYLGJA_DRIVER")
                   if name in environ)
    assert text == message


def test_the_lease_is_named_before_the_driver_and_check_runs_last() -> None:
    # No Lease and the containerlab driver: the Lease is named first.
    lacking = {k: v for k, v in S3.items() if k != "FYLGJA_LEASE"}
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**lacking, "FYLGJA_DRIVER": "containerlab"})
    assert e.value.variable == "FYLGJA_LEASE"
    # A fault in a setting read alone is named before what one setting rules out of another.
    with pytest.raises(config.Misconfigured) as e:
        config.from_environ({**lacking, "FYLGJA_TLS_CERT": TLS["FYLGJA_TLS_CERT"]})
    assert e.value.variable == "FYLGJA_TLS_KEY"


@pytest.mark.parametrize("environ", [FULL, {**FULL, "FYLGJA_LEASE": "fylgja-core"}, CLABERNETES,
                                     {**CLABERNETES, "FYLGJA_LEASE": "fylgja-core"}],
                         ids=["containerlab", "containerlab-lease", "clabernetes", "clabernetes-lease"])
def test_a_directory_store_takes_either_driver_with_or_without_a_lease(environ: dict[str, str]) -> None:
    s = config.from_environ(environ)
    assert s.store == Path("/var/lib/fylgja") and s.lease == environ.get("FYLGJA_LEASE")
    config.check(s)


def test_check_refuses_settings_made_whole_without_from_environ() -> None:
    access_key, secret_key = KEYS
    store = config.S3Location("fylgja", "", "http://s3.example.internal:7070", "us-east-1", access_key, secret_key,
                              None)
    base = config.from_environ(FULL)
    with pytest.raises(config.Misconfigured) as e:
        config.check(dataclasses.replace(base, store=store, driver="clabernetes"))
    assert e.value.variable == "FYLGJA_LEASE"
    with pytest.raises(config.Misconfigured) as e:
        config.check(dataclasses.replace(base, store=store, lease="fylgja-core"))
    assert e.value.variable == "FYLGJA_DRIVER"
    config.check(dataclasses.replace(base, store=store, driver="clabernetes", lease="fylgja-core"))
