'use strict';

var SnapPassCrypto = (function () {
    var ALGO = 'AES-GCM';
    var KEY_LENGTH = 256;
    var IV_LENGTH = 12;

    function getSubtle() {
        if (typeof crypto !== 'undefined' && crypto.subtle) {
            return crypto.subtle;
        }
        throw new Error('Web Crypto API not available. HTTPS is required.');
    }

    function generateKey() {
        return getSubtle().generateKey(
            { name: ALGO, length: KEY_LENGTH },
            true,
            ['encrypt', 'decrypt']
        );
    }

    function exportKey(key) {
        return getSubtle().exportKey('raw', key).then(function (raw) {
            return btoa(String.fromCharCode.apply(null, new Uint8Array(raw)))
                .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
        });
    }

    function importKey(encoded) {
        var padded = encoded.replace(/-/g, '+').replace(/_/g, '/');
        while (padded.length % 4) padded += '=';
        var raw = Uint8Array.from(atob(padded), function (c) { return c.charCodeAt(0); });
        return getSubtle().importKey(
            'raw', raw, { name: ALGO, length: KEY_LENGTH }, false, ['decrypt']
        );
    }

    function encrypt(plaintext, key) {
        var iv = crypto.getRandomValues(new Uint8Array(IV_LENGTH));
        var encoded = new TextEncoder().encode(plaintext);
        return getSubtle().encrypt({ name: ALGO, iv: iv }, key, encoded)
            .then(function (encrypted) {
                var combined = new Uint8Array(iv.length + encrypted.byteLength);
                combined.set(iv);
                combined.set(new Uint8Array(encrypted), iv.length);
                return btoa(String.fromCharCode.apply(null, combined));
            });
    }

    function decrypt(ciphertext, key) {
        var raw = Uint8Array.from(atob(ciphertext), function (c) { return c.charCodeAt(0); });
        var iv = raw.slice(0, IV_LENGTH);
        var data = raw.slice(IV_LENGTH);
        return getSubtle().decrypt({ name: ALGO, iv: iv }, key, data)
            .then(function (decrypted) {
                return new TextDecoder().decode(decrypted);
            });
    }

    return {
        generateKey: generateKey,
        exportKey: exportKey,
        importKey: importKey,
        encrypt: encrypt,
        decrypt: decrypt
    };
})();
