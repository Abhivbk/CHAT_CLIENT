#!/bin/bash
# Usage:  bash scripts/start_controller.sh baseline    |    bash scripts/start_controller.sh sdn
# Run from the folder that contains sdn_controller.py (Terminal 1, leave it open).
MODE=${1:-sdn}
source ~/ryu-env/bin/activate
SDN_MODE=$MODE ryu-manager --verbose sdn_controller.py
