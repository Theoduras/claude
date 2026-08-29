#!/usr/bin/env python3
"""Web Push, spoken directly: VAPID (RFC 8292) and aes128gcm (RFC 8291).

This is the one place in the app where a library is *not* hand-rolled away.
CSRF sits on itsdangerous and the rate limiter sits on Postgres because both
are a few lines of ordinary code that happen to ship as packages. Web Push is
not that: pushing to a browser means ECDH on P-256, HKDF, an AES-GCM seal and
an ES256 signature, and writing any of those by hand is how private keys and
plaintexts leak. So `cryptography` is a dependency, and everything above the
primitives -- the framing, the headers, the retry-worthy status codes -- is
here, because that part is just bytes in a defined order.

`pywebpush` would do the same job, but it pulls `http_ece`, `py-vapid`,
`pyOpenSSL` and a second HTTP client behind it, and this module is ~150 lines
against the `requests` the app already has.

## What a send actually is

A push message is end-to-end encrypted between this server and the browser.
The push service (Google, Mozilla, Apple) relays a blob it cannot read, which
is why message content in a payload is no worse than message content in the
database -- and why the browser, not the service, decides what the person sees.

Two independent key pairs are involved and they are easy to confuse:

  * The **VAPID pair** is ours, long-lived, and lives in the environment. It
    signs a JWT that says "this push came from Velvt", so a push service can
    rate-limit and contact us. It never encrypts anything.
  * The **ephemeral pair** is generated per message. Its public half travels
    in the body; combined with the browser's own key it derives the content
    key. It is thrown away immediately, which is what makes each message's
    encryption independent of every other one's.

Run this file directly to mint a VAPID pair for .env:

    python webpush.py
"""
import base64
import hashlib
import hmac
import json
import os
import struct
import time
from urllib.parse import urlparse

import requests
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes, serialization

# A push service will not hold a message forever, and we would not want it to:
# "someone is searching right now" is false an hour later. Four hours is long
# enough to survive a phone being asleep and short enough that nothing stale
# arrives.
DEFAULT_TTL_SECONDS = 4 * 60 * 60

# RFC 8291 fixes the record size field but not its value. 4096 is the smallest
# size every push service is required to accept, and the payloads here are a
# title and a sentence -- there is nothing to gain from a larger record.
RECORD_SIZE = 4096
# 16 bytes of AES-GCM tag, one delimiter byte, and the 21-byte header that
# precedes the ciphertext. Anything longer would need a second record, which
# no notification this app sends comes close to.
MAX_PAYLOAD_BYTES = RECORD_SIZE - 17 - 21

# A JWT good for longer than a day is refused outright by some push services.
# Twelve hours is well inside that and means the token outlives any single
# request comfortably.
JWT_LIFETIME_SECONDS = 12 * 60 * 60


class PushGone(Exception):
    """The subscription is dead and should be deleted, not retried.

    A browser that clears its site data, or a person who revokes permission,
    leaves an endpoint that answers 404 or 410 forever. Distinguished from an
    ordinary failure because the correct response is to forget the row.
    """


# --- base64url ------------------------------------------------------------
# Every key and token in this protocol is base64url with the padding stripped,
# and Python's base64 module insists on the padding in one direction and emits
# it in the other. Two functions rather than the same fix at nine call sites.

def b64e(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64d(text):
    if isinstance(text, str):
        text = text.encode("ascii")
    return base64.urlsafe_b64decode(text + b"=" * (-len(text) % 4))


# --- keys -----------------------------------------------------------------

def _private_key(raw_b64):
    """The VAPID private key, stored as its 32-byte scalar.

    That is the shape every Web Push tool exchanges keys in -- a browser's
    `applicationServerKey` is the matching public point -- so a key minted
    here is usable by any other implementation, and vice versa.
    """
    return ec.derive_private_key(int.from_bytes(b64d(raw_b64), "big"),
                                 ec.SECP256R1())


def _public_bytes(key):
    """The uncompressed X9.62 point: 0x04 || X || Y, 65 bytes."""
    return key.public_bytes(serialization.Encoding.X962,
                            serialization.PublicFormat.UncompressedPoint)


def generate_keys():
    """A fresh VAPID pair as (private, public), both base64url.

    Minting a new pair invalidates every existing subscription: a browser
    remembers the application server key it subscribed with and the push
    service checks the signature against it. So this is a first-run step, not
    something to repeat.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    scalar = key.private_numbers().private_value.to_bytes(32, "big")
    return b64e(scalar), b64e(_public_bytes(key.public_key()))


def public_key_for(private_b64):
    """The public half, which is what the browser subscribes with."""
    return b64e(_public_bytes(_private_key(private_b64).public_key()))


# --- VAPID ----------------------------------------------------------------

def _vapid_header(endpoint, private_b64, subject):
    """`Authorization: vapid t=<jwt>, k=<public key>` for one endpoint.

    The audience is the push service's *origin* and nothing more -- signing
    the full endpoint would leak the subscription into the token, and the
    spec asks for the origin anyway.
    """
    origin = urlparse(endpoint)
    key = _private_key(private_b64)

    header = b64e(json.dumps({"typ": "JWT", "alg": "ES256"},
                             separators=(",", ":")).encode("utf-8"))
    claims = b64e(json.dumps({
        "aud": f"{origin.scheme}://{origin.netloc}",
        "exp": int(time.time()) + JWT_LIFETIME_SECONDS,
        "sub": subject,
    }, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{claims}".encode("ascii")

    # ES256 wants the raw r||s pair; `cryptography` signs to DER, which is
    # what a TLS certificate uses and what a JWS explicitly does not.
    der = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = b64e(r.to_bytes(32, "big") + s.to_bytes(32, "big"))

    return (f"vapid t={header}.{claims}.{signature}, "
            f"k={b64e(_public_bytes(key.public_key()))}")


# --- payload encryption ---------------------------------------------------

def _hkdf(salt, ikm, info, length):
    """One-block HKDF. Every output here is 16 or 32 bytes, so N is always 1."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(payload, ua_public_b64, auth_secret_b64):
    """Seal `payload` for one subscription, per RFC 8291 section 3.4.

    The returned bytes are the whole request body: a header carrying the salt,
    the record size and our ephemeral public key, then the sealed record. The
    browser has everything it needs to derive the same key from its own
    private half -- nothing about the content key is transmitted.
    """
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError(
            f"push payload is {len(payload)} bytes; one record holds "
            f"{MAX_PAYLOAD_BYTES}")

    ua_public = b64d(ua_public_b64)
    auth_secret = b64d(auth_secret_b64)

    ours = ec.generate_private_key(ec.SECP256R1())
    our_public = _public_bytes(ours.public_key())
    shared = ours.exchange(
        ec.ECDH(),
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))

    # The auth secret is the salt for this first step, which is what binds the
    # derived key to *this subscription* rather than to the ECDH alone.
    ikm = _hkdf(auth_secret, shared,
                b"WebPush: info\x00" + ua_public + our_public, 32)

    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)

    # 0x02 is the last-record delimiter. A single record is always the last.
    sealed = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return (salt + struct.pack("!IB", RECORD_SIZE, len(our_public))
            + our_public + sealed)


# --- sending --------------------------------------------------------------

def send(subscription, payload, private_b64, subject,
         ttl=DEFAULT_TTL_SECONDS, urgency="normal", timeout=5):
    """Deliver one message to one browser. Returns the push service's status.

    `subscription` is the PushSubscription the browser handed us, as
    {"endpoint", "p256dh", "auth"}.

    Raises PushGone when the endpoint has been retired, so the caller can
    delete the row instead of retrying it every time forever. Every other
    failure is the caller's to decide about -- a push service having a bad
    minute is not a reason to lose a subscription.
    """
    body = encrypt(payload, subscription["p256dh"], subscription["auth"])
    resp = requests.post(
        subscription["endpoint"],
        data=body,
        headers={
            "Authorization": _vapid_header(subscription["endpoint"],
                                           private_b64, subject),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(ttl),
            # "normal" wakes a sleeping phone; "low" waits for it to be awake
            # anyway. A chat message is normal, a product announcement is not.
            "Urgency": urgency,
        },
        timeout=timeout,
    )
    if resp.status_code in (404, 410):
        raise PushGone(f"{resp.status_code} from {urlparse(subscription['endpoint']).netloc}")
    return resp.status_code


if __name__ == "__main__":
    private, public = generate_keys()
    print("# Add these to .env. The public key is not a secret -- it is handed")
    print("# to every browser that subscribes. The private key signs, so it is.")
    print(f"VAPID_PRIVATE_KEY={private}")
    print(f"VAPID_PUBLIC_KEY={public}")
