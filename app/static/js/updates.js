(function () {
  'use strict';

  var PHASE_PROGRESS = {
    start: 5,
    update: 25,
    upgrade: 65,
    autoremove: 85,
    reboot: 95,
    done: 100,
  };

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  function setProgress(phase) {
    var fill = document.getElementById('update-progress-fill');
    var badge = document.getElementById('update-phase-badge');
    var text = document.getElementById('update-phase-text');
    var pct = PHASE_PROGRESS[phase] || 10;
    if (fill) fill.style.width = pct + '%';
    if (text && badge) {
      var label = badge.textContent;
      if (phase && phase !== 'done') {
        label = text.textContent;
      }
    }
  }

  function showProgressCard() {
    var card = document.getElementById('update-progress-card');
    if (card) card.hidden = false;
  }

  function updateJobUI(data) {
    var badge = document.getElementById('update-phase-badge');
    var text = document.getElementById('update-phase-text');
    var output = document.getElementById('update-job-output');
    var upgradeBtn = document.getElementById('btn-apt-upgrade');

    if (badge && data.phase_label) badge.textContent = data.phase_label;
    if (text && data.phase_label) text.textContent = data.phase_label;
    if (output && typeof data.output === 'string') {
      output.textContent = data.output;
      output.scrollTop = output.scrollHeight;
    }
    if (data.phase) setProgress(data.phase);

    if (upgradeBtn) {
      upgradeBtn.disabled = data.status === 'running';
    }
  }

  function pollJob() {
    var url = window.SAMBA_UPDATE_JOB_URL;
    if (!url) return;

    fetch(url, { credentials: 'same-origin' })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        updateJobUI(data);
        if (data.status === 'running') {
          setTimeout(pollJob, 2000);
          return;
        }
        if (data.status === 'done' && data.success) {
          if (data.reboot_pending) {
            showToast('Updates installiert – Neustart läuft …', 'success');
          } else {
            showToast('Updates wurden installiert.', 'success');
            setTimeout(function () { window.location.reload(); }, 1500);
          }
        } else if (data.status === 'failed') {
          showToast('Update fehlgeschlagen.', 'error');
        }
      })
      .catch(function () {
        setTimeout(pollJob, 3000);
      });
  }

  function showToast(message, type) {
    var stack = document.querySelector('.toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'toast-stack';
      stack.setAttribute('role', 'status');
      var main = document.querySelector('.container');
      if (main) main.insertBefore(stack, main.firstChild);
    }
    var toast = document.createElement('div');
    toast.className = 'toast ' + (type || 'success');
    toast.setAttribute('data-toast', '');
    toast.innerHTML =
      '<span class="toast-icon" aria-hidden="true">' + (type === 'error' ? '!' : '✓') + '</span>' +
      '<span class="toast-message"></span>' +
      '<button type="button" class="toast-close" aria-label="Schließen">×</button>';
    toast.querySelector('.toast-message').textContent = message;
    stack.appendChild(toast);
  }

  function startUpgrade() {
    var url = window.SAMBA_UPDATE_START_URL;
    if (!url || !window.SambaUI) return;

    window.SambaUI.confirm(
      'Updates installieren? Bei Bedarf wird das System neu gestartet.',
      { title: 'Updates installieren', danger: true }
    ).then(function (ok) {
      if (!ok) return;

      showProgressCard();
      setProgress('start');
      var upgradeBtn = document.getElementById('btn-apt-upgrade');
      if (upgradeBtn) {
        upgradeBtn.disabled = true;
        upgradeBtn.textContent = 'Wird ausgeführt …';
      }

      fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRF-Token': csrfToken(),
          'Content-Type': 'application/json',
        },
      })
        .then(function (res) { return res.json().then(function (b) { return { ok: res.ok, body: b }; }); })
        .then(function (result) {
          if (!result.ok) {
            showToast(result.body.error || 'Start fehlgeschlagen.', 'error');
            if (upgradeBtn) {
              upgradeBtn.disabled = false;
              upgradeBtn.textContent = 'Updates installieren';
            }
            return;
          }
          pollJob();
        })
        .catch(function () {
          showToast('Verbindungsfehler beim Start.', 'error');
          if (upgradeBtn) {
            upgradeBtn.disabled = false;
            upgradeBtn.textContent = 'Updates installieren';
          }
        });
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var upgradeBtn = document.getElementById('btn-apt-upgrade');
    if (upgradeBtn) {
      upgradeBtn.addEventListener('click', startUpgrade);
    }
    if (window.SAMBA_UPDATE_JOB_RUNNING) {
      showProgressCard();
      pollJob();
    }
  });
})();
