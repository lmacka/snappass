import functools
import os
import sys
import uuid

import redis

from flask import abort, Flask, render_template, request, jsonify, make_response
from redis.exceptions import ConnectionError
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
# _ is required to get the Jinja templates translated
from flask_babel import Babel, _  # noqa: F401


def strtobool(val):
    val = str(val).lower().strip()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    if val in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    raise ValueError(f'invalid truth value {val!r}')


NO_SSL = strtobool(os.environ.get('NO_SSL', 'False'))
URL_PREFIX = os.environ.get('URL_PREFIX', None)
HOST_OVERRIDE = os.environ.get('HOST_OVERRIDE', None)

# Initialize Flask Application
app = Flask(__name__)
if os.environ.get('DEBUG'):
    app.debug = True

if os.environ.get('SECRET_KEY'):
    app.secret_key = os.environ['SECRET_KEY']
else:
    app.secret_key = os.urandom(32).hex()
    print('WARNING: SECRET_KEY not set, using random key. '
          'Sessions will not persist across restarts.', file=sys.stderr)

app.config.update(
    dict(STATIC_URL=os.environ.get('STATIC_URL', 'static')))


# Set up Babel
def get_locale():
    return request.accept_languages.best_match(['en', 'es', 'de', 'nl', 'fr'])


babel = Babel(app, locale_selector=get_locale)

# Initialize Redis
if os.environ.get('MOCK_REDIS'):
    from fakeredis import FakeStrictRedis

    redis_client = FakeStrictRedis()
elif os.environ.get('REDIS_URL'):
    redis_client = redis.StrictRedis.from_url(os.environ.get('REDIS_URL'))
else:
    redis_host = os.environ.get('REDIS_HOST', 'localhost')
    redis_port = os.environ.get('REDIS_PORT', 6379)
    redis_password = os.environ.get('REDIS_PASSWORD')
    redis_db = os.environ.get('SNAPPASS_REDIS_DB', 0)
    redis_client = redis.StrictRedis(
        host=redis_host, port=redis_port, db=redis_db, password=redis_password)
REDIS_PREFIX = os.environ.get('REDIS_PREFIX', 'snappass')

TIME_CONVERSION = {'two weeks': 1209600, 'week': 604800, 'day': 86400,
                   'hour': 3600}
DEFAULT_API_TTL = 1209600
MAX_TTL = DEFAULT_API_TTL
MAX_CIPHERTEXT_SIZE = 10240  # 10KB max


# Rate limiting — build Redis URI for limiter from available env vars
def _get_limiter_storage_uri():
    if os.environ.get('MOCK_REDIS'):
        return 'memory://'
    if os.environ.get('REDIS_URL'):
        return os.environ['REDIS_URL']
    host = os.environ.get('REDIS_HOST', 'localhost')
    port = os.environ.get('REDIS_PORT', 6379)
    password = os.environ.get('REDIS_PASSWORD')
    db = os.environ.get('SNAPPASS_REDIS_DB', 0)
    if password:
        return f'redis://:{password}@{host}:{port}/{db}'
    return f'redis://{host}:{port}/{db}'


limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    storage_uri=_get_limiter_storage_uri(),
    default_limits=[],
)


def check_redis_alive(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        try:
            redis_client.ping()
            return fn(*args, **kwargs)
        except ConnectionError:
            print('Failed to connect to redis!', file=sys.stderr)
            if fn.__name__ == 'main':
                sys.exit(1)
            else:
                return abort(500)

    return inner


def store_secret(ciphertext, ttl):
    """
    Store a pre-encrypted ciphertext blob in Redis with the specified TTL.

    Returns the storage key.
    """
    storage_key = REDIS_PREFIX + uuid.uuid4().hex
    redis_client.setex(storage_key, ttl, ciphertext)
    return storage_key


def retrieve_secret(storage_key):
    """
    Retrieve and delete a ciphertext blob from Redis.

    Returns the raw ciphertext bytes, or None if not found.
    """
    ciphertext = redis_client.get(storage_key)
    if ciphertext is not None:
        redis_client.delete(storage_key)
    return ciphertext


@check_redis_alive
def secret_exists(storage_key):
    return redis_client.exists(storage_key)


def empty(value):
    if not value:
        return True


def clean_input():
    """
    Make sure we're not getting bad data from the front end,
    format data to be machine readable
    """
    if empty(request.form.get('password', '')):
        abort(400)

    if empty(request.form.get('ttl', '')):
        abort(400)

    time_period = request.form['ttl'].lower()
    if time_period not in TIME_CONVERSION:
        abort(400)

    return TIME_CONVERSION[time_period], request.form['password']


def set_base_url(req):
    if NO_SSL:
        if HOST_OVERRIDE:
            base_url = f'http://{HOST_OVERRIDE}/'
        else:
            base_url = req.url_root
    else:
        if HOST_OVERRIDE:
            base_url = f'https://{HOST_OVERRIDE}/'
        else:
            base_url = req.url_root.replace("http://", "https://")
    if URL_PREFIX:
        base_url = base_url + URL_PREFIX.strip("/") + "/"
    return base_url


# Security headers
@app.after_request
def add_security_headers(response):
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self'; "
        "frame-ancestors 'none'"
    )
    return response


@app.route('/', methods=['GET'])
def index():
    return render_template('set_password.html')


@app.route('/', methods=['POST'])
@limiter.limit("10/minute")
def handle_password():
    """Accept pre-encrypted ciphertext from client, store in Redis, return storage key."""
    data = request.get_json(silent=True)
    if not data:
        abort(400)

    ciphertext = data.get('ciphertext', '')
    ttl_str = data.get('ttl', '')

    if not ciphertext or not ttl_str:
        abort(400)

    try:
        ttl = int(ttl_str)
    except (ValueError, TypeError):
        abort(400)

    if ttl <= 0 or ttl > MAX_TTL:
        abort(400)

    if len(ciphertext) > MAX_CIPHERTEXT_SIZE:
        abort(413)

    storage_key = store_secret(ciphertext.encode('utf-8'), ttl)
    return jsonify(key=storage_key)


@app.route('/<password_key>', methods=['GET'])
@limiter.limit("30/minute")
def preview_password(password_key):
    if not secret_exists(password_key):
        return render_template('expired.html'), 404

    return render_template('preview.html')


@app.route('/<password_key>', methods=['POST'])
@limiter.limit("30/minute")
def show_password(password_key):
    """Return ciphertext blob as JSON. Client decrypts in browser."""
    ciphertext = retrieve_secret(password_key)
    if ciphertext is None:
        return jsonify(error='not_found'), 404

    return jsonify(ciphertext=ciphertext.decode('utf-8'))


# API v3 — Zero-knowledge API
@app.route('/api/v3/secrets', methods=['POST'])
@limiter.limit("10/minute")
def api_v3_store_secret():
    data = request.get_json(silent=True)
    if not data:
        return _api_error('Request body must be JSON', 400)

    ciphertext = data.get('ciphertext', '')
    ttl = data.get('ttl', DEFAULT_API_TTL)

    errors = []
    if not ciphertext:
        errors.append({'name': 'ciphertext',
                       'reason': 'Ciphertext is required and must not be empty.'})

    try:
        ttl = int(ttl)
    except (ValueError, TypeError):
        errors.append({'name': 'ttl', 'reason': 'TTL must be an integer.'})
        ttl = None

    if ttl is not None and (ttl <= 0 or ttl > MAX_TTL):
        errors.append({'name': 'ttl',
                       'reason': f'TTL must be between 1 and {MAX_TTL} seconds.'})

    if isinstance(ciphertext, str) and len(ciphertext) > MAX_CIPHERTEXT_SIZE:
        errors.append({'name': 'ciphertext',
                       'reason': f'Ciphertext exceeds maximum size of {MAX_CIPHERTEXT_SIZE} bytes.'})

    if errors:
        return _api_validation_error(errors)

    storage_key = store_secret(ciphertext.encode('utf-8'), ttl)
    return jsonify(key=storage_key, ttl=ttl), 201


@app.route('/api/v3/secrets/<key>', methods=['HEAD'])
@limiter.limit("30/minute")
def api_v3_check_secret(key):
    if not secret_exists(key):
        return ('', 404)
    return ('', 200)


@app.route('/api/v3/secrets/<key>', methods=['GET'])
@limiter.limit("30/minute")
def api_v3_retrieve_secret(key):
    ciphertext = retrieve_secret(key)
    if ciphertext is None:
        return _api_error('Secret not found', 404)

    return jsonify(ciphertext=ciphertext.decode('utf-8'))


def _api_error(message, status_code):
    return make_response(jsonify(error=message), status_code)


def _api_validation_error(invalid_params):
    problem = {
        'title': 'Validation error',
        'invalid-params': invalid_params
    }
    response = make_response(jsonify(problem), 400)
    response.headers['Content-Type'] = 'application/problem+json'
    return response


@app.route('/_/_/health', methods=['GET'])
@check_redis_alive
@limiter.exempt
def health_check():
    return {}


@check_redis_alive
def main():
    app.run(host=os.environ.get('SNAPPASS_BIND_ADDRESS', '0.0.0.0'),
            port=os.environ.get('SNAPPASS_PORT', 5000))


if __name__ == '__main__':
    main()
