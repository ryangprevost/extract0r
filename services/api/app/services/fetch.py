"""Fetching a reference from a URL instead of an upload.

Convenience for a real problem — the original is not always to hand — but a server that
fetches arbitrary URLs on request is a request forgery primitive unless it is built
carefully. Everything below exists for that reason.

**Only http and https.** `file://`, `gopher://` and friends read the server's own disk or
speak to services that were never expecting a request.

**Every resolved address is checked, not the hostname.** `internal.example.com` can
resolve to 10.0.0.5, and a name that passes a hostname check can resolve differently a
moment later. The check is on the addresses, and it is repeated on every redirect hop,
because a public URL that 302s to `169.254.169.254` is the standard way to read a cloud
instance's credentials.

**The size cap is enforced while reading.** `Content-Length` is a claim by the other end,
not a fact, and a server that sends more than it promised should cost us one buffer rather
than all our memory.

What this deliberately does not do is extract audio from streaming sites. Extract0r's own
terms say it will not process audio ripped from a streaming service in breach of that
service's terms, and a downloader built into the product would make that sentence false.
Streaming URLs are recognised only so the refusal can explain itself.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

#: Only schemes that mean "fetch a document over the network".
ALLOWED_SCHEMES = frozenset({"http", "https"})

#: Give up rather than hold a worker open on a server that has stopped talking.
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 60.0

#: A public URL that redirects inward is the usual shape of the attack, so each hop is
#: re-checked. The count is low because legitimate audio links do not need many.
MAX_REDIRECTS = 5

#: Read in chunks so the cap can be enforced against bytes actually received.
CHUNK_BYTES = 256 * 1024

#: Hosts that serve pages, not audio files. Listed so the error can say why rather than
#: failing later with an unhelpful "unsupported format".
STREAMING_HOSTS = (
    "youtube.com", "youtu.be", "music.youtube.com", "spotify.com", "open.spotify.com",
    "soundcloud.com", "apple.com", "music.apple.com", "tidal.com", "deezer.com",
    "bandcamp.com", "mixcloud.com", "audiomack.com", "pandora.com",
)

#: Plenty of servers - Wikimedia among them - reject requests that do not identify
#: themselves, so saying who we are is the difference between working and a blanket 403.
USER_AGENT = "Extract0r/0.1 (reference fetch; +https://github.com/ryangprevost/extract0r)"

#: Content types that actually carry audio. A page returning text/html is a page.
AUDIO_CONTENT_TYPES = (
    "audio/", "application/ogg", "application/octet-stream", "video/mp4",
)


class FetchError(Exception):
    """Something about the URL or the response makes it unusable. Message is user-facing."""


class BlockedHostError(FetchError):
    """The URL points somewhere a server should not be made to fetch on request."""


class StreamingSiteError(FetchError):
    """A streaming page rather than an audio file."""


@dataclass(slots=True)
class Fetched:
    data: bytes
    filename: str
    content_type: str
    source_url: str


def _is_blocked(address: str) -> bool:
    """Whether an address belongs to the infrastructure rather than the internet."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True  # unparseable is not something to gamble on

    # An IPv4 address wearing an IPv6 costume still reaches the IPv4 host.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped

    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local      # includes 169.254.169.254, the cloud metadata endpoint
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def resolve_public(host: str, port: int) -> None:
    """Resolve a hostname and refuse if *any* address it answers with is internal.

    Any, not all: a name that returns one public and one private address would otherwise
    be a way through, since which one gets connected to is not ours to decide.
    """
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise FetchError(f"Could not resolve {host}.") from exc

    if not infos:
        raise FetchError(f"Could not resolve {host}.")

    for info in infos:
        address = info[4][0]
        if _is_blocked(address):
            raise BlockedHostError(
                "That URL points at a private or internal address, so it will not be "
                "fetched. Use a public link to an audio file."
            )


def check_url(raw: str) -> str:
    """Validate a URL and return it, or raise with something worth reading."""
    raw = (raw or "").strip()
    if not raw:
        raise FetchError("Enter a URL.")

    parsed = urlparse(raw)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise FetchError("Only http and https URLs can be fetched.")
    if not parsed.hostname:
        raise FetchError("That URL has no host.")

    host = parsed.hostname.lower().rstrip(".")
    if any(host == site or host.endswith("." + site) for site in STREAMING_HOSTS):
        raise StreamingSiteError(
            "Extract0r does not download from streaming sites. Its terms say it will not "
            "process audio ripped from a streaming service in breach of that service's "
            "terms, and a downloader built in would make that untrue. Use a direct link "
            "to an audio file you have the right to use — cloud storage, your own site, "
            "or a promo link all work."
        )

    resolve_public(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    return raw


def filename_for(url: str, content_type: str) -> str:
    """A sensible name for the stored file, from the URL path where there is one."""
    from pathlib import PurePosixPath

    name = PurePosixPath(unquote(urlparse(url).path)).name
    if name and "." in name:
        return name[:120]

    for suffix, kind in (
        (".mp3", "mpeg"), (".flac", "flac"), (".wav", "wav"), (".ogg", "ogg"),
        (".m4a", "mp4"), (".aac", "aac"), (".aiff", "aiff"),
    ):
        if kind in content_type:
            return f"reference{suffix}"
    return "reference.mp3"


async def fetch_audio(url: str, max_bytes: int) -> Fetched:
    """Download an audio file, re-validating the destination at every redirect."""
    import httpx

    current = check_url(url)
    timeout = httpx.Timeout(READ_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)

    # Redirects are followed by hand so each hop goes through check_url again. With
    # follow_redirects=True the client would happily land on an internal address.
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(MAX_REDIRECTS + 1):
            try:
                request = client.build_request(
                    "GET",
                    current,
                    headers={"Accept": "audio/*,*/*", "User-Agent": USER_AGENT},
                )
                response = await client.send(request, stream=True)
            except httpx.HTTPError as exc:
                raise FetchError(f"Could not reach that URL: {exc}") from exc

            if response.is_redirect:
                location = response.headers.get("location", "")
                await response.aclose()
                if not location:
                    raise FetchError("That URL redirected without saying where.")
                current = check_url(str(httpx.URL(current).join(location)))
                continue

            try:
                if response.status_code >= 400:
                    raise FetchError(
                        f"That URL returned {response.status_code}. If it needs a login, "
                        "download it yourself and upload the file."
                    )

                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                if content_type and not content_type.startswith(AUDIO_CONTENT_TYPES):
                    raise FetchError(
                        f"That URL returned {content_type}, not audio. It is probably a "
                        "web page rather than a direct link to a file."
                    )

                chunks, total = [], 0
                async for chunk in response.aiter_bytes(CHUNK_BYTES):
                    total += len(chunk)
                    if total > max_bytes:
                        raise FetchError(
                            f"That file is larger than the {max_bytes // (1024 * 1024)} MB "
                            "limit."
                        )
                    chunks.append(chunk)
            finally:
                await response.aclose()

            data = b"".join(chunks)
            if not data:
                raise FetchError("That URL returned an empty file.")
            return Fetched(
                data=data,
                filename=filename_for(current, content_type),
                content_type=content_type,
                source_url=current,
            )

    raise FetchError("That URL redirected too many times.")
