import unittest
from unittest import TestCase

from freezegun import freeze_time

# noinspection PyPep8Naming
import snappass.main as snappass


class SnapPassCoreTestCase(TestCase):

    def test_store_and_retrieve_secret(self):
        ciphertext = b'encrypted-blob-data'
        key = snappass.store_secret(ciphertext, 30)
        result = snappass.retrieve_secret(key)
        self.assertEqual(ciphertext, result)

    def test_retrieve_deletes_from_redis(self):
        ciphertext = b'one-time-data'
        key = snappass.store_secret(ciphertext, 30)
        self.assertIsNotNone(snappass.retrieve_secret(key))
        self.assertIsNone(snappass.retrieve_secret(key))

    def test_secret_exists(self):
        ciphertext = b'check-existence'
        key = snappass.store_secret(ciphertext, 30)
        self.assertTrue(snappass.secret_exists(key))
        snappass.retrieve_secret(key)
        self.assertFalse(snappass.secret_exists(key))

    def test_ciphertext_stored_as_is(self):
        ciphertext = b'opaque-encrypted-content'
        key = snappass.store_secret(ciphertext, 30)
        stored = snappass.redis_client.get(key)
        self.assertEqual(ciphertext, stored)

    @freeze_time("2020-05-08 12:00:00")
    def test_secret_before_expiration(self):
        ciphertext = b'time-test'
        key = snappass.store_secret(ciphertext, 30)
        self.assertEqual(ciphertext, snappass.retrieve_secret(key))

    @freeze_time("2020-05-08 12:00:00", auto_tick_seconds=2)
    def test_secret_after_expiration(self):
        ciphertext = b'expiring-data'
        key = snappass.store_secret(ciphertext, 1)
        # auto_tick_seconds=2 means next call is 2 seconds later
        self.assertIsNone(snappass.retrieve_secret(key))


class SnapPassRoutesTestCase(TestCase):

    def setUp(self):
        snappass.app.config['TESTING'] = True
        self.app = snappass.app.test_client()

    def test_health_check(self):
        response = self.app.get('/_/_/health')
        self.assertEqual(200, response.status_code)

    def test_index_page(self):
        response = self.app.get('/')
        self.assertEqual(200, response.status_code)

    def test_create_secret_returns_key(self):
        rv = self.app.post(
            '/',
            json={'ciphertext': 'encrypted-data', 'ttl': 3600},
            content_type='application/json',
        )
        self.assertEqual(200, rv.status_code)
        data = rv.get_json()
        self.assertIn('key', data)
        self.assertTrue(data['key'].startswith(snappass.REDIS_PREFIX))

    def test_create_secret_missing_ciphertext(self):
        rv = self.app.post(
            '/',
            json={'ttl': 3600},
            content_type='application/json',
        )
        self.assertEqual(400, rv.status_code)

    def test_create_secret_missing_ttl(self):
        rv = self.app.post(
            '/',
            json={'ciphertext': 'data'},
            content_type='application/json',
        )
        self.assertEqual(400, rv.status_code)

    def test_create_secret_negative_ttl(self):
        rv = self.app.post(
            '/',
            json={'ciphertext': 'data', 'ttl': -1},
            content_type='application/json',
        )
        self.assertEqual(400, rv.status_code)

    def test_create_secret_excessive_ttl(self):
        rv = self.app.post(
            '/',
            json={'ciphertext': 'data', 'ttl': 99999999},
            content_type='application/json',
        )
        self.assertEqual(400, rv.status_code)

    def test_create_secret_oversized_ciphertext(self):
        big_data = 'x' * (snappass.MAX_CIPHERTEXT_SIZE + 1)
        rv = self.app.post(
            '/',
            json={'ciphertext': big_data, 'ttl': 3600},
            content_type='application/json',
        )
        self.assertEqual(413, rv.status_code)

    def test_preview_existing_secret(self):
        key = snappass.store_secret(b'preview-test', 30)
        rv = self.app.get(f'/{key}')
        self.assertEqual(200, rv.status_code)
        self.assertNotIn(b'preview-test', rv.data)

    def test_preview_nonexistent_secret(self):
        rv = self.app.get('/snappassnonexistent')
        self.assertEqual(404, rv.status_code)

    def test_reveal_returns_ciphertext(self):
        key = snappass.store_secret(b'reveal-blob', 30)
        rv = self.app.post(f'/{key}')
        self.assertEqual(200, rv.status_code)
        data = rv.get_json()
        self.assertEqual('reveal-blob', data['ciphertext'])

    def test_reveal_deletes_secret(self):
        key = snappass.store_secret(b'one-time', 30)
        rv = self.app.post(f'/{key}')
        self.assertEqual(200, rv.status_code)
        rv2 = self.app.post(f'/{key}')
        self.assertEqual(404, rv2.status_code)

    def test_reveal_nonexistent_returns_404(self):
        rv = self.app.post('/snappassnonexistent')
        self.assertEqual(404, rv.status_code)

    def test_old_tilde_token_rejected(self):
        """Tokens with ~ (old format) should not match any route or be valid keys."""
        rv = self.app.get('/snappassfake~oldkey')
        self.assertEqual(404, rv.status_code)


class SnapPassSecurityTestCase(TestCase):

    def setUp(self):
        snappass.app.config['TESTING'] = True
        self.app = snappass.app.test_client()

    def test_security_headers_present(self):
        rv = self.app.get('/')
        self.assertEqual('DENY', rv.headers.get('X-Frame-Options'))
        self.assertEqual('nosniff', rv.headers.get('X-Content-Type-Options'))
        self.assertEqual('no-referrer', rv.headers.get('Referrer-Policy'))
        self.assertIn('camera=()', rv.headers.get('Permissions-Policy'))
        self.assertIn("default-src 'self'", rv.headers.get('Content-Security-Policy'))
        self.assertIn("frame-ancestors 'none'", rv.headers.get('Content-Security-Policy'))

    def test_security_headers_on_api(self):
        rv = self.app.post(
            '/api/v3/secrets',
            json={'ciphertext': 'test', 'ttl': 3600},
            content_type='application/json',
        )
        self.assertEqual('no-referrer', rv.headers.get('Referrer-Policy'))

    def test_security_headers_on_404(self):
        rv = self.app.get('/snappassnonexistent')
        self.assertEqual('DENY', rv.headers.get('X-Frame-Options'))


class SnapPassAPIv3TestCase(TestCase):

    def setUp(self):
        snappass.app.config['TESTING'] = True
        self.app = snappass.app.test_client()

    def test_create_secret(self):
        rv = self.app.post(
            '/api/v3/secrets',
            json={'ciphertext': 'encrypted-payload', 'ttl': 3600},
            content_type='application/json',
        )
        self.assertEqual(201, rv.status_code)
        data = rv.get_json()
        self.assertIn('key', data)
        self.assertEqual(3600, data['ttl'])

    def test_create_secret_default_ttl(self):
        rv = self.app.post(
            '/api/v3/secrets',
            json={'ciphertext': 'encrypted-payload'},
            content_type='application/json',
        )
        self.assertEqual(201, rv.status_code)
        data = rv.get_json()
        self.assertEqual(snappass.DEFAULT_API_TTL, data['ttl'])

    def test_create_secret_no_ciphertext(self):
        rv = self.app.post(
            '/api/v3/secrets',
            json={'ciphertext': ''},
            content_type='application/json',
        )
        self.assertEqual(400, rv.status_code)

    def test_create_secret_excessive_ttl(self):
        rv = self.app.post(
            '/api/v3/secrets',
            json={'ciphertext': 'data', 'ttl': 99999999},
            content_type='application/json',
        )
        self.assertEqual(400, rv.status_code)

    def test_check_secret_exists(self):
        rv = self.app.post(
            '/api/v3/secrets',
            json={'ciphertext': 'check-me', 'ttl': 3600},
            content_type='application/json',
        )
        key = rv.get_json()['key']

        rv2 = self.app.head(f'/api/v3/secrets/{key}')
        self.assertEqual(200, rv2.status_code)

    def test_check_secret_not_found(self):
        rv = self.app.head('/api/v3/secrets/snappassnonexistent')
        self.assertEqual(404, rv.status_code)

    def test_retrieve_secret(self):
        rv = self.app.post(
            '/api/v3/secrets',
            json={'ciphertext': 'retrieve-me', 'ttl': 3600},
            content_type='application/json',
        )
        key = rv.get_json()['key']

        rv2 = self.app.get(f'/api/v3/secrets/{key}')
        self.assertEqual(200, rv2.status_code)
        self.assertEqual('retrieve-me', rv2.get_json()['ciphertext'])

    def test_retrieve_secret_deletes(self):
        rv = self.app.post(
            '/api/v3/secrets',
            json={'ciphertext': 'one-time', 'ttl': 3600},
            content_type='application/json',
        )
        key = rv.get_json()['key']

        self.app.get(f'/api/v3/secrets/{key}')
        rv2 = self.app.get(f'/api/v3/secrets/{key}')
        self.assertEqual(404, rv2.status_code)

    def test_retrieve_secret_not_found(self):
        rv = self.app.get('/api/v3/secrets/snappassnonexistent')
        self.assertEqual(404, rv.status_code)

    def test_full_lifecycle(self):
        """Create, check exists, retrieve, verify gone."""
        # Create
        rv = self.app.post(
            '/api/v3/secrets',
            json={'ciphertext': 'lifecycle-test', 'ttl': 3600},
            content_type='application/json',
        )
        self.assertEqual(201, rv.status_code)
        key = rv.get_json()['key']

        # Check exists
        rv2 = self.app.head(f'/api/v3/secrets/{key}')
        self.assertEqual(200, rv2.status_code)

        # Retrieve
        rv3 = self.app.get(f'/api/v3/secrets/{key}')
        self.assertEqual(200, rv3.status_code)
        self.assertEqual('lifecycle-test', rv3.get_json()['ciphertext'])

        # Verify gone
        rv4 = self.app.head(f'/api/v3/secrets/{key}')
        self.assertEqual(404, rv4.status_code)

        rv5 = self.app.get(f'/api/v3/secrets/{key}')
        self.assertEqual(404, rv5.status_code)


if __name__ == '__main__':
    unittest.main()
