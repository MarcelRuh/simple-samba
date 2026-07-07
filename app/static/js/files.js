(function () {
  'use strict';

  if (!window.FILES_BOOT || !window.FILES_BOOT.shares) return;

  var shares = window.FILES_BOOT.shares;
  var shareList = document.getElementById('files-share-list');
  var breadcrumb = document.getElementById('files-breadcrumb');
  var backBtn = document.getElementById('files-back-btn');
  var gridEl = document.getElementById('files-grid');
  var listWrap = document.getElementById('files-list-wrap');
  var tbody = document.getElementById('files-tbody');
  var loadingEl = document.getElementById('files-loading');
  var emptyEl = document.getElementById('files-empty');
  var uploadInput = document.getElementById('files-upload-input');
  var uploadLabel = document.getElementById('files-upload-label');
  var mkdirBtn = document.getElementById('files-mkdir-btn');
  var refreshBtn = document.getElementById('files-refresh-btn');
  var viewToggle = document.getElementById('files-view-toggle');
  var searchInput = document.getElementById('files-search');
  var progressEl = document.getElementById('files-upload-progress');
  var progressBar = document.getElementById('files-upload-progress-bar');
  var progressText = document.getElementById('files-upload-progress-text');

  var currentShare = '';
  var currentPath = '';
  var readOnly = false;
  var viewMode = 'grid';
  var lastData = null;
  var searchQuery = '';

  var IMAGE_EXT = /\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i;

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function shareByName(name) {
    for (var i = 0; i < shares.length; i++) {
      if (shares[i].name === name) return shares[i];
    }
    return shares[0];
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

  function relPath(data, name) {
    return data.rel_path ? data.rel_path + '/' + name : name;
  }

  function downloadUrl(rel) {
    return '/api/files/download?share=' + encodeURIComponent(currentShare) +
      '&path=' + encodeURIComponent(rel);
  }

  function fileIconSvg(type) {
    if (type === 'dir') {
      return '<svg viewBox="0 0 24 24" fill="currentColor" class="files-icon-folder"><path d="M10 4H4a2 2 0 00-2 2v12a2 2 0 002 2h16a2 2 0 002-2V8a2 2 0 00-2-2h-8l-2-2z"/></svg>';
    }
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="files-icon-file"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
  }

  function isImage(name) {
    return IMAGE_EXT.test(name);
  }

  function renderSidebar() {
    shareList.innerHTML = '';
    shares.forEach(function (share) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'files-share-item' + (share.name === currentShare ? ' active' : '');
      btn.innerHTML =
        '<span class="files-share-icon" aria-hidden="true">' + fileIconSvg('dir') + '</span>' +
        '<span class="files-share-label"><span class="files-share-name">' + share.name + '</span>' +
        '<span class="files-share-path">' + share.path + '</span></span>';
      btn.addEventListener('click', function () {
        if (currentShare === share.name) return;
        currentShare = share.name;
        readOnly = !!share.readOnly;
        searchInput.value = '';
        searchQuery = '';
        renderSidebar();
        setWriteControls();
        loadBrowse('');
      });
      shareList.appendChild(btn);
    });
  }

  function renderBreadcrumb(data) {
    breadcrumb.innerHTML = '';
    backBtn.hidden = !data.rel_path;

    var home = document.createElement('button');
    home.type = 'button';
    home.className = 'files-crumb files-crumb-home';
    home.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/></svg>';
    home.title = currentShare;
    home.addEventListener('click', function () { loadBrowse(''); });
    breadcrumb.appendChild(home);

    var sep = document.createElement('span');
    sep.className = 'files-crumb-sep';
    sep.textContent = currentShare;
    breadcrumb.appendChild(sep);

    if (!data.rel_path) return;

    var parts = data.rel_path.split('/').filter(Boolean);
    var acc = '';
    parts.forEach(function (part, idx) {
      var chevron = document.createElement('span');
      chevron.className = 'files-crumb-chevron';
      chevron.textContent = '›';
      breadcrumb.appendChild(chevron);

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

  function filteredEntries(data) {
    var entries = data.entries || [];
    if (!searchQuery) return entries;
    var q = searchQuery.toLowerCase();
    return entries.filter(function (e) {
      return e.name.toLowerCase().indexOf(q) !== -1;
    });
  }

  function confirmDelete(entryName, entryType, rel) {
    var label = entryType === 'dir' ? 'Ordner' : 'Datei';
    window.SambaUI.confirm(
      '"' + entryName + '" wirklich löschen?',
      { title: label + ' löschen', okLabel: 'Löschen', danger: true }
    ).then(function (ok) {
      if (!ok) return;
      apiPost('/api/files/delete', { share: currentShare, path: rel })
        .then(function () {
          showToast('Gelöscht.', 'success');
          loadBrowse(currentPath);
        })
        .catch(showApiError);
    });
  }

  function buildActions(entry, data, compact) {
    var wrap = document.createElement('div');
    wrap.className = 'files-item-actions';

    var rel = relPath(data, entry.name);
    var dl = document.createElement('a');
    dl.className = 'files-action-btn';
    dl.title = entry.type === 'dir' ? 'Als ZIP herunterladen' : 'Herunterladen';
    dl.href = downloadUrl(rel);
    dl.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
    wrap.appendChild(dl);

    if (!readOnly) {
      var del = document.createElement('button');
      del.type = 'button';
      del.className = 'files-action-btn files-action-danger';
      del.title = 'Löschen';
      del.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>';
      del.addEventListener('click', function (e) {
        e.stopPropagation();
        confirmDelete(entry.name, entry.type, rel);
      });
      wrap.appendChild(del);
    }
    return wrap;
  }

  function openEntry(entry, data) {
    if (entry.type === 'dir') {
      loadBrowse(relPath(data, entry.name));
    } else {
      window.location.href = downloadUrl(relPath(data, entry.name));
    }
  }

  function renderGrid(data) {
    gridEl.innerHTML = '';
    var entries = filteredEntries(data);

    entries.forEach(function (entry) {
      var item = document.createElement('div');
      item.className = 'files-grid-item' + (entry.type === 'dir' ? ' is-dir' : ' is-file');
      item.tabIndex = 0;

      var preview = document.createElement('div');
      preview.className = 'files-grid-preview';

      if (entry.type === 'dir') {
        preview.innerHTML = fileIconSvg('dir');
      } else if (isImage(entry.name)) {
        var img = document.createElement('img');
        img.className = 'files-grid-thumb';
        img.src = downloadUrl(relPath(data, entry.name));
        img.alt = entry.name;
        img.loading = 'lazy';
        img.addEventListener('error', function () {
          preview.innerHTML = fileIconSvg('file');
        });
        preview.appendChild(img);
      } else {
        preview.innerHTML = fileIconSvg('file');
      }

      var label = document.createElement('div');
      label.className = 'files-grid-label';
      label.textContent = entry.name;
      label.title = entry.name;

      item.appendChild(preview);
      item.appendChild(label);
      item.appendChild(buildActions(entry, data, true));

      item.addEventListener('dblclick', function () { openEntry(entry, data); });
      item.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') openEntry(entry, data);
      });
      item.addEventListener('click', function (e) {
        if (e.target.closest('.files-item-actions')) return;
        if (entry.type === 'dir') openEntry(entry, data);
      });

      gridEl.appendChild(item);
    });

    emptyEl.hidden = entries.length > 0;
    gridEl.hidden = entries.length === 0 && !data.rel_path;
  }

  function renderList(data) {
    tbody.innerHTML = '';
    var entries = filteredEntries(data);

    entries.forEach(function (entry) {
      var tr = document.createElement('tr');
      tr.className = 'files-list-row';

      var nameCell = document.createElement('td');
      nameCell.className = 'files-list-name';
      var nameBtn = document.createElement('button');
      nameBtn.type = 'button';
      nameBtn.className = 'files-list-name-btn';
      nameBtn.innerHTML =
        '<span class="files-list-icon">' + fileIconSvg(entry.type) + '</span>' +
        '<span>' + entry.name + (entry.type === 'dir' ? '/' : '') + '</span>';
      nameBtn.addEventListener('click', function () { openEntry(entry, data); });
      nameCell.appendChild(nameBtn);

      var sizeCell = document.createElement('td');
      sizeCell.textContent = entry.type === 'dir' ? '—' : formatSize(entry.size || 0);

      var timeCell = document.createElement('td');
      timeCell.textContent = formatTime(entry.mtime);

      var actionCell = document.createElement('td');
      actionCell.className = 'files-list-actions';
      actionCell.appendChild(buildActions(entry, data, false));

      tr.appendChild(nameCell);
      tr.appendChild(sizeCell);
      tr.appendChild(timeCell);
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    });

    emptyEl.hidden = entries.length > 0;
    listWrap.hidden = entries.length === 0 && !data.rel_path;
  }

  function renderView(data) {
    lastData = data;
    renderBreadcrumb(data);
    if (viewMode === 'grid') {
      gridEl.hidden = false;
      listWrap.hidden = true;
      renderGrid(data);
    } else {
      gridEl.hidden = true;
      listWrap.hidden = false;
      renderList(data);
    }
  }

  function showApiError(err) {
    var msg = (err && err.message) ? err.message : 'Unbekannter Fehler';
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
    loadingEl.hidden = false;
    emptyEl.hidden = true;
    gridEl.hidden = true;
    listWrap.hidden = true;

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
        renderSidebar();
        renderView(data);
      })
      .catch(showApiError)
      .finally(function () { loadingEl.hidden = true; });
  }

  function uploadOne(file, index, total) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      var form = new FormData();
      form.append('csrf_token', csrfToken());
      form.append('share', currentShare);
      form.append('path', currentPath);
      form.append('file', file, file.name);

      xhr.upload.addEventListener('progress', function (e) {
        if (e.lengthComputable) {
          var pct = Math.round((e.loaded / e.total) * 100);
          progressBar.style.width = pct + '%';
          progressText.textContent =
            'Upload ' + (index + 1) + '/' + total + ': ' + file.name + ' (' + pct + '%)';
        } else {
          progressText.textContent =
            'Upload ' + (index + 1) + '/' + total + ': ' + file.name + ' …';
        }
      });

      xhr.addEventListener('load', function () {
        var data;
        try {
          data = JSON.parse(xhr.responseText);
        } catch (e) {
          reject(new Error('Upload fehlgeschlagen'));
          return;
        }
        if (xhr.status >= 400) {
          reject(new Error(data.error || 'Upload fehlgeschlagen'));
          return;
        }
        resolve(data);
      });
      xhr.addEventListener('error', function () {
        reject(new Error('Upload fehlgeschlagen'));
      });
      xhr.open('POST', '/api/files/upload');
      xhr.send(form);
    });
  }

  function uploadFiles(fileList) {
    if (!fileList || !fileList.length || readOnly) return;
    var files = Array.prototype.slice.call(fileList);
    var total = files.length;
    if (progressEl) {
      progressEl.hidden = false;
      progressBar.style.width = '0%';
    }

    var chain = Promise.resolve();
    files.forEach(function (file, index) {
      chain = chain.then(function () {
        progressBar.style.width = '0%';
        return uploadOne(file, index, total);
      });
    });

    chain
      .then(function () {
        showToast('Upload abgeschlossen.', 'success');
        loadBrowse(currentPath);
      })
      .catch(showApiError)
      .finally(function () {
        if (progressEl) {
          progressEl.hidden = true;
          progressBar.style.width = '0%';
          progressText.textContent = '';
        }
      });
  }

  function toggleView() {
    viewMode = viewMode === 'grid' ? 'list' : 'grid';
    viewToggle.title = viewMode === 'grid' ? 'Listenansicht' : 'Kachelansicht';
    viewToggle.querySelector('.files-view-icon-grid').hidden = viewMode !== 'grid';
    viewToggle.querySelector('.files-view-icon-list').hidden = viewMode === 'grid';
    if (lastData) renderView(lastData);
  }

  uploadInput.addEventListener('change', function () {
    uploadFiles(uploadInput.files);
    uploadInput.value = '';
  });

  mkdirBtn.addEventListener('click', function () {
    if (readOnly) return;
    window.SambaUI.prompt({
      title: 'Neuer Ordner',
      label: 'Ordnername',
      okLabel: 'Erstellen',
    }).then(function (name) {
      if (!name) return;
      if (/[\/\\]/.test(name) || name === '.' || name === '..') {
        showToast('Ungültiger Ordnername.', 'error');
        return;
      }
      apiPost('/api/files/mkdir', { share: currentShare, path: currentPath, name: name })
        .then(function () {
          showToast('Ordner erstellt.', 'success');
          loadBrowse(currentPath);
        })
        .catch(showApiError);
    });
  });

  refreshBtn.addEventListener('click', function () { loadBrowse(currentPath); });
  viewToggle.addEventListener('click', toggleView);
  backBtn.addEventListener('click', function () {
    if (lastData && lastData.parent_rel !== undefined) {
      loadBrowse(lastData.parent_rel || '');
    }
  });

  searchInput.addEventListener('input', function () {
    searchQuery = searchInput.value.trim();
    if (lastData) renderView(lastData);
  });

  var first = shares[0];
  currentShare = first.name;
  readOnly = !!first.readOnly;
  renderSidebar();
  setWriteControls();
  loadBrowse('');
})();
