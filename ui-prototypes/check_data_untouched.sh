#!/usr/bin/env bash
# Closing check for hard rule 2 (never touch real data). Run from the worktree root.
#   bash ui-prototypes/check_data_untouched.sh
# 1. DATA/db/*.sqlite and DATA/derived/step_cache must match the START snapshot exactly.
# 2. No file anywhere under DATA/ or Results/ may be newer than the snapshot file, except the one
#    known stray (critique r1 P0) which is listed here on purpose so it is never silently accepted.
set -u
START=ui-prototypes/DATA_MTIMES_START.txt
KNOWN_STRAY="DATA/derived/models/catalogue_classifier_153815b9dea451b2.joblib"
tmp=$(mktemp)
{ echo "## DATA/db/*.sqlite"; stat -c '%Y %s %n' DATA/db/*.sqlite* 2>/dev/null;
  echo "## DATA/derived/step_cache/ (recursive)"; find DATA/derived/step_cache -type f -printf '%T@ %s %p\n' | sort -k3;
  echo "## step_cache dir count: $(find DATA/derived/step_cache -type d | wc -l), file count: $(find DATA/derived/step_cache -type f | wc -l)"; } > "$tmp"
rc=0
if diff <(tail -n +2 "$START") "$tmp" >/dev/null; then
  echo "OK   DATA/db sqlite + step_cache identical to the START snapshot"
else
  echo "FAIL DATA/db sqlite or step_cache differ from the START snapshot:"; diff <(tail -n +2 "$START") "$tmp"; rc=1
fi
newer=$(find DATA/ Results/ -type f -newer "$START" 2>/dev/null | grep -v "/step_cache/" || true)
if [ -z "$newer" ]; then
  echo "OK   no file under DATA/ or Results/ is newer than the snapshot"
else
  echo "NEWER files under DATA/ or Results/ since the snapshot:"
  while read -r f; do
    if [ "$f" = "$KNOWN_STRAY" ]; then echo "  known stray (reported, not deleted): $f"; else echo "  UNEXPECTED: $f"; rc=1; fi
  done <<< "$newer"
fi
rm -f "$tmp"
exit $rc
