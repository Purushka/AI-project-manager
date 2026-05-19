#!/usr/bin/env bash
set -euo pipefail

echo "=== Installing ai-pm-skills to OpenClaw ==="
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_SRC="$SCRIPT_DIR/skills"
SKILLS_DST="$HOME/.openclaw/plugin-skills"

mkdir -p "$SKILLS_DST"

for skill_dir in "$SKILLS_SRC"/ai-pm-*; do
    if [ -d "$skill_dir" ]; then
        skill_name=$(basename "$skill_dir")
        target="$SKILLS_DST/$skill_name"

        if [ -L "$target" ]; then
            rm "$target"
            echo "  Removed existing symlink: $target"
        elif [ -d "$target" ]; then
            echo "  [WARN] $target is a real directory, skipping (remove manually to reinstall)"
            continue
        fi

        ln -s "$skill_dir" "$target"
        echo "  [OK] $skill_name -> $skill_dir"
    fi
done

echo ""
echo "=== Installation Complete ==="
echo ""
echo "Installed skills:"
ls -la "$SKILLS_DST"/ai-pm-* 2>/dev/null || echo "  (none found)"
