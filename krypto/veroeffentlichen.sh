#!/usr/bin/env bash
# Zustand, Verlauf und Bericht liegen auf dem Branch krypto-daten, immer als ein einziger Commit.
# So wächst der Git-Verlauf nicht um einen Commit pro Lauf.
#   laden             Dateien vom Daten-Branch nach $DATEN holen (fehlt der Branch: neues Depot)
#   veroeffentlichen  Dateien aus $DATEN als einzelnen Commit auf den Daten-Branch schreiben (Force-Push)
#   --trockenlauf     wie veroeffentlichen, aber ohne Push; zeigt den Commit-Inhalt
set -euo pipefail

BRANCH=krypto-daten
DATEN=${DATEN:-daten}
DATEIEN=(KRYPTO-REPORT.md zustand.json verlauf.svg)

commit_bauen() {
  local index
  index=$(mktemp)
  rm -f "$index"  # git legt den Index selbst an; eine leere Datei wäre ungültig
  trap 'rm -f "$index"' RETURN
  for f in "${DATEIEN[@]}"; do
    [ -f "$DATEN/$f" ] || { echo "fehlt: $DATEN/$f" >&2; return 1; }
    GIT_INDEX_FILE=$index git update-index --add --cacheinfo "100644,$(git hash-object -w "$DATEN/$f"),$f"
  done
  local tree
  tree=$(GIT_INDEX_FILE=$index git write-tree)
  GIT_AUTHOR_NAME=krypto-bot GIT_AUTHOR_EMAIL=krypto-bot@users.noreply.github.com \
  GIT_COMMITTER_NAME=krypto-bot GIT_COMMITTER_EMAIL=krypto-bot@users.noreply.github.com \
    git commit-tree "$tree" -m "Lauf $(date -u +%Y-%m-%dT%H:%MZ)"
}

case "${1:-}" in
  laden)
    mkdir -p "$DATEN"
    if git fetch --quiet --depth 1 origin "$BRANCH" 2>/dev/null; then
      git archive FETCH_HEAD | tar -x -C "$DATEN"
      echo "Zustand vom Branch $BRANCH geladen."
    else
      echo "Kein Branch $BRANCH: neues Rennen startet."
    fi
    ;;
  veroeffentlichen)
    commit=$(commit_bauen) || exit 1
    git push --quiet --force origin "$commit:refs/heads/$BRANCH"
    echo "Veröffentlicht auf $BRANCH: $commit"
    ;;
  --trockenlauf)
    commit=$(commit_bauen) || exit 1
    git ls-tree --name-only "$commit"
    echo "Trockenlauf: $commit nicht gepusht."
    ;;
  *)
    echo "Aufruf: $0 laden|veroeffentlichen|--trockenlauf" >&2
    exit 2
    ;;
esac
