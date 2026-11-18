"""Web Push for one subscriber: VAPID authentication (RFC 8292) and `aes128gcm` content encryption (RFC 8291).

Small on purpose: the only third-party code is `cryptography` (bundled into the Lambda at deploy time, see infra/bundle.py).
Nothing here reads configuration or logs a secret; the callers pass the key, the subscription and the site URL in."""

import base64
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# The push services a browser subscription can point at. The endpoint comes from a parameter edited by hand, and this keeps a
# typo or a bad paste from turning the Lambda into a client for any other address.
PUSH_HOSTS = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com")
RECORD_SIZE = 4096  # one record; Apple and the others accept payloads up to about 4 KB
MAX_PAYLOAD = 3000  # bytes of JSON before encryption
VAPID_LIFETIME = 12 * 3600  # a VAPID token must expire within 24 hours


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A push service answers 201 or an error, never a redirect; following one would leave the checked host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_open = urllib.request.build_opener(_NoRedirect).open


class PushError(Exception):
    """The push could not be sent (bad key or subscription, network failure, or a rejection)."""


class Expired(PushError):
    """The push service says the subscription is gone (HTTP 404 or 410): the phone has to register again."""


def b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def load_vapid_key(raw: str) -> ec.EllipticCurvePrivateKey:
    """The VAPID private key: a PEM (the one in use is the SEC1 "BEGIN EC PRIVATE KEY" that `openssl ecparam -name prime256v1
    -genkey -noout` prints; PKCS#8 works too, and an "EC PARAMETERS" block before the key is ignored), or the 32-byte scalar
    in URL-safe base64 (what `web-push generate-vapid-keys` prints)."""
    text = raw.strip()
    try:
        if "BEGIN" in text:
            block = re.search(
                r"-----BEGIN (?:EC |ENCRYPTED )?PRIVATE KEY-----.*?-----END (?:EC |ENCRYPTED )?PRIVATE KEY-----", text, re.DOTALL
            )
            if block is None:
                raise ValueError("no private key block")
            key = serialization.load_pem_private_key(block.group(0).encode(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
                raise ValueError("not a P-256 key")
            return key
        scalar = b64d(text)
        if len(scalar) != 32:
            raise ValueError("not 32 bytes")
        return ec.derive_private_key(int.from_bytes(scalar, "big"), ec.SECP256R1())
    except (ValueError, TypeError) as exc:
        raise PushError("the VAPID private key is not a valid P-256 key") from exc  # never include the value


def public_key_b64(key: ec.EllipticCurvePrivateKey) -> str:
    """The uncompressed public point, URL-safe base64: the `k` of the VAPID header and the browser's applicationServerKey."""
    point = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64e(point)


def check_endpoint(endpoint: str) -> str:
    """The endpoint's origin ("https://host"), if it is an https URL on a known push service."""
    parts = urlsplit(endpoint)
    host = parts.hostname or ""
    if parts.scheme != "https" or "@" in parts.netloc or not any(host == h or host.endswith("." + h) for h in PUSH_HOSTS):
        raise PushError("the subscription endpoint is not an https address on a known push service")
    return f"https://{parts.netloc}"


def vapid_header(key: ec.EllipticCurvePrivateKey, endpoint: str, subject: str, now: float) -> str:
    """The Authorization header: a short-lived ES256 token naming the push service (`aud`) and the site (`sub`)."""
    claims = {"aud": check_endpoint(endpoint), "exp": int(now) + VAPID_LIFETIME, "sub": subject}
    signing_input = b64e(json.dumps({"typ": "JWT", "alg": "ES256"}).encode()) + "." + b64e(json.dumps(claims).encode())
    r, s = decode_dss_signature(key.sign(signing_input.encode(), ec.ECDSA(hashes.SHA256())))
    token = signing_input + "." + b64e(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={token}, k={public_key_b64(key)}"


def encrypt(
    payload: bytes,
    p256dh: str,
    auth: str,
    *,
    ephemeral: ec.EllipticCurvePrivateKey | None = None,
    salt: bytes | None = None,
) -> bytes:
    """RFC 8291 `aes128gcm` body for one record. `ephemeral` and `salt` are only given by tests (the RFC's example)."""
    if len(payload) > MAX_PAYLOAD:
        raise PushError("payload is too large")
    try:
        ua_public = b64d(p256dh)
        auth_secret = b64d(auth)
        peer = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    except (ValueError, TypeError) as exc:
        raise PushError("the subscription keys are not valid") from exc
    if len(auth_secret) != 16:
        raise PushError("the subscription auth secret is not 16 bytes")
    as_key = ephemeral or ec.generate_private_key(ec.SECP256R1())
    as_public = as_key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    salt = salt or os.urandom(16)
    shared = as_key.exchange(ec.ECDH(), peer)
    key_info = b"WebPush: info\x00" + ua_public + as_public
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret, info=key_info).derive(shared)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # 0x02: the delimiter of the last (only) record
    return salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public + ciphertext


def send(
    subscription: dict[str, Any],
    message: dict[str, str],
    key: ec.EllipticCurvePrivateKey,
    subject: str,
    *,
    ttl: int = 3600,
    timeout: float = 5,
    opener: Callable[..., Any] = _open,
    now: float | None = None,
) -> int:
    """Send one message. Returns the HTTP status (201 when accepted). Raises Expired for 404/410, PushError for anything else."""
    endpoint = subscription["endpoint"]
    keys = subscription["keys"]
    body = encrypt(json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode(), keys["p256dh"], keys["auth"])
    request = urllib.request.Request(  # noqa: S310  (https only, on a known push host: check_endpoint, called by vapid_header)
        endpoint,
        data=body,
        method="POST",
        headers={
            "Authorization": vapid_header(key, endpoint, subject, time.time() if now is None else now),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(ttl),
            "Urgency": "high",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            return int(response.status)
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 410):
            raise Expired(f"push service answered {exc.code}") from exc
        raise PushError(f"push service answered {exc.code}") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise PushError(f"push failed: {type(exc).__name__}") from exc
