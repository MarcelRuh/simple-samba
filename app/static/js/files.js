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
  var dlProgressEl = document.getElementById('files-download-progress');
  var dlProgressBar = document.getElementById('files-download-progress-bar');
  var dlProgressText = document.getElementById('files-download-progress-text');
  var dlCancelBtn = document.getElementById('files-download-cancel-btn');
  var contentEl = document.getElementById('files-content');
  var dropOverlay = document.getElementById('files-drop-overlay');

  var currentShare = '';
  var currentPath = '';
  var readOnly = false;
  var viewMode = 'grid';
  var lastData = null;
  var searchQuery = '';
  var sortMode = 'name';
  var downloadBusy = false;
  var uploadBusy = false;
  var dragDepth = 0;
  var downloadTransferXhr = null;
  var downloadCancelled = false;

  var IMAGE_EXT = /\.(png|jpe?g|gif|webp|svg|bmp|ico)$/i;

  function csrfToken() {
    return window.SambaUI ? window.SambaUI.csrfToken() : '';
  }

  function formatSize(bytes) {
    return window.SambaUI ? window.SambaUI.formatSize(bytes) : String(bytes);
  }

  function shareByName(name) {
    var key = (name || '').toLowerCase();
    for (var i = 0; i < shares.length; i++) {
      if (shares[i].name.toLowerCase() === key) return shares[i];
    }
    return shares[0];
  }

  function estimateZipDownloadSize(manifest) {
    var files = manifest.files || [];
    var totalSize = manifest.total_size || 0;
    if (!totalSize) {
      files.forEach(function (file) {
        totalSize += file.size || 0;
      });
    }
    var fileCount = manifest.total_files || files.length;
    return totalSize + fileCount * 128 + 4096;
  }

  function transferProgressPct(loaded, total) {
    if (!total) {
      return loaded > 0 ? Math.min(20, Math.round(loaded / (5 * 1024 * 1024) * 20)) : 2;
    }
    return Math.min(99, Math.round((loaded / total) * 100));
  }

  function formatTransferProgress(loaded, total, label, fileName, speedBps) {
    var text = label + ': ' + fileName;
    if (total > 0) {
      var pct = transferProgressPct(loaded, total);
      text += ' (' + pct + '% · ' + formatSize(loaded) + ' / ' + formatSize(total) + ')';
    } else if (loaded > 0) {
      text += ' (' + formatSize(loaded) + ' …)';
    } else {
      text += ' …';
    }
    if (speedBps > 0) {
      text += ' · ' + formatSize(speedBps) + '/s';
    }
    return text;
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

  function sleep(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms); });
  }

  function DownloadAbortError() {
    this.name = 'DownloadAbortError';
    this.message = 'Download abgebrochen';
  }

  function isDownloadAbort(err) {
    return downloadCancelled || (err && err.name === 'DownloadAbortError');
  }

  function resetDownloadState() {
    downloadTransferXhr = null;
    downloadCancelled = false;
    setDownloadProgress(false);
  }

  function cancelDownload() {
    if (!downloadBusy) return;
    downloadCancelled = true;
    if (downloadTransferXhr) {
      downloadTransferXhr.abort();
      downloadTransferXhr = null;
    }
    resetDownloadState();
    if (window.showToast) showToast('Download abgebrochen.', 'success');
  }

  function setDownloadProgress(visible, pct, text) {
    if (!dlProgressEl) return;
    if (!visible) {
      dlProgressEl.setAttribute('hidden', '');
      if (dlProgressBar) dlProgressBar.style.width = '0%';
      if (dlProgressText) dlProgressText.textContent = '';
      downloadBusy = false;
      return;
    }
    dlProgressEl.removeAttribute('hidden');
    if (dlProgressBar) {
      dlProgressBar.style.width = Math.max(0, Math.min(100, pct || 0)) + '%';
    }
    if (dlProgressText) dlProgressText.textContent = text || '';
    downloadBusy = true;
  }

  function joinRel(base, part) {
    if (!base) return part;
    if (!part) return base;
    return base + '/' + part;
  }

  function fetchDownloadManifest(rel) {
    var url = '/api/files/download/manifest?share=' + encodeURIComponent(currentShare) +
      '&path=' + encodeURIComponent(rel);
    return fetch(url, { credentials: 'same-origin' }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || 'Ordnerliste fehlgeschlagen');
        return data;
      });
    });
  }

  function fetchDownloadBlob(rel) {
    return fetch(downloadUrl(rel), { credentials: 'same-origin' }).then(function (res) {
      if (!res.ok) {
        return res.json().then(function (data) {
          throw new Error(data.error || 'Download fehlgeschlagen');
        }).catch(function () {
          throw new Error('Download fehlgeschlagen');
        });
      }
      return res.blob();
    });
  }

  function canUseFolderPicker() {
    return window.isSecureContext && typeof window.showDirectoryPicker === 'function';
  }

  function folderZipUrl(rel) {
    return '/api/files/download/folder?share=' + encodeURIComponent(currentShare) +
      '&path=' + encodeURIComponent(rel);
  }

  function transferDirectDownloadFromUrl(url, fileName, opts) {
    opts = opts || {};
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      downloadTransferXhr = xhr;
      var expectedBytes = opts.expectedBytes || 0;
      var headerTotal = 0;
      var lastLoaded = 0;
      var lastTime = Date.now();
      var speedBps = 0;
      var label = opts.label || 'Download';

      xhr.open('GET', url);
      xhr.responseType = 'blob';
      xhr.onreadystatechange = function () {
        if (xhr.readyState >= 2 && !headerTotal) {
          var hdr = xhr.getResponseHeader('X-Download-Total-Bytes');
          if (hdr) headerTotal = parseInt(hdr, 10) || 0;
        }
      };
      xhr.addEventListener('progress', function (e) {
        if (isDownloadAbort()) return;
        var total = e.lengthComputable ? e.total : (headerTotal || expectedBytes);
        var loaded = e.loaded || 0;
        var now = Date.now();
        if (now - lastTime >= 500 && loaded > lastLoaded) {
          speedBps = (loaded - lastLoaded) / ((now - lastTime) / 1000);
          lastLoaded = loaded;
          lastTime = now;
        }
        setDownloadProgress(
          true,
          transferProgressPct(loaded, total),
          formatTransferProgress(loaded, total, label, fileName, speedBps)
        );
      });
      xhr.addEventListener('load', function () {
        downloadTransferXhr = null;
        if (isDownloadAbort()) {
          reject(new DownloadAbortError());
          return;
        }
        if (xhr.status >= 400) {
          reject(new Error('Download fehlgeschlagen'));
          return;
        }
        var blobUrl = URL.createObjectURL(xhr.response);
        var link = document.createElement('a');
        link.href = blobUrl;
        link.download = fileName;
        document.body.appendChild(link);
        link.click();
        link.remove();
        URL.revokeObjectURL(blobUrl);
        resolve();
      });
      xhr.addEventListener('error', function () {
        downloadTransferXhr = null;
        if (isDownloadAbort()) {
          reject(new DownloadAbortError());
          return;
        }
        reject(new Error('Download fehlgeschlagen'));
      });
      xhr.addEventListener('abort', function () {
        downloadTransferXhr = null;
        reject(new DownloadAbortError());
      });
      xhr.send();
    });
  }

  function startFolderZipDownload(rel, folderName) {
    if (downloadBusy) {
      showToast('Es läuft bereits ein Download.', 'error');
      return;
    }
    downloadCancelled = false;
    setDownloadProgress(true, 0, 'Ordner wird vorbereitet …');
    fetchDownloadManifest(rel)
      .then(function (manifest) {
        if (isDownloadAbort()) throw new DownloadAbortError();
        var expectedBytes = estimateZipDownloadSize(manifest);
        var fileCount = manifest.total_files || (manifest.files && manifest.files.length) || 0;
        setDownloadProgress(
          true,
          1,
          'ZIP wird erstellt (' + fileCount + ' Dateien, ca. ' + formatSize(expectedBytes) + ') …'
        );
        return transferDirectDownloadFromUrl(folderZipUrl(rel), folderName + '.zip', {
          expectedBytes: expectedBytes,
          label: 'Download',
        });
      })
      .then(function () {
        if (isDownloadAbort()) return;
        setDownloadProgress(true, 100, 'Download abgeschlossen');
        showToast('Ordner-Download abgeschlossen.', 'success');
      })
      .catch(function (err) {
        if (isDownloadAbort(err)) return;
        showApiError(err);
      })
      .finally(function () {
        if (downloadCancelled) {
          downloadCancelled = false;
          return;
        }
        sleep(800).then(function () { resetDownloadState(); });
      });
  }

  function writeBlobToDirectory(rootHandle, relPath, blob) {
    var parts = relPath.split('/').filter(Boolean);
    var fileName = parts.pop();
    var chain = Promise.resolve(rootHandle);
    parts.forEach(function (part) {
      chain = chain.then(function (dirHandle) {
        return dirHandle.getDirectoryHandle(part, { create: true });
      });
    });
    return chain.then(function (dirHandle) {
      return dirHandle.getFileHandle(fileName, { create: true }).then(function (fileHandle) {
        return fileHandle.createWritable().then(function (writable) {
          return writable.write(blob).then(function () {
            return writable.close();
          });
        });
      });
    });
  }

  function startFolderDownload(rel, folderName) {
    if (!canUseFolderPicker()) {
      startFolderZipDownload(rel, folderName);
      return;
    }
    if (downloadBusy) {
      showToast('Es läuft bereits ein Download.', 'error');
      return;
    }
    downloadCancelled = false;
    setDownloadProgress(true, 0, 'Ordner wird vorbereitet …');

    window.showDirectoryPicker({ mode: 'readwrite' })
      .then(function (dirHandle) {
        return dirHandle.getDirectoryHandle(folderName, { create: true });
      })
      .then(function (rootHandle) {
        if (isDownloadAbort()) throw new DownloadAbortError();
        return fetchDownloadManifest(rel).then(function (manifest) {
          return { root: rootHandle, manifest: manifest };
        });
      })
      .then(function (ctx) {
        var files = ctx.manifest.files || [];
        if (!files.length) {
          throw new Error('Der Ordner enthält keine Dateien.');
        }
        var totalBytes = ctx.manifest.total_size || 0;
        if (!totalBytes) {
          files.forEach(function (file) { totalBytes += file.size || 0; });
        }
        var loadedBytes = 0;
        var chain = Promise.resolve();
        files.forEach(function (file) {
          chain = chain.then(function () {
            if (isDownloadAbort()) throw new DownloadAbortError();
            var fileRel = joinRel(rel, file.rel);
            setDownloadProgress(
              true,
              transferProgressPct(loadedBytes, totalBytes),
              formatTransferProgress(loadedBytes, totalBytes, 'Download', file.rel, 0)
            );
            return fetchDownloadBlob(fileRel).then(function (blob) {
              return writeBlobToDirectory(ctx.root, file.rel, blob).then(function () {
                loadedBytes += file.size || blob.size || 0;
              });
            }).then(function () {
              setDownloadProgress(
                true,
                transferProgressPct(loadedBytes, totalBytes),
                formatTransferProgress(loadedBytes, totalBytes, 'Download', file.rel, 0)
              );
            });
          });
        });
        return chain;
      })
      .then(function () {
        if (isDownloadAbort()) return;
        setDownloadProgress(true, 100, 'Download abgeschlossen');
        showToast('Ordner-Download abgeschlossen.', 'success');
      })
      .catch(function (err) {
        if (isDownloadAbort(err)) return;
        if (err && err.name === 'AbortError') return;
        showApiError(err);
      })
      .finally(function () {
        if (downloadCancelled) {
          downloadCancelled = false;
          return;
        }
        sleep(800).then(function () { resetDownloadState(); });
      });
  }

  function startFileDownload(rel, displayName, fileSize) {
    if (downloadBusy) {
      showToast('Es läuft bereits ein Download.', 'error');
      return;
    }
    downloadCancelled = false;
    setDownloadProgress(true, 0, 'Download wird gestartet …');
    transferDirectDownloadFromUrl(downloadUrl(rel), displayName, {
      expectedBytes: fileSize || 0,
      label: 'Download',
    })
      .then(function () {
        if (isDownloadAbort()) return;
        setDownloadProgress(true, 100, 'Download abgeschlossen');
        showToast('Download abgeschlossen.', 'success');
      })
      .catch(function (err) {
        if (isDownloadAbort(err)) return;
        showApiError(err);
      })
      .finally(function () {
        if (downloadCancelled) {
          downloadCancelled = false;
          return;
        }
        sleep(800).then(function () { resetDownloadState(); });
      });
  }

  function transferDirectDownload(rel, fileName) {
    return transferDirectDownloadFromUrl(downloadUrl(rel), fileName);
  }

  function startDownload(rel, displayName, entryType, fileSize) {
    if (entryType === 'dir') {
      startFolderDownload(rel, displayName);
      return;
    }
    startFileDownload(rel, displayName, fileSize);
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

  function sortedEntries(data) {
    var entries = filteredEntries(data).slice();
    entries.sort(function (a, b) {
      if (sortMode === 'size') {
        if (a.type === 'dir' && b.type !== 'dir') return -1;
        if (b.type === 'dir' && a.type !== 'dir') return 1;
        var sizeA = a.type === 'dir' ? 0 : (a.size || 0);
        var sizeB = b.type === 'dir' ? 0 : (b.size || 0);
        return sizeB - sizeA || a.name.localeCompare(b.name, 'de');
      }
      if (sortMode === 'mtime') {
        return (b.mtime || 0) - (a.mtime || 0) || a.name.localeCompare(b.name, 'de');
      }
      return a.name.localeCompare(b.name, 'de');
    });
    return entries;
  }

  function updateHttpsHint() {
    var el = document.getElementById('files-download-hint');
    if (!el) return;
    if (canUseFolderPicker()) {
      el.hidden = true;
      return;
    }
    el.hidden = false;
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
    var dl = document.createElement('button');
    dl.type = 'button';
    dl.className = 'files-action-btn';
    dl.title = entry.type === 'dir' ? 'Ordner herunterladen' : 'Herunterladen';
    dl.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>';
    dl.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      startDownload(rel, entry.name, entry.type, entry.size);
    });
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
      startDownload(relPath(data, entry.name), entry.name, entry.type, entry.size);
    }
  }

  function renderGrid(data) {
    gridEl.innerHTML = '';
    var entries = sortedEntries(data);

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
    var entries = sortedEntries(data);

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

  function setLoading(active) {
    if (!loadingEl) return;
    if (active) {
      loadingEl.removeAttribute('hidden');
      loadingEl.classList.add('is-active');
    } else {
      loadingEl.setAttribute('hidden', '');
      loadingEl.classList.remove('is-active');
    }
  }

  function renderView(data) {
    setLoading(false);
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
    setLoading(true);
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
      .finally(function () { setLoading(false); });
  }

  function uploadOne(file, index, total, targetPath) {
    var uploadPath = targetPath !== undefined ? targetPath : currentPath;
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest();
      var form = new FormData();
      form.append('csrf_token', csrfToken());
      form.append('share', currentShare);
      form.append('path', uploadPath);
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

  function dirnameRel(relPath) {
    var parts = (relPath || '').replace(/\\/g, '/').split('/').filter(Boolean);
    parts.pop();
    return parts.join('/');
  }

  function joinCurrentPath(relDir) {
    if (!relDir) return currentPath;
    return currentPath ? currentPath + '/' + relDir : relDir;
  }

  function ensureRelativeDirs(relDir) {
    if (!relDir) return Promise.resolve();
    var parts = relDir.split('/').filter(Boolean);
    var chain = Promise.resolve();
    var acc = currentPath;
    parts.forEach(function (part) {
      chain = chain.then(function () {
        return apiPost('/api/files/mkdir', {
          share: currentShare,
          path: acc,
          name: part,
        }).catch(function (err) {
          var msg = (err && err.message) ? err.message : '';
          if (msg.indexOf('existiert bereits') === -1) throw err;
        });
      }).then(function () {
        acc = acc ? acc + '/' + part : part;
      });
    });
    return chain;
  }

  function readDirectory(dirEntry, prefix) {
    var reader = dirEntry.createReader();
    var collected = [];

    return new Promise(function (resolve, reject) {
      function readBatch() {
        reader.readEntries(function (entries) {
          if (!entries.length) {
            resolve(collected);
            return;
          }
          var chain = Promise.resolve();
          entries.forEach(function (entry) {
            chain = chain.then(function () {
              if (entry.isFile) {
                return new Promise(function (res, rej) {
                  entry.file(function (file) {
                    collected.push({
                      file: file,
                      relPath: prefix + '/' + file.name,
                    });
                    res();
                  }, rej);
                });
              }
              if (entry.isDirectory) {
                return readDirectory(entry, prefix + '/' + entry.name).then(function (nested) {
                  collected = collected.concat(nested);
                });
              }
              return Promise.resolve();
            });
          });
          chain.then(readBatch).catch(reject);
        }, reject);
      }
      readBatch();
    });
  }

  function processDroppedEntry(entry) {
    if (entry.isFile) {
      return new Promise(function (resolve, reject) {
        entry.file(function (file) {
          resolve([{ file: file, relPath: file.name }]);
        }, reject);
      });
    }
    if (entry.isDirectory) {
      return readDirectory(entry, entry.name);
    }
    return Promise.resolve([]);
  }

  function collectDroppedFiles(dataTransfer) {
    if (!dataTransfer) return Promise.resolve([]);

    var items = dataTransfer.items;
    if (items && items.length) {
      var entries = [];
      for (var i = 0; i < items.length; i++) {
        if (items[i].kind !== 'file') continue;
        var entry = items[i].webkitGetAsEntry && items[i].webkitGetAsEntry();
        if (entry) entries.push(entry);
      }
      if (entries.length) {
        return Promise.all(entries.map(processDroppedEntry)).then(function (groups) {
          var flat = [];
          groups.forEach(function (group) {
            flat = flat.concat(group);
          });
          return flat;
        });
      }
    }

    var files = dataTransfer.files ? Array.prototype.slice.call(dataTransfer.files) : [];
    return Promise.resolve(files.map(function (file) {
      return { file: file, relPath: file.name };
    }));
  }

  function setDropActive(active) {
    if (!contentEl) return;
    contentEl.classList.toggle('files-content--dragover', active);
    if (dropOverlay) {
      if (active) {
        dropOverlay.removeAttribute('hidden');
        dropOverlay.setAttribute('aria-hidden', 'false');
      } else {
        dropOverlay.setAttribute('hidden', '');
        dropOverlay.setAttribute('aria-hidden', 'true');
      }
    }
  }

  function uploadFileItems(items) {
    if (!items || !items.length || readOnly) return;
    if (uploadBusy) {
      if (window.showToast) showToast('Upload läuft bereits.', 'error');
      return;
    }

    uploadBusy = true;
    var total = items.length;
    if (progressEl) {
      progressEl.removeAttribute('hidden');
      progressBar.style.width = '0%';
    }

    var prepared = [];
    var chain = Promise.resolve();
    items.forEach(function (item) {
      chain = chain.then(function () {
        var relPath = (item.relPath || item.file.name || '').replace(/\\/g, '/');
        var relDir = dirnameRel(relPath);
        return ensureRelativeDirs(relDir).then(function () {
          prepared.push({
            file: item.file,
            path: joinCurrentPath(relDir),
          });
        });
      });
    });

    chain
      .then(function () {
        var uploadChain = Promise.resolve();
        prepared.forEach(function (entry, index) {
          uploadChain = uploadChain.then(function () {
            progressBar.style.width = '0%';
            return uploadOne(entry.file, index, total, entry.path);
          });
        });
        return uploadChain;
      })
      .then(function () {
        if (window.showToast) showToast('Upload abgeschlossen.', 'success');
        loadBrowse(currentPath);
      })
      .catch(showApiError)
      .finally(function () {
        uploadBusy = false;
        if (progressEl) {
          progressEl.setAttribute('hidden', '');
          progressBar.style.width = '0%';
          progressText.textContent = '';
        }
      });
  }

  function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    var items = Array.prototype.slice.call(fileList).map(function (file) {
      return { file: file, relPath: file.name };
    });
    uploadFileItems(items);
  }

  function initDragAndDrop() {
    if (!contentEl) return;

    contentEl.addEventListener('dragenter', function (e) {
      if (readOnly || uploadBusy) return;
      e.preventDefault();
      dragDepth += 1;
      setDropActive(true);
    });

    contentEl.addEventListener('dragover', function (e) {
      if (readOnly || uploadBusy) return;
      e.preventDefault();
      if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy';
    });

    contentEl.addEventListener('dragleave', function (e) {
      if (readOnly) return;
      e.preventDefault();
      dragDepth = Math.max(0, dragDepth - 1);
      if (dragDepth === 0) setDropActive(false);
    });

    contentEl.addEventListener('drop', function (e) {
      e.preventDefault();
      dragDepth = 0;
      setDropActive(false);
      if (readOnly || uploadBusy) return;
      collectDroppedFiles(e.dataTransfer)
        .then(function (items) {
          if (!items.length) return;
          uploadFileItems(items);
        })
        .catch(showApiError);
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
  if (dlCancelBtn) {
    dlCancelBtn.addEventListener('click', cancelDownload);
  }
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

  var sortSelect = document.getElementById('files-sort');
  if (sortSelect) {
    sortSelect.addEventListener('change', function () {
      sortMode = sortSelect.value || 'name';
      if (lastData) renderView(lastData);
    });
  }

  var first = shares[0];
  currentShare = first.name;
  readOnly = !!first.readOnly;
  renderSidebar();
  setWriteControls();
  updateHttpsHint();
  initDragAndDrop();
  loadBrowse('');
})();
