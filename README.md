# SnapPass

[![Artifact Hub](https://img.shields.io/endpoint?url=https://artifacthub.io/badge/repository/snappass)](https://artifacthub.io/packages/search?repo=snappass)
[![CI](https://github.com/lmacka/snappass/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/lmacka/snappass/actions/workflows/ci.yml)
[![GitHub Release](https://img.shields.io/github/v/release/lmacka/snappass)](https://github.com/lmacka/snappass/releases)
[![Docker Pulls](https://img.shields.io/docker/pulls/lmacka/snappass)](https://hub.docker.com/r/lmacka/snappass)
[![Trivy](https://github.com/lmacka/snappass/actions/workflows/trivy.yml/badge.svg)](https://github.com/lmacka/snappass/actions/workflows/trivy.yml)

A zero-knowledge, one-time secret sharing web app. Fork of [Pinterest's SnapPass](https://github.com/pinterest/snappass) with major security and architecture upgrades.

Share a secret by generating a link. The recipient opens the link, reveals the secret once, and it's permanently deleted. The server never sees your plaintext - encryption and decryption happen entirely in the browser.

```mermaid
sequenceDiagram
    box rgb(30, 30, 40) Creating a Secret
        participant You
        participant Browser
        participant Server
        participant Redis
    end

    You->>Browser: type secret + TTL
    Note over Browser: generate random AES-256-GCM key
    Note over Browser: encrypt secret locally
    Browser->>Server: POST ciphertext + TTL
    Note right of Browser: #key never sent
    Server->>Redis: SET key blob, EXPIRE ttl
    Redis-->>Server: OK
    Server-->>Browser: storage key
    Browser-->>You: link: /key#aes_key
    Note over You: send link to recipient
```

```mermaid
sequenceDiagram
    box rgb(30, 30, 40) Revealing a Secret
        participant Recipient
        participant Browser
        participant Server
        participant Redis
    end

    Recipient->>Browser: open link
    Browser->>Server: POST /key (no #fragment)
    Server->>Redis: GET key
    Redis-->>Server: ciphertext
    Server->>Redis: DEL key
    Server-->>Browser: ciphertext
    Note over Browser: decrypt with #key from URL
    Browser-->>Recipient: plaintext secret
```

> **The `#key` NEVER leaves the browser** - servers don't receive URL fragments ([RFC 3986](https://www.rfc-editor.org/rfc/rfc3986#section-3.5))
>
> **Redis only stores opaque ciphertext** - useless without the key
>
> **Secret is deleted on first retrieval** - no second chances

## What Changed From Upstream

This fork rewrites the security model while keeping the same simple UX. Key differences from Pinterest's original:

**Zero-knowledge architecture** - Encryption moved from server-side (Python/Fernet) to client-side (browser/AES-256-GCM via Web Crypto API). The server only stores and serves opaque encrypted blobs. Decryption keys live in the URL fragment (`#key`), which browsers never send to the server per RFC 3986. This means:

- The server cannot decrypt your secrets, even if compromised
- Decryption keys don't appear in server logs, proxy logs, or access logs
- Redis contains only ciphertext that is useless without the URL fragment

**Security hardening** - Response headers (CSP, X-Frame-Options, Referrer-Policy, etc.), per-endpoint rate limiting, input size validation (10KB max), and a randomized `SECRET_KEY` default.

**Modernized stack** - Python 3.12, Flask 3.1, `pyproject.toml` packaging. Removed all vendored EOL libraries: Bootstrap 3, jQuery, Font Awesome 4, Clipboard.js (over 1MB of dead weight). Replaced with ~300 lines of vanilla CSS and JS with the same dark theme.

**New API** - The v1 and v2 APIs accepted and returned plaintext, which is incompatible with zero-knowledge. They've been replaced by a v3 API that works with pre-encrypted ciphertext. See [API v3](#api-v3) below.

## How It Works

**Creating a secret:**

1. You type a secret and pick an expiration time
2. Your browser encrypts the secret with a random AES-256-GCM key (Web Crypto API)
3. The browser sends only the encrypted blob and TTL to the server
4. The server stores the blob in Redis and returns a storage key
5. Your browser constructs the share link: `https://host/{storage_key}#{crypto_key}`
6. The `#crypto_key` fragment never leaves your browser

**Revealing a secret:**

1. Recipient opens the link and sees a "Reveal secret" button
2. Clicking it sends a POST to the server (without the `#fragment`)
3. The server returns the encrypted blob and deletes it from Redis
4. The browser decrypts using the key from the URL fragment
5. The plaintext is displayed. Refreshing the page shows "not found".

## Requirements

- Redis or compatible (valkey bundeled in helm-snappass)
- Python 3.10+
- HTTPS (required for Web Crypto API - use a reverse proxy, Cloudflare Tunnel, etc.)

## Installation

```
$ pip install snappass
$ snappass
* Running on http://0.0.0.0:5000/
```

## Docker

```
$ docker compose up -d
```

This starts SnapPass and Redis. The app is accessible at http://localhost:5000.

Pre-built multi-arch images (amd64/arm64) are available:

- `lmacka/snappass:latest` - latest release
- `lmacka/snappass:dev` - latest dev branch build
- `ghcr.io/lmacka/snappass:latest` - same, from GitHub Container Registry

## Kubernetes (Helm)

The recommended method for production deployments:

```
$ helm repo add snappass https://lmacka.github.io/helm-snappass/
$ helm install snappass snappass/snappass
```

Deploys SnapPass with a bundled Valkey (Redis-compatible) instance. See the [Helm chart documentation](https://github.com/lmacka/helm-snappass) for ingress, TLS, external Redis, autoscaling, and other options.

## Configuration

All configuration is via environment variables. Start by ensuring Redis is running.

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Signs Flask sessions. If unset, a random key is generated on startup. | random |
| `REDIS_URL` | Full Redis connection URL. Takes precedence over host/port/db. Example: `redis://user:pass@localhost:6379/0` | - |
| `REDIS_HOST` | Redis hostname | `localhost` |
| `REDIS_PORT` | Redis port | `6379` |
| `REDIS_PASSWORD` | Redis authentication password | `None` |
| `SNAPPASS_REDIS_DB` | Redis database number | `0` |
| `REDIS_PREFIX` | Prefix for Redis keys to prevent collisions | `snappass` |
| `NO_SSL` | Set to `True` if not using SSL | `False` |
| `URL_PREFIX` | Path prefix when behind a reverse proxy. Example: `/snappass/` | - |
| `HOST_OVERRIDE` | Override the base URL. Useful behind reverse proxies or SSO. | - |
| `SNAPPASS_BIND_ADDRESS` | Bind address | `0.0.0.0` |
| `SNAPPASS_PORT` | Port | `5000` |
| `GUNICORN_WORKERS` | Number of gunicorn workers | `3` |
| `DEBUG` | Enable Flask debug mode | - |
| `STATIC_URL` | Location of static assets | `static` |

## API v3

The v3 API is zero-knowledge: it accepts and returns pre-encrypted ciphertext. Your application is responsible for encryption and decryption using any algorithm you choose.

The previous v1 (`/api/set_password/`) and v2 (`/api/v2/passwords`) APIs have been removed because they accepted plaintext secrets, which is incompatible with the zero-knowledge architecture.

### Store a secret

```
$ curl -X POST -H "Content-Type: application/json" \
    -d '{"ciphertext": "BASE64_ENCRYPTED_DATA", "ttl": 3600}' \
    https://localhost:5000/api/v3/secrets
```

Response (`201 Created`):

```json
{
    "key": "snappass1a2b3c4d5e6f...",
    "ttl": 3600
}
```

The default TTL is 2 weeks (1209600 seconds). Maximum TTL is also 2 weeks. Maximum ciphertext size is 10KB.

### Check if a secret exists

```
$ curl --head https://localhost:5000/api/v3/secrets/snappass1a2b3c4d5e6f...
```

Returns `200 OK` if the secret exists, `404 Not Found` otherwise. This does not consume the secret.

### Retrieve a secret

```
$ curl https://localhost:5000/api/v3/secrets/snappass1a2b3c4d5e6f...
```

Response (`200 OK`):

```json
{
    "ciphertext": "BASE64_ENCRYPTED_DATA"
}
```

This is a one-time retrieval - the secret is deleted from the server immediately. Subsequent requests return `404`.

### Example: full lifecycle with Python

```python
import base64, json, os, requests
from cryptography.fernet import Fernet

# Encrypt client-side
key = Fernet.generate_key()
ciphertext = Fernet(key).encrypt(b"hunter2").decode()

# Store
r = requests.post("https://snappass.example.com/api/v3/secrets",
                   json={"ciphertext": ciphertext, "ttl": 3600})
storage_key = r.json()["key"]

# Retrieve and decrypt
r = requests.get(f"https://snappass.example.com/api/v3/secrets/{storage_key}")
plaintext = Fernet(key).decrypt(r.json()["ciphertext"].encode())
print(plaintext.decode())  # "hunter2"
```

### Example: full lifecycle with curl + openssl

```bash
# Generate a key and encrypt
KEY=$(openssl rand -base64 32)
CIPHERTEXT=$(echo -n "hunter2" | openssl enc -aes-256-cbc -base64 -pass pass:$KEY 2>/dev/null)

# Store
STORAGE_KEY=$(curl -s -X POST -H "Content-Type: application/json" \
    -d "{\"ciphertext\": \"$CIPHERTEXT\", \"ttl\": 3600}" \
    https://snappass.example.com/api/v3/secrets | jq -r .key)

# Retrieve and decrypt
curl -s https://snappass.example.com/api/v3/secrets/$STORAGE_KEY \
    | jq -r .ciphertext | openssl enc -aes-256-cbc -d -base64 -pass pass:$KEY 2>/dev/null
```

## Health Check

```
$ curl https://localhost:5000/_/_/health
```

Returns `200 OK` with `{}` if the app and Redis are healthy.

## Internationalization

SnapPass supports English, German, Spanish, Dutch, and French via Flask-Babel. The language is selected automatically from the browser's `Accept-Language` header.

To update translations:

```
$ pybabel extract -F babel.cfg -o messages.pot .
$ pybabel update -i messages.pot -d snappass/translations
$ pybabel compile -d snappass/translations
```

## Development

```
$ pip install -r dev-requirements.txt
$ MOCK_REDIS=1 pytest tests.py -v
```

Tests use `fakeredis` so no Redis server is needed. Time-dependent tests use `freezegun`.

Lint:

```
$ flake8 --max-line-length=120
```

CI runs tests across Python 3.10, 3.11, and 3.12 via tox.

## Contributing

Development happens on the `dev` branch. Push to `dev` builds a `dev`-tagged Docker image automatically.

**Patch releases** are automated. Merge a PR to `master` with the `release` label (or from dependabot) and the pipeline will:

1. Bump the patch version in `snappass/__init__.py` and `pyproject.toml`
2. Commit, tag, and push to `master`
3. Build and push multi-arch Docker images
4. Dispatch to [helm-snappass](https://github.com/lmacka/helm-snappass) to auto-bump the chart

**Minor or major releases** require a manual version bump before merging:

1. Update `snappass/__init__.py` (`__version__`) and `pyproject.toml` (`version`)
2. Merge the PR to `master` **without** the `release` label (to skip the auto-bump)
3. Tag manually: `git tag v<version> && git push origin master --tags`

The tag push triggers the same Docker build and GitHub release as the auto pipeline.

## Origins

Originally built at [Pinterest](https://github.com/pinterest/snappass).
