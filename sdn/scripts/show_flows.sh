#!/bin/bash
# Evidence for the demo / report. Run while the chat test is running.
for sw in s1 s2; do
  echo "======== $sw flows ========"
  sudo ovs-ofctl -O OpenFlow13 dump-flows $sw
  echo "======== $sw queue stats ========"
  sudo ovs-ofctl -O OpenFlow13 queue-stats $sw
done
echo "======== QoS / queue config ========"
sudo ovs-vsctl list qos; sudo ovs-vsctl list queue
