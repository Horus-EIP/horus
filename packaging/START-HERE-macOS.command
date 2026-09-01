#!/bin/bash
set -u

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE" || { echo "Could not enter $HERE"; exit 1; }

SCRIPT="$HERE/installer/horus_install.py"

pause_and_exit() {
    echo
    echo "  Press Return to close this window."
    read -r _ || true
    exit "$1"
}

if [ ! -f "$SCRIPT" ]; then
    cat <<'EOF'

  ERROR: installer/horus_install.py is missing.

  This usually means the ZIP was only partly extracted, or this file was
  copied out of it on its own.

  Extract the whole Horus-Beta ZIP to a folder, open that folder, then
  right-click START-HERE-macOS.command and choose Open.

EOF
    pause_and_exit 17
fi

HORUS_PY=""
for candidate in python3.13 python3.12 python3.11 python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
            HORUS_PY="$candidate"
            break
        fi
    fi
done

if [ -z "$HORUS_PY" ]; then
    cat <<'EOF'

  ===================================================================
   Python 3.11 or newer is required, and was not found.
  ===================================================================

  Horus itself runs in Docker - Python is only needed to run this
  installer.

  Easiest option, download the official installer:

      https://www.python.org/downloads/macos/

  Or, if you already use Homebrew:

      brew install python@3.12

  The Python that ships with macOS is too old, and Apple has removed it
  from recent versions entirely, so installing a current one is expected.

  When it finishes, right-click START-HERE-macOS.command and choose Open
  again.

EOF
    pause_and_exit 10
fi

echo
echo "  Using $HORUS_PY ($("$HORUS_PY" --version 2>&1))"
echo

"$HORUS_PY" "$SCRIPT" "$@"
RC=$?

echo
if [ "$RC" -ne 0 ]; then
    echo "  The installer stopped with exit code $RC."
    echo "  Details are in install-log.txt next to this file."
fi
pause_and_exit "$RC"
