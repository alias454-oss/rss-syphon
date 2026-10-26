#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status.
set -euo pipefail

# Enable debug logging if DEBUG=yes
if [[ "${DEBUG:-no}" == "yes" ]]; then
    echo "DEBUG mode is enabled. Command tracing will be shown."
    set -x  # turn ON
else
    set +x  # turn OFF
fi

echo "Running RSS-Syphon..."
python3 syphon.py
echo "Script finished."

# Execute the main container command (CMD)
exec "$@"
