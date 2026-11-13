#!/usr/bin/env bash
# Privacy guard: fails on personal data in tracked files or commit history (the repo may be public).
set -euo pipefail

status=0

# Emails, except no-reply and example addresses.
if git grep -nIE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' -- ':!*package-lock.json' \
  | grep -vE '@(users\.)?noreply\.(github|anthropic)\.com|noreply@|@example\.(com|org)'; then
  echo "::error::Found email addresses above. Personal emails stay out of the repo."
  status=1
fi

# AWS account IDs, except the docs example used in tests.
if git grep -nwE '[0-9]{12}' -- ':!*package-lock.json' | grep -v '123456789012'; then
  echo "::error::Found 12-digit numbers above that look like AWS account IDs. The deploy reads the account from AWS."
  status=1
fi

# Names from the PII_DENYLIST secret (comma-separated, never printed).
if [ -n "${PII_DENYLIST:-}" ]; then
  IFS=',' read -r -a words <<<"$PII_DENYLIST"
  history="$(git log --format='%an %ae %cn %ce %B' 2>/dev/null || true)"  # read once: grep -q on a pipe can SIGPIPE git under pipefail
  for word in "${words[@]}"; do
    word="$(echo "$word" | xargs)"
    [ -z "$word" ] && continue
    if git grep -qiwF -- "$word" -- ':!*package-lock.json' || grep -qiwF -- "$word" <<<"$history"; then
      echo "::error::A word from PII_DENYLIST appears in tracked files or commit history (not printed, to keep it private)."
      status=1
    fi
  done
fi

if git ls-files | grep -v '^tests/fixtures/' | grep -iE '\.(xlsx|xls|csv)$'; then
  echo "::error::Data files are tracked above. Exports and dumps must stay out of the repo."
  status=1
fi

[ "$status" -eq 0 ] && echo "No personal data found"
exit "$status"
