"""Fetching a URL on request is a request-forgery primitive unless it is fenced in.

These are mostly negative tests, which is the point: the feature is one line of
convenience and a page of refusals, and the refusals are the part that has to hold.
"""

from __future__ import annotations

import pytest

from app.services import fetch
from app.services.fetch import (
    BlockedHostError,
    FetchError,
    StreamingSiteError,
    _is_blocked,
    check_url,
    filename_for,
)


@pytest.fixture
def public_dns(monkeypatch):
    """Resolve every hostname to a public address, so tests exercise policy not DNS."""
    monkeypatch.setattr(
        fetch.socket,
        "getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )


# ──────────────────────────────── address policy ────────────────────────────────


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1", "127.9.9.9",          # loopback
        "10.0.0.5", "172.16.4.1", "192.168.1.1",  # RFC1918
        "169.254.169.254",                  # cloud metadata, the classic target
        "0.0.0.0",
        "100.64.0.1",                       # carrier NAT
        "224.0.0.1",                        # multicast
        "::1",                              # IPv6 loopback
        "fc00::1",                          # IPv6 unique-local
        "fe80::1",                          # IPv6 link-local
        "::ffff:127.0.0.1",                 # IPv4 loopback wearing an IPv6 costume
        "::ffff:10.0.0.1",
        "not-an-address",
    ],
)
def test_internal_addresses_are_blocked(address):
    assert _is_blocked(address)


@pytest.mark.parametrize("address", ["93.184.216.34", "1.1.1.1", "2606:2800:220:1::1"])
def test_public_addresses_are_allowed(address):
    assert not _is_blocked(address)


def test_a_hostname_resolving_inward_is_refused(monkeypatch):
    """The check is on the resolved address, not the name. internal.example.com is a
    perfectly ordinary-looking hostname."""
    monkeypatch.setattr(
        fetch.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 443))]
    )
    with pytest.raises(BlockedHostError):
        check_url("https://internal.example.com/track.mp3")


def test_one_bad_answer_among_good_ones_is_enough(monkeypatch):
    """Which address gets connected to is not ours to decide, so any is disqualifying."""
    monkeypatch.setattr(
        fetch.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ],
    )
    with pytest.raises(BlockedHostError):
        check_url("https://mixed.example.com/track.mp3")


def test_a_name_that_does_not_resolve_is_an_error(monkeypatch):
    import socket as real_socket

    def boom(*a, **k):
        raise real_socket.gaierror("nope")

    monkeypatch.setattr(fetch.socket, "getaddrinfo", boom)
    with pytest.raises(FetchError, match="resolve"):
        check_url("https://nowhere.invalid/track.mp3")


# ──────────────────────────────── scheme policy ────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "file://C:/Windows/win.ini",
        "gopher://example.com/x",
        "ftp://example.com/track.mp3",
        "data:audio/mp3;base64,AAAA",
        "//example.com/track.mp3",
    ],
)
def test_only_http_and_https_are_fetched(url, public_dns):
    with pytest.raises(FetchError, match="http"):
        check_url(url)


@pytest.mark.parametrize("url", ["", "   ", "https://", "http://"])
def test_empty_and_hostless_urls_are_refused(url, public_dns):
    with pytest.raises(FetchError):
        check_url(url)


# ──────────────────────────────── streaming sites ────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=abc",
        "https://youtu.be/abc",
        "https://music.youtube.com/watch?v=abc",
        "https://open.spotify.com/track/abc",
        "https://soundcloud.com/artist/song",
        "https://music.apple.com/us/album/x/1",
        "https://artist.bandcamp.com/track/song",
    ],
)
def test_streaming_pages_are_refused_with_a_reason(url, public_dns):
    with pytest.raises(StreamingSiteError) as caught:
        check_url(url)
    # The refusal has to explain itself, not just fail.
    assert "terms" in str(caught.value)
    assert "direct link" in str(caught.value)


def test_a_lookalike_domain_is_not_caught_by_the_suffix_check(public_dns):
    """notyoutube.com is not youtube.com; the check is on labels, not substrings."""
    assert check_url("https://notyoutube.com/track.mp3")


def test_a_trailing_dot_does_not_get_past_the_check(public_dns):
    with pytest.raises(StreamingSiteError):
        check_url("https://youtube.com./watch?v=abc")


def test_an_ordinary_host_passes(public_dns):
    assert check_url("https://files.example.com/master.wav")


# ──────────────────────────────── naming ────────────────────────────────


@pytest.mark.parametrize(
    ("url", "content_type", "expected"),
    [
        ("https://x.com/My Song.mp3", "audio/mpeg", "My Song.mp3"),
        ("https://x.com/a/b/track.flac", "audio/flac", "track.flac"),
        ("https://x.com/My%20Song.wav", "audio/wav", "My Song.wav"),
        ("https://x.com/download?id=7", "audio/mpeg", "reference.mp3"),
        ("https://x.com/download", "audio/flac", "reference.flac"),
        ("https://x.com/", "", "reference.mp3"),
    ],
)
def test_the_stored_name_comes_from_the_url_or_the_type(url, content_type, expected):
    assert filename_for(url, content_type) == expected


def test_an_absurd_filename_is_truncated():
    long = "https://x.com/" + "a" * 500 + ".mp3"
    assert len(filename_for(long, "audio/mpeg")) <= 120


# ──────────────────────────────── the download itself ────────────────────────────


def transport(handler):
    """Swap httpx's network layer for a function, so these run without a server."""
    import httpx

    return httpx.MockTransport(handler)


@pytest.fixture
def mock_http(monkeypatch):
    """Let a test supply the responses fetch_audio will see."""
    import httpx

    def install(handler):
        original = httpx.AsyncClient

        class Patched(original):
            def __init__(self, *args, **kwargs):
                kwargs["transport"] = transport(handler)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", Patched)

    return install


@pytest.mark.anyio
async def test_a_redirect_to_an_internal_address_is_caught(mock_http, monkeypatch):
    """The attack this exists for: a public URL that 302s to the metadata endpoint.

    httpx would follow it happily with follow_redirects=True, which is why redirects are
    walked by hand and re-checked at every hop.
    """
    import httpx

    from app.services.fetch import fetch_audio

    def handler(request):
        if "evil" in str(request.url):
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
        return httpx.Response(200, content=b"x", headers={"content-type": "audio/mpeg"})

    mock_http(handler)
    resolved = {"evil.example.com": "93.184.216.34", "169.254.169.254": "169.254.169.254"}
    monkeypatch.setattr(
        fetch.socket,
        "getaddrinfo",
        lambda host, *a, **k: [(2, 1, 6, "", (resolved.get(host, host), 443))],
    )

    with pytest.raises(BlockedHostError):
        await fetch_audio("https://evil.example.com/track.mp3", 10 * 1024 * 1024)


@pytest.mark.anyio
async def test_a_file_bigger_than_it_claimed_is_cut_off(mock_http, public_dns):
    """The cap is enforced against bytes received, because Content-Length is a claim."""
    import httpx

    from app.services.fetch import fetch_audio

    mock_http(
        lambda request: httpx.Response(
            200,
            content=b"\0" * (3 * 1024 * 1024),
            headers={"content-type": "audio/mpeg", "content-length": "10"},
        )
    )
    with pytest.raises(FetchError, match="larger than"):
        await fetch_audio("https://files.example.com/big.mp3", 1024 * 1024)


@pytest.mark.anyio
async def test_a_web_page_is_not_mistaken_for_audio(mock_http, public_dns):
    import httpx

    from app.services.fetch import fetch_audio

    mock_http(
        lambda request: httpx.Response(
            200, content=b"<html></html>", headers={"content-type": "text/html"}
        )
    )
    with pytest.raises(FetchError, match="not audio"):
        await fetch_audio("https://files.example.com/page", 1024 * 1024)


@pytest.mark.anyio
async def test_an_empty_response_is_an_error(mock_http, public_dns):
    import httpx

    from app.services.fetch import fetch_audio

    mock_http(
        lambda request: httpx.Response(200, content=b"", headers={"content-type": "audio/mpeg"})
    )
    with pytest.raises(FetchError, match="empty"):
        await fetch_audio("https://files.example.com/nothing.mp3", 1024 * 1024)


@pytest.mark.anyio
async def test_a_login_wall_says_what_to_do_instead(mock_http, public_dns):
    import httpx

    from app.services.fetch import fetch_audio

    mock_http(lambda request: httpx.Response(403))
    with pytest.raises(FetchError, match="upload the file"):
        await fetch_audio("https://files.example.com/private.mp3", 1024 * 1024)


@pytest.mark.anyio
async def test_a_good_url_comes_back_with_its_bytes(mock_http, public_dns):
    import httpx

    from app.services.fetch import fetch_audio

    mock_http(
        lambda request: httpx.Response(
            200, content=b"ID3audio", headers={"content-type": "audio/mpeg"}
        )
    )
    got = await fetch_audio("https://files.example.com/Master%20v3.mp3", 1024 * 1024)
    assert got.data == b"ID3audio"
    assert got.filename == "Master v3.mp3"
    assert got.source_url.endswith("Master%20v3.mp3")


@pytest.mark.anyio
async def test_a_redirect_loop_gives_up(mock_http, public_dns):
    import httpx

    from app.services.fetch import fetch_audio

    mock_http(
        lambda request: httpx.Response(
            302, headers={"location": "https://files.example.com/again.mp3"}
        )
    )
    with pytest.raises(FetchError, match="too many times"):
        await fetch_audio("https://files.example.com/start.mp3", 1024 * 1024)


# ──────────────────────────────── through the API ────────────────────────────────


def a_track(client, sample_wav):
    """Upload something so there is a track for a reference to attach to."""
    with sample_wav.open("rb") as handle:
        response = client.post(
            "/api/v1/tracks",
            files={"file": ("song.wav", handle, "audio/wav")},
            data={"owns_or_licensed": "true", "personal_use_only": "true"},
        )
    assert response.status_code == 201, response.text
    return response.json()["track_id"]


def test_the_rights_gate_applies_to_a_url_too(client, sample_wav):
    """A different way to get the bytes, not a different set of rules about them."""
    track = a_track(client, sample_wav)
    response = client.post(
        f"/api/v1/tracks/{track}/reference/url",
        json={"url": "https://files.example.com/master.mp3", "owns_or_licensed": False},
    )
    assert response.status_code == 403
    assert "right to use" in response.json()["detail"]


def test_a_streaming_url_is_refused_with_an_explanation(client, sample_wav):
    track = a_track(client, sample_wav)
    response = client.post(
        f"/api/v1/tracks/{track}/reference/url",
        json={"url": "https://www.youtube.com/watch?v=abc", "owns_or_licensed": True},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "terms" in detail and "direct link" in detail


def test_an_internal_url_is_refused(client, sample_wav):
    track = a_track(client, sample_wav)
    response = client.post(
        f"/api/v1/tracks/{track}/reference/url",
        json={"url": "http://127.0.0.1:8000/admin", "owns_or_licensed": True},
    )
    assert response.status_code == 403
    assert "private or internal" in response.json()["detail"]


def test_a_url_for_an_unknown_track_is_a_404(client):
    response = client.post(
        "/api/v1/tracks/does-not-exist/reference/url",
        json={"url": "https://files.example.com/master.mp3", "owns_or_licensed": True},
    )
    assert response.status_code == 404
