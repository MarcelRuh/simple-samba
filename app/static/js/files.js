(function () {
  'use strict';

  if (!window.FILES_BOOT) return;

  var shareSelect = document.getElementById('files-share-select');
  var breadcrumb = document.getElementById('files-breadcrumb');
  var tbody = document.getElementById('files-tbody');
  var loadingEl = document.getElementById('files-loading');
  var errorEl = document.getElementById('files-error');
  var emptyEl = document.getElementById('files-empty');
  var metaEl = document.getElementById('files-meta');
  var uploadInput = document.getElementById('files-upload-input');
  var uploadLabel = document.getElementById('files-upload-label');
  var mkdirBtn = document.getElementById('files-mkdir-btn');
  var refreshBtn = document.getElementById('files-refresh-btn');

  var currentShare = '';
  var currentPath = '';
  var readOnly = false;

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function selectedShare() {
    var opt = shareSelect.options[shareSelect.selectedIndex];
    return {
      name: opt.value,
      path: opt.getAttribute('data-path') || '',
      readOnly: opt.getAttribute('data-readonly') === '1',
    };
  }

  function formatSize(bytes) {
    if (bytes === 0) return '0 B';
    var units = ['B', 'KB', 'MB', 'GB', 'TB'];
    var i = 0;
    var size = bytes;
    while (size >= 1024 && i < units.length - 1) {
      size /= 1024;
      i += 1;
    }
    return (i === 0 ? size : size.toFixed(size >= 10 ? 0 : 1)) + ' ' + units[i];
  }

  function formatTime(ts) {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleString('de-DE');
  }

  function setWriteControls() {
    var disabled = readOnly;
    uploadLabel.classList.toggle('disabled', disabled);
    uploadInput.disabled = disabled;
    mkdirBtn.disabled = disabled;
  }

  function showError(msg) {
    errorEl.hidden = !msg;
    errorEl.textContent = msg || '';
  }

  function renderBreadcrumb(data) {
    breadcrumb.innerHTML = '';
    var root = document.createElement('button');
    root.type = 'button';
    root.className = 'files-crumb';
    root.textContent = currentShare;
    root.addEventListener('click', function () { loadBrowse(''); });
    breadcrumb.appendChild(root);

    if (!data.rel_path) return;

    var parts = data.rel_path.split('/').filter(Boolean);
    var acc = '';
    parts.forEach(function (part, idx) {
      var sep = document.createElement('span');
      sep.className = 'files-crumb-sep';
      sep.textContent = '/';
      breadcrumb.appendChild(sep);

      acc = acc ? acc + '/' + part : part;
      var isLast = idx === parts.length - 1;
      if (isLast) {
        var span = document.createElement('span');
        span.className = 'files-crumb-current';
        span.textContent = part;
        breadcrumb.appendChild(span);
      } else {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'files-crumb';
        btn.textContent = part;
        (function (path) {
          btn.addEventListener('click', function () { loadBrowse(path); });
        })(acc);
        breadcrumb.appendChild(btn);
      }
    });
  }

  function renderTable(data) {
    tbody.innerHTML = '';
    var entries = data.entries || [];

    if (data.rel_path) {
      var up = document.createElement('tr');
      up.innerHTML =
        '<td colspan="4"><button type="button" class="btn btn-ghost btn-sm files-up-btn">↩ Zurück</button></td>';
      up.querySelector('button').addEventListener('click', function () {
        loadBrowse(data.parent_rel || '');
      });
      tbody.appendChild(up);
    }

    entries.forEach(function (entry) {
      var tr = document.createElement('tr');
      var nameCell = document.createElement('td');
      var sizeCell = document.createElement('td');
      var timeCell = document.createElement('td');
      var actionCell = document.createElement('td');
      actionCell.className = 'actions-cell';

      if (entry.type === 'dir') {
        var dirBtn = document.createElement('button');
        dirBtn.type = 'button';
        dirBtn.className = 'files-entry-dir';
        dirBtn.textContent = entry.name + '/';
        dirBtn.addEventListener('click', function () {
          var next = data.rel_path ? data.rel_path + '/' + entry.name : entry.name;
          loadBrowse(next);
        });
        nameCell.appendChild(dirBtn);
        sizeCell.textContent = '—';
      } else {
        nameCell.innerHTML = '<code>' + entry.name + '</code>';
        sizeCell.textContent = formatSize(entry.size || 0);

        var dl = document.createElement('a');
        dl.className = 'btn btn-secondary btn-sm';
        dl.textContent = 'Download';
        dl.href = '/api/files/download?share=' + encodeURIComponent(currentShare) +
          '&path=' + encodeURIComponent((data.rel_path ? data.rel_path + '/' : '') + entry.name);
        actionCell.appendChild(dl);
      }

      timeCell.textContent = formatTime(entry.mtime);

      if (!readOnly) {
        var del = document.createElement('button');
        del.type = 'button';
        del.className = 'btn btn-danger btn-sm';
        del.textContent = 'Löschen';
        del.style.marginLeft = '0.35rem';
        (function (entryName, entryType) {
          del.addEventListener('click', function () {
            var rel = data.rel_path ? data.rel_path + '/' + entryName : entryName;
            var label = entryType === 'dir' ? 'Ordner' : 'Datei';
            window.SambaUI.confirm(
              label + ' löschen',
              '"' + entryName + '" wirklich löschen?',
              'Löschen'
            ).then(function (ok) {
              if (!ok) return;
              apiPost('/api/files/delete', { share: currentShare, path: rel })
                .then(function () {
                  showToast('Gelöscht.', 'success');
                  loadBrowse(currentPath);
                })
                .catch(showApiError);
            });
          });
        })(entry.name, entry.type);
        actionCell.appendChild(del);
      }

      tr.appendChild(nameCell);
      tr.appendChild(sizeCell);
      tr.appendChild(timeCell);
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    });

    emptyEl.hidden = entries.length > 0 || !!data.rel_path;
    metaEl.textContent = data.path || '';
  }

  function showApiError(err) {
    var msg = (err && err.message) ? err.message : 'Unbekannter Fehler';
    showError(msg);
    showToast(msg, 'error');
  }

  function apiPost(url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': csrfToken(),
      },
      body: JSON.stringify(body),
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || 'Anfrage fehlgeschlagen');
        return data;
      });
    });
  }

  function loadBrowse(path) {
    currentPath = path || '';
    showError('');
    loadingEl.hidden = false;
    emptyEl.hidden = true;

    var url = '/api/files/browse?share=' + encodeURIComponent(currentShare) +
      '&path=' + encodeURIComponent(currentPath);

    fetch(url, { credentials: 'same-origin' })
      .then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok) throw new Error(data.error || 'Laden fehlgeschlagen');
          return data;
        });
      })
      .then(function (data) {
        readOnly = !!data.read_only;
        setWriteControls();
        renderBreadcrumb(data);
        renderTable(data);
      })
      .catch(showApiError)
      .finally(function () { loadingEl.hidden = true; });
  }

  function uploadFiles(fileList) {
    if (!fileList || !fileList.length || readOnly) return;
    var pending = Array.prototype.slice.call(fileList);
    var uploadNext = function () {
      if (!pending.length) {
        showToast('Upload abgeschlossen.', 'success');
        loadBrowse(currentPath);
        return;
      }
      var file = pending.shift();
      var form = new FormData();
      form.append('csrf_token', csrfToken());
      form.append('share', currentShare);
      form.append('path', currentPath);
      form.append('file', file, file.name);
      fetch('/api/files/upload', { method: 'POST', credentials: 'same-origin', body: form })
        .then(function (res) {
          return res.json().then(function (data) {
            if (!res.ok) throw new Error(data.error || 'Upload fehlgeschlagen');
            return data;
          });
        })
        .then(uploadNext)
        .catch(showApiError);
    };
    uploadNext();
  }

  shareSelect.addEventListener('change', function () {
    var s = selectedShare();
    currentShare = s.name;
    readOnly = s.readOnly;
    setWriteControls();
    loadBrowse('');
  });

  uploadInput.addEventListener('change', function () {
    uploadFiles(uploadInput.files);
    uploadInput.value = '';
  });

  mkdirBtn.addEventListener('click', function () {
    if (readOnly) return;
    var name = window.prompt('Name des neuen Ordners:');
    if (!name) return;
    apiPost('/api/files/mkdir', { share: currentShare, path: currentPath, name: name })
      .then(function () {
        showToast('Ordner erstellt.', 'success');
        loadBrowse(currentPath);
      })
      .catch(showApiError);
  });

  refreshBtn.addEventListener('click', function () { loadBrowse(currentPath); });

  var initial = selectedShare();
  currentShare = initial.name;
  readOnly = initial.readOnly;
  setWriteControls();
  loadBrowse('');
})();
