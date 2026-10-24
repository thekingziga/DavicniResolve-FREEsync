#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "======================================================="
echo "   ResolveSync - DaVinci Resolve Universal Client"
echo "======================================================="
echo ""

# Ensure modern dark UI and database libraries if pip is available
python3 -c "import customtkinter, requests, pg8000" 2>/dev/null || python3 -m pip install -q --user customtkinter requests pg8000 2>/dev/null

# Launch Graphical Desktop Application
if [ -f "$DIR/desktop_app.py" ]; then
    python3 "$DIR/desktop_app.py" "$@"
else
    python3 "$DIR/resolvesync_mac.py" "$@"
fi
