#!/bin/bash
# Screenshots aus dem Cursor-Workspace in docs/screenshots/ kopieren und umbenennen.
# Auf dem lokalen Rechner ausführen (nicht auf dem Samba-Server).
set -euo pipefail

SRC="${1:-$HOME/.config/Cursor/User/workspaceStorage/empty-window/images}"
DST="${2:-$(cd "$(dirname "$0")/.." && pwd)/docs/screenshots}"

declare -A MAP=(
    ["image-babded24-c01e-4fab-8da3-ef433f4acd6e.png"]="Freigaben.png"
    ["image-8f33e42b-3670-4135-b8d8-478c7504b315.png"]="Benutzer.png"
    ["image-ab00c36c-dce7-46d5-95b6-54d184ed6c28.png"]="Status.png"
    ["image-b3f9b2d2-93ea-428c-a2e0-fc25d50f3380.png"]="Updates.png"
    ["image-9ddc21b5-515c-4aa7-8269-c9451ba13875.png"]="Passwort.png"
)

mkdir -p "${DST}"

for src_name in "${!MAP[@]}"; do
    src="${SRC}/${src_name}"
    dst="${DST}/${MAP[$src_name]}"
    if [[ ! -f "${src}" ]]; then
        echo "FEHLER: ${src} nicht gefunden" >&2
        exit 1
    fi
    cp "${src}" "${dst}"
    echo "→ ${MAP[$src_name]}"
done

echo "Fertig: ${DST}"
