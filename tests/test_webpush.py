"""Web Push: VAPID header, aes128gcm encryption (against the RFC 8291 example), and the HTTP send with its failures."""

import base64
import io
import json
import urllib.error
import urllib.request
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ingest import webpush
from ingest.webpush import Expired, PushError, b64d, b64e

# RFC 8291 appendix A: a worked example of the encryption (public test values, not secrets).
RFC_PLAINTEXT = b"When I grow up, I want to be a watermelon"
RFC_AS_PRIVATE = "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw"
RFC_UA_PUBLIC = "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4"
RFC_AUTH = "BTBZMqHH6r4Tts7J_aSIgg"
RFC_SALT = "DGv6ra1nlYgDCS1FRnbzlw"
RFC_BODY = (
    "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_"
    "yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN"
)


def _key(scalar: str) -> ec.EllipticCurvePrivateKey:
    return ec.derive_private_key(int.from_bytes(b64d(scalar), "big"), ec.SECP256R1())


def _subscriber() -> tuple[ec.EllipticCurvePrivateKey, str, str]:
    """A throwaway browser: its private key, and the p256dh / auth it would register."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return key, b64e(public), b64e(b"0123456789abcdef")


def _decrypt(body: bytes, ua_key: ec.EllipticCurvePrivateKey, ua_public: str, auth: str) -> bytes:
    """The browser's side, from RFC 8291, so a round trip proves the body is well formed."""
    salt, record_size, id_len = body[:16], int.from_bytes(body[16:20], "big"), body[20]
    as_public, ciphertext = body[21 : 21 + id_len], body[21 + id_len :]
    assert record_size == 4096
    peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), as_public)
    shared = ua_key.exchange(ec.ECDH(), peer)
    info = b"WebPush: info\x00" + b64d(ua_public) + as_public
    ikm = HKDF(hashes.SHA256(), 32, b64d(auth), info).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, ciphertext, None)
    assert plain.endswith(b"\x02")
    return plain[:-1]


def test_encrypt_matches_the_rfc_example() -> None:
    body = webpush.encrypt(RFC_PLAINTEXT, RFC_UA_PUBLIC, RFC_AUTH, ephemeral=_key(RFC_AS_PRIVATE), salt=b64d(RFC_SALT))
    assert b64e(body) == RFC_BODY


def test_encrypt_round_trip_uses_fresh_keys_each_time() -> None:
    ua_key, public, auth = _subscriber()
    first = webpush.encrypt(b"hello", public, auth)
    second = webpush.encrypt(b"hello", public, auth)
    assert first != second
    assert _decrypt(first, ua_key, public, auth) == b"hello"
    assert _decrypt(second, ua_key, public, auth) == b"hello"


@pytest.mark.parametrize(
    ("public", "auth", "payload"),
    [("not-a-key", "AAAA", b"x"), ("", "", b"x"), (RFC_UA_PUBLIC, "AAAA", b"x"), (RFC_UA_PUBLIC, RFC_AUTH, b"x" * 3001)],
)
def test_encrypt_rejects_bad_input(public: str, auth: str, payload: bytes) -> None:
    with pytest.raises(PushError):
        webpush.encrypt(payload, public, auth)


def test_vapid_key_formats() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    scalar = b64e(key.private_numbers().private_value.to_bytes(32, "big"))
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    # what `openssl ecparam -name prime256v1 -genkey -noout` prints: the SEC1 "BEGIN EC PRIVATE KEY" PEM the user stored
    sec1 = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()
    assert sec1.startswith("-----BEGIN EC PRIVATE KEY-----")
    with_parameters = "-----BEGIN EC PARAMETERS-----\nBggqhkjOPQMBBw==\n-----END EC PARAMETERS-----\n" + sec1  # without -noout
    for raw in (scalar, scalar + "\n", pem, sec1, "\n" + sec1 + "\n", with_parameters):
        assert webpush.public_key_b64(webpush.load_vapid_key(raw)) == webpush.public_key_b64(key)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "short",
        b64e(b"x" * 31),
        "-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----",
        "-----BEGIN EC PARAMETERS-----\nBggqhkjOPQMBBw==\n-----END EC PARAMETERS-----",  # parameters only, no key
    ],
)
def test_vapid_key_rejects_garbage_without_echoing_it(raw: str) -> None:
    with pytest.raises(PushError) as excinfo:
        webpush.load_vapid_key(raw)
    assert raw.strip() == "" or raw not in str(excinfo.value)


def test_vapid_key_rejects_another_curve() -> None:
    other = ec.generate_private_key(ec.SECP384R1())
    pem = other.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    with pytest.raises(PushError):
        webpush.load_vapid_key(pem)


def test_vapid_header_is_a_verifiable_es256_token() -> None:
    key = ec.generate_private_key(ec.SECP256R1())
    header = webpush.vapid_header(key, "https://web.push.apple.com/abc/def", "https://news.example.net", now=1_700_000_000)
    scheme, rest = header.split(" ", 1)
    assert scheme == "vapid"
    fields = dict(part.split("=", 1) for part in rest.split(", "))
    assert fields["k"] == webpush.public_key_b64(key)
    head, claims, signature = fields["t"].split(".")
    assert json.loads(b64d(head)) == {"typ": "JWT", "alg": "ES256"}
    assert json.loads(b64d(claims)) == {
        "aud": "https://web.push.apple.com",
        "exp": 1_700_000_000 + 12 * 3600,
        "sub": "https://news.example.net",
    }
    raw = b64d(signature)
    assert len(raw) == 64
    key.public_key().verify(
        encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
        f"{head}.{claims}".encode(),
        ec.ECDSA(hashes.SHA256()),
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://web.push.apple.com/x",
        "https://example.com/x",
        "https://evil-push.apple.com.example.com/x",
        "https://storage.googleapis.com/x",
        "https://name:secret"
        + "@"
        + "web.push.apple.com/x",  # userinfo in the URL (kept apart: the privacy guard looks for emails)
        "https://push.apple.com.evil.io/x",
        "ftp://web.push.apple.com",
        "",
    ],
)
def test_endpoint_must_be_https_on_a_known_push_service(endpoint: str) -> None:
    with pytest.raises(PushError):
        webpush.check_endpoint(endpoint)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://web.push.apple.com/x",
        "https://fcm.googleapis.com/fcm/send/x",
        "https://updates.push.services.mozilla.com/wpush/v2/x",
        "https://wns2-par02p.notify.windows.com/w/x",
    ],
)
def test_known_push_services_are_accepted(endpoint: str) -> None:
    assert webpush.check_endpoint(endpoint).startswith("https://")


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _send(opener: Any) -> int:
    _, public, auth = _subscriber()
    subscription = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": public, "auth": auth}}
    return webpush.send(
        subscription,
        {"title": "t", "body": "b", "url": "/", "tag": "x"},
        ec.generate_private_key(ec.SECP256R1()),
        "https://news.example.net",
        opener=opener,
        now=1_700_000_000,
    )


def test_send_posts_an_encrypted_body_with_the_push_headers() -> None:
    seen: dict[str, Any] = {}

    def opener(request: Any, timeout: float) -> _Response:
        seen["request"], seen["timeout"] = request, timeout
        return _Response(201)

    assert _send(opener) == 201
    request = seen["request"]
    assert request.get_method() == "POST"
    assert request.full_url == "https://web.push.apple.com/abc"
    assert request.get_header("Content-encoding") == "aes128gcm"
    assert request.get_header("Ttl") == "3600"
    assert request.get_header("Authorization").startswith("vapid t=")
    assert b"title" not in request.data  # encrypted, not sent in the clear
    assert seen["timeout"] == 5


@pytest.mark.parametrize("code", [404, 410])
def test_send_reports_an_expired_subscription(code: int) -> None:
    def opener(request: Any, timeout: float) -> _Response:
        raise urllib.error.HTTPError(request.full_url, code, "gone", None, io.BytesIO(b""))  # pyright: ignore[reportArgumentType]

    with pytest.raises(Expired):
        _send(opener)


@pytest.mark.parametrize(
    "failure",
    [urllib.error.HTTPError("https://x", 500, "oops", None, io.BytesIO(b"")), urllib.error.URLError("down"), TimeoutError()],
)  # pyright: ignore[reportArgumentType]
def test_send_wraps_other_failures(failure: Exception) -> None:
    def opener(request: Any, timeout: float) -> _Response:
        raise failure

    with pytest.raises(PushError) as excinfo:
        _send(opener)
    assert not isinstance(excinfo.value, Expired)


def test_base64_helpers_round_trip() -> None:
    assert b64d(b64e(b"\xfb\xff\x00abc")) == b"\xfb\xff\x00abc"
    assert base64.urlsafe_b64encode(b"\xfb\xff").decode().rstrip("=") == b64e(b"\xfb\xff")


def test_redirects_are_not_followed() -> None:
    import http.server
    import threading

    class Redirector(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/elsewhere")
            self.end_headers()

        def log_message(self, *args: Any) -> None:
            return None

    server = http.server.HTTPServer(("127.0.0.1", 0), Redirector)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/x", data=b"x", method="POST")
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            webpush._open(request, timeout=5)
        assert excinfo.value.code == 302
    finally:
        server.shutdown()
        server.server_close()
