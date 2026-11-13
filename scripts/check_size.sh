#!/usr/bin/env bash
# Fails if the built app's JavaScript and CSS together exceed the budget (gzipped), so the
# Home Screen app stays quick to open on a phone.
set -euo pipefail

limit_kb="${SIZE_LIMIT_KB:-150}"
dist="${1:-frontend/dist}"

# Fail loudly when there's no build to measure: find's errors inside < <(...) would not stop the script.
if [ ! -d "$dist" ]; then
  echo "::error::No build at $dist; run the frontend build first"
  exit 1
fi

total=0
files=0
while IFS= read -r -d '' file; do
  total=$((total + $(gzip -9 -c "$file" | wc -c)))
  files=$((files + 1))
done < <(find "$dist" -type f \( -name '*.js' -o -name '*.css' \) -print0)

if [ "$files" -eq 0 ]; then
  echo "::error::No JavaScript or CSS found in $dist"
  exit 1
fi

total_kb=$(( (total + 1023) / 1024 ))
echo "Frontend size: ${total_kb} KB gzipped (limit ${limit_kb} KB)"
if [ "$total_kb" -gt "$limit_kb" ]; then
  echo "::error::Frontend is ${total_kb} KB gzipped, over the ${limit_kb} KB limit"
  exit 1
fi
