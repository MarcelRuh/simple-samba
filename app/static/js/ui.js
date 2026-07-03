(function () {
  'use strict';

  var modalEl = null;
  var modalTitle = null;
  var modalBody = null;
  var modalOk = null;
  var modalCancel = null;
  var modalResolve = null;

  function initModal() {
    modalEl = document.getElementById('ui-modal');
    if (!modalEl) return;
    modalTitle = document.getElementById('ui-modal-title');
    modalBody = document.getElementById('ui-modal-body');
    modalOk = document.getElementById('ui-modal-ok');
    modalCancel = document.getElementById('ui-modal-cancel');

    modalCancel.addEventListener('click', function () {
      closeModal(false);
    });
    modalOk.addEventListener('click', function () {
      closeModal(true);
    });
    modalEl.querySelector('.ui-modal-backdrop').addEventListener('click', function () {
      closeModal(false);
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modalEl && !modalEl.hidden) {
        closeModal(false);
      }
    });
  }

  function openModal(message, options) {
    options = options || {};
    if (!modalEl) return Promise.resolve(false);

    modalTitle.textContent = options.title || 'Bestätigen';
    modalBody.textContent = message;
    modalOk.textContent = options.okLabel || 'OK';
    modalCancel.textContent = options.cancelLabel || 'Abbrechen';
    modalOk.className = 'btn ' + (options.danger ? 'btn-danger' : 'btn-primary');

    modalEl.hidden = false;
    modalEl.setAttribute('aria-hidden', 'false');
    document.body.classList.add('modal-open');
    modalOk.focus();

    return new Promise(function (resolve) {
      modalResolve = resolve;
    });
  }

  function closeModal(result) {
    if (!modalEl || modalEl.hidden) return;
    modalEl.hidden = true;
    modalEl.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('modal-open');
    if (modalResolve) {
      modalResolve(!!result);
      modalResolve = null;
    }
  }

  function bindConfirmForms() {
    document.querySelectorAll('form[data-confirm]').forEach(function (form) {
      form.addEventListener('submit', function (e) {
        if (form.dataset.confirmed === '1') {
          delete form.dataset.confirmed;
          return;
        }
        e.preventDefault();
        var message = form.getAttribute('data-confirm') || 'Fortfahren?';
        var title = form.getAttribute('data-confirm-title') || 'Bestätigen';
        var danger = form.hasAttribute('data-confirm-danger');
        openModal(message, { title: title, danger: danger }).then(function (ok) {
          if (ok) {
            form.dataset.confirmed = '1';
            if (typeof form.requestSubmit === 'function') {
              form.requestSubmit();
            } else {
              form.submit();
            }
          }
        });
      });
    });
  }

  function bindToastDismiss() {
    document.querySelectorAll('[data-toast]').forEach(function (toast) {
      var closeBtn = toast.querySelector('.toast-close');
      if (closeBtn) {
        closeBtn.addEventListener('click', function () {
          toast.classList.add('toast-hide');
          setTimeout(function () {
            toast.remove();
          }, 220);
        });
      }
      setTimeout(function () {
        if (!toast.isConnected) return;
        toast.classList.add('toast-hide');
        setTimeout(function () {
          if (toast.isConnected) toast.remove();
        }, 220);
      }, 8000);
    });
  }

  function bindFormLoading() {
    document.querySelectorAll('form[data-loading]').forEach(function (form) {
      form.addEventListener('submit', function () {
        var btn = form.querySelector('button[type="submit"]');
        if (!btn || btn.disabled) return;
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = 'Wird ausgeführt …';
        btn.classList.add('is-loading');
      });
    });
  }

  window.SambaUI = {
    confirm: openModal,
    csrfToken: function () {
      var meta = document.querySelector('meta[name="csrf-token"]');
      return meta ? meta.getAttribute('content') : '';
    },
  };

  document.addEventListener('DOMContentLoaded', function () {
    initModal();
    bindConfirmForms();
    bindToastDismiss();
    bindFormLoading();
  });
})();
