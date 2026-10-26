#!/bin/bash
sudo mn -c
sudo ip link del ctl0 2>/dev/null
sudo ovs-vsctl --all destroy QoS 2>/dev/null
sudo ovs-vsctl --all destroy Queue 2>/dev/null
echo cleaned
