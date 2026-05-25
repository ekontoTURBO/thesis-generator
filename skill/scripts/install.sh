#!/usr/bin/env bash
# Install the thesis-generator skill into ~/.claude/skills/.
# Idempotent — safe to re-run; existing installation is overwritten.
set -euo pipefail

DEST="${HOME}/.claude/skills/thesis-generator"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$(dirname "$DEST")"

if [[ -L "$DEST" || -d "$DEST" ]]; then
    echo "Removing previous installation at $DEST"
    rm -rf "$DEST"
fi

# Symlink on Linux/macOS, copy on Windows (Git Bash detects $OS)
if [[ "${OS:-}" == "Windows_NT" ]]; then
    cp -r "$SRC" "$DEST"
    echo "Copied $SRC → $DEST"
else
    ln -s "$SRC" "$DEST"
    echo "Symlinked $SRC → $DEST"
fi

echo ""
echo "✓ Installed. Restart Claude Code (or run /reload-skills) and fire with:"
echo "   /thesis-generator"
