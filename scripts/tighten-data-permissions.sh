#!/bin/sh
# Remove group and other access from the existing private data files and folders.
# Dry run by default: lists what would change. --apply changes it. Safe to run again.
# Only ever removes bits, never widens a mode, and never follows a symlink.
#
#   sh scripts/tighten-data-permissions.sh [--apply] [--data-dir DIR]
#
# Run it as the owner of data/ (on the host, the user who runs rootless podman).
# Same folder list as PRIVATE_RESTORE in scripts/backup-handler.js, plus data/applications.

set -u

usage() {
  echo "Usage: sh tighten-data-permissions.sh [--apply] [--data-dir DIR]"
  exit "$1"
}

apply=0
root=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd) || exit 1
data="$root/data"

while [ $# -gt 0 ]; do
  case "$1" in
    --apply) apply=1 ;;
    --data-dir)
      shift
      [ $# -gt 0 ] || usage 2
      data=$1
      ;;
    -h | --help) usage 0 ;;
    *) usage 2 ;;
  esac
  shift
done

if [ ! -d "$data" ]; then
  echo "No such data folder: $data" >&2
  exit 2
fi

# Entries of type $2 under $1 with any group or other bit set; the rest of the arguments are find actions.
too_open() {
  dir=$1
  type=$2
  shift 2
  find "$dir" -type "$type" \( -perm -040 -o -perm -020 -o -perm -010 -o -perm -004 -o -perm -002 -o -perm -001 \) "$@"
}

count_all() {
  total=0
  for dir in "$@"; do
    n=$(too_open "$dir" "$type_wanted" -print | wc -l)
    total=$((total + n))
  done
  echo "$total"
}

set -- "$data/profile" "$data/applications" "$data/ai/findings" "$data/config" "$data/backups" "$data"/profile.bak-*
for dir in "$@"; do
  shift
  if [ -L "$dir" ]; then
    echo "Skipped, a symlink: $dir" >&2
  elif [ -d "$dir" ]; then
    set -- "$@" "$dir"
  fi
done

for dir in "$@"; do
  too_open "$dir" f -exec ls -ld -- {} +
  too_open "$dir" d -exec ls -ld -- {} +
done

type_wanted=f
files=$(count_all "$@")
type_wanted=d
dirs=$(count_all "$@")

if [ "$apply" -eq 0 ]; then
  echo "Dry run: $files files and $dirs directories would change. Nothing was changed. Use --apply."
  exit 0
fi

for dir in "$@"; do
  too_open "$dir" f -exec chmod go-rwx -- {} +
  too_open "$dir" d -exec chmod go-rwx -- {} +
done

type_wanted=f
files_left=$(count_all "$@")
type_wanted=d
dirs_left=$(count_all "$@")
echo "Changed $((files - files_left)) files and $((dirs - dirs_left)) directories."

if [ "$files_left" -ne 0 ] || [ "$dirs_left" -ne 0 ]; then
  echo "Still open: $files_left files and $dirs_left directories." >&2
  exit 1
fi
