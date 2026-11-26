#!/bin/sh
# Export commit SHA of REPO into the existing directory DEST with the committed file modes (0755 / 0644).
#
#   sh scripts/export-tree.sh REPO SHA DEST
#
# tar run by a non-root user narrows the archive modes by the caller's umask, so under the owner's umask 077 an
# executable came out 0700 and the git-hook tests failed in the package runner's gate (2026-11-26). The fixed umask
# applies to this extraction only; the caller keeps its own for everything else.
set -u
[ $# -eq 3 ] || { echo "usage: sh scripts/export-tree.sh REPO SHA DEST" >&2; exit 2; }
repo=$1
sha=$2
dest=$3
tar_file=$(mktemp) || exit 1
trap 'rm -f "$tar_file"' EXIT
git -C "$repo" archive --format=tar -o "$tar_file" "$sha" || exit 1
umask 022
tar -xf "$tar_file" -C "$dest"
