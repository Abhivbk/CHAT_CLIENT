#!/bin/bash
# Run INSIDE the Ubuntu VM:  bash scripts/install_deps.sh
set -e
sudo apt update
sudo apt upgrade -y
sudo apt install -y mininet openvswitch-switch git python3-pip python3-venv iperf tshark wireshark python3-matplotlib python3-pandas xterm
sudo systemctl enable --now openvswitch-switch || true

# Ryu in its own virtual environment (kept separate from Mininet's system Python)
python3 -m venv ~/ryu-env
source ~/ryu-env/bin/activate
pip install --upgrade pip wheel "setuptools<68"
pip install "eventlet==0.30.2" ryu
echo "Ryu installed:  $(ryu-manager --version 2>&1)"
echo "Next time: source ~/ryu-env/bin/activate  before running ryu-manager"
