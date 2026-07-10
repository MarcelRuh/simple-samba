#!/bin/bash
# Stellt Git-Autor und Hooks für das Quell-Repository dauerhaft ein.
set -euo pipefail

GIT_NAME="${SIMPLE_SAMBA_GIT_NAME:-MarcelRuh}"
GIT_EMAIL="${SIMPLE_SAMBA_GIT_EMAIL:-96293418+MarcelRuh@users.noreply.github.com}"
HOOKS_PATH=".githooks"

apply_identity() {
	local repo="$1"
	[[ -d "${repo}/.git" ]] || return 0
	git -C "${repo}" config user.name "${GIT_NAME}"
	git -C "${repo}" config user.email "${GIT_EMAIL}"
	git -C "${repo}" config core.hooksPath "${HOOKS_PATH}"
	chmod +x "${repo}/${HOOKS_PATH}/prepare-commit-msg" 2>/dev/null || true
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
apply_identity "${SCRIPT_DIR}"

for extra in /usr/local/src/simple-samba /home/github/simple-samba-ui; do
	[[ "${extra}" == "${SCRIPT_DIR}" ]] && continue
	apply_identity "${extra}"
done
