'use strict';

(function () {
    // Copy to clipboard
    function copyToClipboard(text, button) {
        navigator.clipboard.writeText(text).then(function () {
            var original = button.textContent;
            button.textContent = 'Copied!';
            setTimeout(function () { button.textContent = original; }, 2000);
        });
    }

    // Create secret form handler
    var createForm = document.getElementById('password_create');
    if (createForm) {
        createForm.addEventListener('submit', function (e) {
            e.preventDefault();

            var textarea = document.getElementById('password');
            var ttlSelect = document.querySelector('select[name="ttl"]');
            var plaintext = textarea.value;
            var ttlLabel = ttlSelect.value;

            var ttlMap = {
                'Two Weeks': 1209600,
                'Week': 604800,
                'Day': 86400,
                'Hour': 3600
            };
            var ttl = ttlMap[ttlLabel];
            if (!plaintext || !ttl) return;

            var submitBtn = document.getElementById('submit');
            submitBtn.disabled = true;
            submitBtn.textContent = 'Encrypting...';

            SnapPassCrypto.generateKey()
                .then(function (key) {
                    return Promise.all([
                        SnapPassCrypto.encrypt(plaintext, key),
                        SnapPassCrypto.exportKey(key)
                    ]);
                })
                .then(function (results) {
                    var ciphertext = results[0];
                    var exportedKey = results[1];

                    return fetch(window.location.pathname, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ ciphertext: ciphertext, ttl: ttl })
                    }).then(function (resp) {
                        if (!resp.ok) throw new Error('Server error: ' + resp.status);
                        return resp.json();
                    }).then(function (data) {
                        return { key: data.key, exportedKey: exportedKey };
                    });
                })
                .then(function (result) {
                    var base = window.location.origin + window.location.pathname;
                    if (base.slice(-1) !== '/') base += '/';
                    var link = base + result.key + '#' + result.exportedKey;

                    // Switch to confirm view
                    var section = document.querySelector('.content-section');
                    section.innerHTML =
                        '<div class="page-header"><h1>' + escapeHtml(document.getElementById('share-title').textContent) + '</h1></div>' +
                        '<p>' + escapeHtml(document.getElementById('share-subtitle').textContent) + '</p>' +
                        '<div class="form-row">' +
                        '  <div class="input-wrap">' +
                        '    <input type="text" class="form-control" id="password-link" value="' + escapeAttr(link) + '" readonly>' +
                        '  </div>' +
                        '  <button type="button" class="btn btn-primary" id="copy-clipboard-btn">Copy</button>' +
                        '</div>';

                    document.getElementById('copy-clipboard-btn').addEventListener('click', function () {
                        copyToClipboard(link, this);
                    });
                })
                .catch(function (err) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Generate URL';
                    alert('Error: ' + err.message);
                });
        });
    }

    // Reveal secret handler
    var revealBtn = document.getElementById('revealSecret');
    if (revealBtn) {
        revealBtn.addEventListener('click', function () {
            var fragment = window.location.hash.slice(1);
            if (!fragment) {
                showError('Invalid link: missing decryption key.');
                return;
            }

            revealBtn.disabled = true;
            revealBtn.textContent = 'Decrypting...';

            fetch(window.location.pathname, {
                method: 'POST',
                headers: { 'Accept': 'application/json' }
            })
            .then(function (resp) {
                if (!resp.ok) {
                    if (resp.status === 404) {
                        throw new Error('expired');
                    }
                    throw new Error('Server error: ' + resp.status);
                }
                return resp.json();
            })
            .then(function (data) {
                return SnapPassCrypto.importKey(fragment)
                    .then(function (key) {
                        return SnapPassCrypto.decrypt(data.ciphertext, key);
                    });
            })
            .then(function (plaintext) {
                var section = document.querySelector('.content-section');
                section.innerHTML =
                    '<div class="page-header"><h1>' + escapeHtml(document.getElementById('secret-title').textContent) + '</h1></div>' +
                    '<p>' + escapeHtml(document.getElementById('save-prompt').textContent) + '</p>' +
                    '<div class="form-row">' +
                    '  <div class="input-wrap">' +
                    '    <textarea class="form-control" rows="10" id="password-text" readonly>' + escapeHtml(plaintext) + '</textarea>' +
                    '  </div>' +
                    '  <button type="button" class="btn btn-primary" id="copy-clipboard-btn">Copy</button>' +
                    '</div>' +
                    '<p>' + escapeHtml(document.getElementById('deleted-notice').textContent) + '</p>';

                document.getElementById('copy-clipboard-btn').addEventListener('click', function () {
                    copyToClipboard(document.getElementById('password-text').value, this);
                });
            })
            .catch(function (err) {
                if (err.message === 'expired') {
                    window.location.reload();
                    return;
                }
                showError('Failed to decrypt. The link may be invalid or corrupted.');
            });
        });
    }

    // Clipboard button for static pages
    var staticCopyBtn = document.getElementById('copy-clipboard-btn');
    if (staticCopyBtn && !createForm && !revealBtn) {
        staticCopyBtn.addEventListener('click', function () {
            var target = document.querySelector(staticCopyBtn.dataset.clipboardTarget);
            if (target) copyToClipboard(target.value || target.textContent, staticCopyBtn);
        });
    }

    function showError(msg) {
        var section = document.querySelector('.content-section');
        if (section) {
            section.innerHTML =
                '<div class="page-header"><h1>Error</h1></div>' +
                '<p class="error-text">' + escapeHtml(msg) + '</p>';
        }
    }

    function escapeHtml(str) {
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    function escapeAttr(str) {
        return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
                  .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
})();
