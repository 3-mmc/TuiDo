#!/usr/bin/env bash
# Publish the reviewed source snapshot; personal journal data is not in the bundle.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
bundle_path="$project_dir/TuiDo.bundle"
repo_name=3-mmc/TuiDo
if [[ ! -f "$bundle_path" ]]; then
    printf '%s\n' 'Missing TuiDo.bundle. Create a source snapshot first.' >&2
    exit 1
fi
gh auth status --hostname github.com
snapshot_dir=$(mktemp -d "${TMPDIR:-/tmp}/tuido-publish.XXXXXX")
git clone "$bundle_path" "$snapshot_dir"
if gh repo view "$repo_name" --json nameWithOwner >/dev/null 2>&1; then
    git -C "$snapshot_dir" remote set-url origin "https://github.com/$repo_name.git"
    git -C "$snapshot_dir" push --set-upstream origin main
else
    git -C "$snapshot_dir" remote remove origin
    gh repo create "$repo_name" --private --description 'Learning paths, a reading library, habits, and a daily bullet journal in your terminal' --source "$snapshot_dir" --remote origin --push
fi
printf '\n%s\n%s\n' "Repository: https://github.com/$repo_name" "Local snapshot: $snapshot_dir"
