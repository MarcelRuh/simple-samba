(function () {
  'use strict';

  var APT_PHASE_PROGRESS = {
    start: 5,
    update: 25,
    upgrade: 65,
    autoremove: 85,
    reboot: 95,
    done: 100,
  };

  var APP_PHASE_PROGRESS = {
    start: 5,
    clone: 35,
    deploy: 75,
    done: 100,
  };

  function csrfToken() {
    return window.SambaUI ? window.SambaUI.csrfToken() : '';
  }

  function showToast(message, type) {
    if (window.showToast) {
      window.showToast(message, type);
    }
  }

  function setProgress(prefix, phase, map) {
    var fill = document.getElementById(prefix + '-progress-fill');
    var pct = map[phase] || 10;
    if (fill) fill.style.width = pct + '%';
  }

  function showProgressCard(prefix) {
    var card = document.getElementById(prefix + '-progress-card');
    if (card) card.hidden = false;
  }

  function updateJobUI(prefix, data, progressMap, buttonId, buttonIdleText) {
    var badge = document.getElementById(prefix + '-phase-badge');
    var text = document.getElementById(prefix + '-phase-text');
    var output = document.getElementById(prefix + '-job-output');
    var button = document.getElementById(buttonId);

    if (badge && data.phase_label) badge.textContent = data.phase_label;
    if (text && data.phase_label) text.textContent = data.phase_label;
    if (output && typeof data.output === 'string') {
      output.textContent = data.output;
      output.scrollTop = output.scrollHeight;
    }
    if (data.phase) setProgress(prefix, data.phase, progressMap);

    if (button) {
      button.disabled = data.status === 'running';
      if (data.status !== 'running' && buttonIdleText) {
        button.textContent = buttonIdleText;
      }
    }
  }

  function pollJob(prefix, jobUrl, progressMap, buttonId, buttonIdleText, onSuccess) {
    if (!jobUrl) return;

    fetch(jobUrl, { credentials: 'same-origin' })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        updateJobUI(prefix, data, progressMap, buttonId, buttonIdleText);
        if (data.status === 'running') {
          setTimeout(function () {
            pollJob(prefix, jobUrl, progressMap, buttonId, buttonIdleText, onSuccess);
          }, 2000);
          return;
        }
        if (data.status === 'done' && data.success) {
          if (onSuccess) onSuccess(data);
        } else if (data.status === 'failed') {
          showToast('Update fehlgeschlagen.', 'error');
        }
      })
      .catch(function () {
        setTimeout(function () {
          pollJob(prefix, jobUrl, progressMap, buttonId, buttonIdleText, onSuccess);
        }, 3000);
      });
  }

  function confirmSystemReboot() {
    if (!window.SAMBA_SYSTEM_REBOOT_URL || !window.SambaUI) {
      return Promise.resolve(false);
    }

    return window.SambaUI.confirm(
      'Das System wird neu gestartet. Offene Verbindungen werden getrennt. Fortfahren?',
      { title: 'Neustart bestätigen', danger: true, okLabel: 'Neustart' }
    ).then(function (ok) {
      if (!ok) return false;

      return fetch(window.SAMBA_SYSTEM_REBOOT_URL, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRF-Token': csrfToken(),
          'Content-Type': 'application/json',
        },
      })
        .then(function (res) {
          return res.json().then(function (body) {
            return { ok: res.ok, body: body };
          });
        })
        .then(function (result) {
          if (result.ok) {
            showToast(result.body.message || 'System startet neu …', 'success');
            return true;
          }
          showToast(result.body.error || 'Neustart fehlgeschlagen.', 'error');
          return false;
        })
        .catch(function () {
          showToast('Verbindungsfehler beim Neustart.', 'error');
          return false;
        });
    });
  }

  function promptRebootAfterUpgrade() {
    if (!window.SambaUI) {
      showToast('Updates installiert. Neustart ausstehend.', 'success');
      setTimeout(function () { window.location.reload(); }, 1500);
      return;
    }

    window.SambaUI.confirm(
      'Updates installiert. Ein Neustart ist erforderlich. Jetzt neu starten?',
      { title: 'Neustart bestätigen', danger: true, okLabel: 'Neustart', cancelLabel: 'Später' }
    ).then(function (ok) {
      if (ok) {
        confirmSystemReboot();
        return;
      }
      showToast('Updates installiert. Neustart ausstehend.', 'success');
      setTimeout(function () { window.location.reload(); }, 1500);
    });
  }

  function startJob(options) {
    var url = options.startUrl;
    if (!url || !window.SambaUI) return;

    window.SambaUI.confirm(options.confirmText, {
      title: options.confirmTitle,
      danger: !!options.danger,
    }).then(function (ok) {
      if (!ok) return;

      showProgressCard(options.prefix);
      setProgress(options.prefix, 'start', options.progressMap);

      var button = document.getElementById(options.buttonId);
      if (button) {
        button.disabled = true;
        button.textContent = 'Wird ausgeführt …';
      }

      fetch(url, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRF-Token': csrfToken(),
          'Content-Type': 'application/json',
        },
      })
        .then(function (res) {
          return res.json().then(function (body) {
            return { ok: res.ok, body: body };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            showToast(result.body.error || 'Start fehlgeschlagen.', 'error');
            if (button) {
              button.disabled = false;
              button.textContent = options.buttonIdleText;
            }
            return;
          }
          pollJob(
            options.prefix,
            options.jobUrl,
            options.progressMap,
            options.buttonId,
            options.buttonIdleText,
            options.onSuccess
          );
        })
        .catch(function () {
          showToast('Verbindungsfehler beim Start.', 'error');
          if (button) {
            button.disabled = false;
            button.textContent = options.buttonIdleText;
          }
        });
    });
  }

  function startUpgrade() {
    startJob({
      prefix: 'update',
      startUrl: window.SAMBA_UPDATE_START_URL,
      jobUrl: window.SAMBA_UPDATE_JOB_URL,
      progressMap: APT_PHASE_PROGRESS,
      buttonId: 'btn-apt-upgrade',
      buttonIdleText: 'Updates installieren',
      confirmTitle: 'Updates installieren',
      confirmText: 'Updates installieren? Bei erforderlichem Neustart wirst du zur Bestätigung aufgefordert.',
      danger: true,
      onSuccess: function (data) {
        if (data.reboot_pending) {
          promptRebootAfterUpgrade();
        } else {
          showToast('Updates wurden installiert.', 'success');
          setTimeout(function () { window.location.reload(); }, 1500);
        }
      },
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var upgradeBtn = document.getElementById('btn-apt-upgrade');
    if (upgradeBtn) {
      upgradeBtn.addEventListener('click', startUpgrade);
    }

    var rebootBtn = document.getElementById('btn-system-reboot');
    if (rebootBtn) {
      rebootBtn.addEventListener('click', confirmSystemReboot);
    }

    var appUpdateBtn = document.getElementById('btn-app-update');
    if (appUpdateBtn) {
      var appUpdateLabel = appUpdateBtn.textContent.trim();
      appUpdateBtn.addEventListener('click', function () {
        startJob({
          prefix: 'app-update',
          startUrl: window.SAMBA_APP_UPDATE_START_URL,
          jobUrl: window.SAMBA_APP_UPDATE_JOB_URL,
          progressMap: APP_PHASE_PROGRESS,
          buttonId: 'btn-app-update',
          buttonIdleText: appUpdateLabel,
          confirmTitle: 'App von GitHub aktualisieren',
          confirmText: 'Simple Samba UI von GitHub aktualisieren? Die Web-UI startet kurz neu.',
          danger: false,
          onSuccess: function (data) {
            var msg = 'App-Update abgeschlossen.';
            if (data.new_version) {
              msg = 'App wurde auf v' + data.new_version + ' aktualisiert.';
            }
            showToast(msg, 'success');
            setTimeout(function () { window.location.reload(); }, 2000);
          },
        });
      });
    }

    if (window.SAMBA_UPDATE_JOB_RUNNING) {
      showProgressCard('update');
      pollJob(
        'update',
        window.SAMBA_UPDATE_JOB_URL,
        APT_PHASE_PROGRESS,
        'btn-apt-upgrade',
        'Updates installieren'
      );
    }
    if (window.SAMBA_APP_UPDATE_JOB_RUNNING) {
      showProgressCard('app-update');
      pollJob(
        'app-update',
        window.SAMBA_APP_UPDATE_JOB_URL,
        APP_PHASE_PROGRESS,
        'btn-app-update',
        appUpdateBtn ? appUpdateBtn.textContent.trim() : 'Von GitHub aktualisieren',
        function (data) {
          var msg = 'App-Update abgeschlossen.';
          if (data.new_version) {
            msg = 'App wurde auf v' + data.new_version + ' aktualisiert.';
          }
          showToast(msg, 'success');
          setTimeout(function () { window.location.reload(); }, 2000);
        }
      );
    }
  });
})();
