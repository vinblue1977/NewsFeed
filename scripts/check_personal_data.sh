#!/usr/bin/env bash
# Privacy guard: fails on personal data in tracked files, new files not yet added (git-ignored ones are skipped) or commit
# history (the repo may be public). New files are scanned too, so a local run catches what CI would.
set -euo pipefail

status=0

# Emails, except no-reply and example addresses.
if git grep --untracked --exclude-standard -nIE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' -- ':!*package-lock.json' \
  | grep -vE '@(users\.)?noreply\.(github|anthropic)\.com|noreply@|@example\.(com|org)'; then
  echo "::error::Found email addresses above. Personal emails stay out of the repo."
  status=1
fi

# Author and committer emails must be GitHub or Anthropic no-reply addresses. PRIVACY_LOG_RANGE (e.g. BASE..HEAD, set by
# CI on pull requests) limits the scan to the PR's own commits; unset scans all history. Addresses are never printed.
# Fail closed: if git log cannot read the range (shallow clone, missing base commit) nothing was scanned.
log="$(git log --format='%ae%n%ce' ${PRIVACY_LOG_RANGE:+"$PRIVACY_LOG_RANGE"})" || {
  echo "::error::git log failed (range '${PRIVACY_LOG_RANGE:-all}'): the commit history was not scanned."
  exit 1
}
bad="$(sort -u <<<"$log" | grep -vcE '^$|@users\.noreply\.github\.com$|^noreply@(github|anthropic)\.com$' || true)"
if [ "$bad" != 0 ]; then
  echo "::error::$bad commit author/committer email(s) are not GitHub/Anthropic no-reply addresses (not printed). Set git user.email to your GitHub no-reply address."
  status=1
fi

# AWS account IDs, except the docs example used in tests.
if git grep --untracked --exclude-standard -nowE '[0-9]{12}' -- ':!*package-lock.json' | grep -vE ':123456789012$'; then
  echo "::error::Found 12-digit numbers above that look like AWS account IDs. The deploy reads the account from AWS."
  status=1
fi

# Names from the PII_DENYLIST secret (comma-separated, never printed).
if [ -z "${PII_DENYLIST:-}" ] && [ -n "${CI:-}" ]; then
  echo "::warning::PII_DENYLIST is not set, so the name check was skipped (expected on fork PRs)."
fi
if [ -n "${PII_DENYLIST:-}" ]; then
  IFS=',' read -r -a words <<<"$PII_DENYLIST"
  history="$(git log --format='%an %ae %cn %ce %B' ${PRIVACY_LOG_RANGE:+"$PRIVACY_LOG_RANGE"})" || { echo "::error::git log failed: history not scanned."; exit 1; }  # read once: grep -q on a pipe can SIGPIPE git under pipefail
  for word in "${words[@]}"; do
    word="$(echo "$word" | xargs)"
    [ -z "$word" ] && continue
    if git grep --untracked --exclude-standard -qiwF -- "$word" -- ':!*package-lock.json' || grep -qiwF -- "$word" <<<"$history"; then
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
