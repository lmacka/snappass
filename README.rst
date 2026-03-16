========
SnapPass
========

.. image:: https://img.shields.io/endpoint?url=https://artifacthub.io/badge/repository/snappass
   :target: https://artifacthub.io/packages/search?repo=snappass
   :alt: Artifact Hub

.. image:: https://github.com/lmacka/snappass/actions/workflows/ci.yml/badge.svg?branch=master
   :target: https://github.com/lmacka/snappass/actions/workflows/ci.yml
   :alt: CI

.. image:: https://img.shields.io/github/v/release/lmacka/snappass
   :target: https://github.com/lmacka/snappass/releases
   :alt: GitHub Release

.. image:: https://img.shields.io/docker/pulls/lmacka/snappass
   :target: https://hub.docker.com/r/lmacka/snappass
   :alt: Docker Pulls

A zero-knowledge, one-time secret sharing web app. Fork of `Pinterest's SnapPass <https://github.com/pinterest/snappass>`_ with major security and architecture upgrades.

Share a secret by generating a link. The recipient opens the link, reveals the secret once, and it's permanently deleted. The server never sees your plaintext — encryption and decryption happen entirely in the browser.

What Changed From Upstream
--------------------------

This fork rewrites the security model while keeping the same simple UX. Key differences from Pinterest's original:

**Zero-knowledge architecture** — Encryption moved from server-side (Python/Fernet) to client-side (browser/AES-256-GCM via Web Crypto API). The server only stores and serves opaque encrypted blobs. Decryption keys live in the URL fragment (``#key``), which browsers never send to the server per RFC 3986. This means:

- The server cannot decrypt your secrets, even if compromised
- Decryption keys don't appear in server logs, proxy logs, or access logs
- Redis contains only ciphertext that is useless without the URL fragment

**Security hardening** — Response headers (CSP, X-Frame-Options, Referrer-Policy, etc.), per-endpoint rate limiting, input size validation (10KB max), and a randomized ``SECRET_KEY`` default with a warning.

**Modernized stack** — Python 3.12, Flask 3.1, ``pyproject.toml`` packaging. Removed all vendored EOL libraries: Bootstrap 3, jQuery, Font Awesome 4, Clipboard.js (over 1MB of dead weight). Replaced with ~300 lines of vanilla CSS and JS with the same dark theme.

**New API** — The v1 and v2 APIs accepted and returned plaintext, which is incompatible with zero-knowledge. They've been replaced by a v3 API that works with pre-encrypted ciphertext. See `API v3`_ below.

How It Works
------------

**Creating a secret:**

1. You type a secret and pick an expiration time
2. Your browser encrypts the secret with a random AES-256-GCM key (Web Crypto API)
3. The browser sends only the encrypted blob and TTL to the server
4. The server stores the blob in Redis and returns a storage key
5. Your browser constructs the share link: ``https://host/{storage_key}#{crypto_key}``
6. The ``#crypto_key`` fragment never leaves your browser

**Revealing a secret:**

1. Recipient opens the link and sees a "Reveal secret" button
2. Clicking it sends a POST to the server (without the ``#fragment``)
3. The server returns the encrypted blob and deletes it from Redis
4. The browser decrypts using the key from the URL fragment
5. The plaintext is displayed. Refreshing the page shows "not found".

Requirements
------------

* `Redis`_
* Python 3.10+
* HTTPS (required for Web Crypto API — use a reverse proxy, Cloudflare Tunnel, etc.)

.. _Redis: https://redis.io/

Installation
------------

::

    $ pip install snappass
    $ snappass
    * Running on http://0.0.0.0:5000/

Docker
------

::

    $ docker compose up -d

This starts SnapPass and Redis. The app is accessible at http://localhost:5000.

Pre-built multi-arch images (amd64/arm64) are available:

- ``lmacka/snappass:latest`` — latest release
- ``lmacka/snappass:dev`` — latest dev branch build
- ``ghcr.io/lmacka/snappass:latest`` — same, from GitHub Container Registry

Configuration
-------------

All configuration is via environment variables. Start by ensuring Redis is running.

``SECRET_KEY``: Used to sign Flask sessions. If not set, a random key is generated on
startup and a warning is logged. Set this in production to persist sessions across restarts.

``REDIS_URL``: (optional) Full Redis connection URL. Takes precedence over individual host/port/db settings. Example: ``redis://username:password@localhost:6379/0``

``REDIS_HOST``: Redis hostname. Defaults to ``"localhost"``

``REDIS_PORT``: Redis port. Defaults to ``6379``

``REDIS_PASSWORD``: Redis authentication password. Defaults to ``None``

``SNAPPASS_REDIS_DB``: Redis database number. Defaults to ``0``

``REDIS_PREFIX``: (optional) Prefix for Redis keys to prevent collisions. Defaults to ``"snappass"``

``NO_SSL``: Set to ``True`` if not using SSL. Defaults to ``False``

``URL_PREFIX``: (optional) Path prefix when running behind a reverse proxy. Example: ``"/snappass/"``

``HOST_OVERRIDE``: (optional) Override the base URL. Useful behind reverse proxies or SSO. Example: ``"secrets.example.com"``

``SNAPPASS_BIND_ADDRESS``: (optional) Bind address. Defaults to ``"0.0.0.0"``

``SNAPPASS_PORT``: (optional) Port. Defaults to ``5000``

``GUNICORN_WORKERS``: (optional) Number of gunicorn workers. Defaults to ``3``

``DEBUG``: Enable Flask debug mode.

``STATIC_URL``: Location of static assets. Defaults to ``"static"``

API v3
------

The v3 API is zero-knowledge: it accepts and returns pre-encrypted ciphertext. Your application is responsible for encryption and decryption using any algorithm you choose.

The previous v1 (``/api/set_password/``) and v2 (``/api/v2/passwords``) APIs have been removed because they accepted plaintext secrets, which is incompatible with the zero-knowledge architecture.

Store a secret
^^^^^^^^^^^^^^

::

    $ curl -X POST -H "Content-Type: application/json" \
        -d '{"ciphertext": "BASE64_ENCRYPTED_DATA", "ttl": 3600}' \
        https://localhost:5000/api/v3/secrets

Response (``201 Created``):

::

    {
        "key": "snappass1a2b3c4d5e6f...",
        "ttl": 3600
    }

The default TTL is 2 weeks (1209600 seconds). Maximum TTL is also 2 weeks. Maximum ciphertext size is 10KB.

Check if a secret exists
^^^^^^^^^^^^^^^^^^^^^^^^

::

    $ curl --head https://localhost:5000/api/v3/secrets/snappass1a2b3c4d5e6f...

Returns ``200 OK`` if the secret exists, ``404 Not Found`` otherwise. This does not consume the secret.

Retrieve a secret
^^^^^^^^^^^^^^^^^

::

    $ curl https://localhost:5000/api/v3/secrets/snappass1a2b3c4d5e6f...

Response (``200 OK``):

::

    {
        "ciphertext": "BASE64_ENCRYPTED_DATA"
    }

This is a one-time retrieval — the secret is deleted from the server immediately. Subsequent requests return ``404``.

Example: full lifecycle with Python
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

::

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

Example: full lifecycle with curl + openssl
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

::

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

Health Check
------------

::

    $ curl https://localhost:5000/_/_/health

Returns ``200 OK`` with ``{}`` if the app and Redis are healthy.

Internationalization
--------------------

SnapPass supports English, German, Spanish, Dutch, and French via Flask-Babel. The language is selected automatically from the browser's ``Accept-Language`` header.

To update translations::

    $ pybabel extract -F babel.cfg -o messages.pot .
    $ pybabel update -i messages.pot -d snappass/translations
    $ pybabel compile -d snappass/translations

Development
-----------

::

    $ pip install -r dev-requirements.txt
    $ MOCK_REDIS=1 pytest tests.py -v

Tests use ``fakeredis`` so no Redis server is needed. Time-dependent tests use ``freezegun``.

Lint::

    $ flake8 --max-line-length=120

CI runs tests across Python 3.10, 3.11, and 3.12 via tox.

Origins
-------

Originally built at `Pinterest <https://github.com/pinterest/snappass>`_.
