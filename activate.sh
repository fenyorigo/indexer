#!/bin/bash
# Must be sourced: . ./activate.sh   (not executed)
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "Please run:  source ./activate.sh"
  exit 1
fi
source .venv/bin/activate
