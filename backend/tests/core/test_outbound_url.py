"""SSRF guard: metadata, loopback, private ranges, DNS rebinding, URL tricks."""

import pytest

from app.core.outbound_url import (
    OutboundUrlError,
    Resolver,
    parse_networks,
    resolve,
    resolve_url,
)

PUBLIC = "93.184.216.34"


def fixed(*answers: str) -> Resolver:
    return lambda host, port: list(answers)


@pytest.mark.parametrize(
    "address",
    [
        "169.254.169.254",
        "127.0.0.1",
        "127.10.0.1",
        "::1",
        "::ffff:127.0.0.1",
        "0.0.0.0",  # noqa: S104 - refused, not bound
        "fd00:ec2::254",
        "fe80::1",
        "224.0.0.1",
        "10.0.0.5",
        "192.168.1.10",
        "172.16.0.1",
    ],
)
def test_refused_addresses(address: str) -> None:
    with pytest.raises(OutboundUrlError):
        resolve(address, 443)


def test_metadata_refused_through_a_host_name() -> None:
    with pytest.raises(OutboundUrlError):
        resolve_url("https://metadata.internal/latest", resolver=fixed("169.254.169.254"))


def test_private_network_allowed_only_when_allowlisted() -> None:
    allowed = parse_networks(["10.0.0.0/8"])
    assert resolve("10.1.2.3", 6514, allowed).address == "10.1.2.3"
    with pytest.raises(OutboundUrlError):
        resolve("192.168.1.10", 6514, allowed)


@pytest.mark.parametrize(
    "network", ["169.254.0.0/16", "127.0.0.0/8", "8.8.8.0/24", "0.0.0.0/0", "fd00:ec2::254/128"]
)
def test_unsafe_networks_cannot_be_allowlisted(network: str) -> None:
    with pytest.raises(OutboundUrlError):
        parse_networks([network])


def test_allowlist_never_opens_loopback_or_metadata() -> None:
    allowed = parse_networks(["10.0.0.0/8", "fc00::/7"])
    for address in ("127.0.0.1", "169.254.169.254", "fd00:ec2::254"):
        with pytest.raises(OutboundUrlError):
            resolve(address, 443, allowed)


def test_one_private_answer_refuses_the_host() -> None:
    with pytest.raises(OutboundUrlError):
        resolve_url("https://hooks.example.com/x", resolver=fixed(PUBLIC, "127.0.0.1"))


def test_dns_rebinding_cannot_change_the_pinned_address() -> None:
    answers = iter([[PUBLIC], ["127.0.0.1"]])

    def rebinding(host: str, port: int) -> list[str]:
        return next(answers)

    destination = resolve_url("https://hooks.example.com/notify?a=1", resolver=rebinding)
    assert destination.address == PUBLIC
    assert destination.host == "hooks.example.com"
    assert destination.path == "/notify?a=1"
    # The resolver was asked once: the connection uses the checked address, never the name.
    assert next(answers) == ["127.0.0.1"]


@pytest.mark.parametrize(
    "url",
    [
        "http://hooks.example.com/",
        "ftp://hooks.example.com/",
        "https://user:pass@hooks.example.com/",
        "https://hooks.example.com@127.0.0.1/",
        "https://hooks.example.com/#frag",
        "https:///nohost",
        "https://hooks.example.com:99999/",
        "https://exa mple.com/",
    ],
)
def test_refused_urls(url: str) -> None:
    with pytest.raises(OutboundUrlError):
        resolve_url(url, resolver=fixed(PUBLIC))


def test_unresolvable_host_is_refused() -> None:
    with pytest.raises(OutboundUrlError):
        resolve_url("https://hooks.example.com/", resolver=fixed())
