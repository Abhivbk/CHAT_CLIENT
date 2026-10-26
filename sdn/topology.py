#!/usr/bin/env python3
"""
topology.py  -  Mininet topology + QoS queues for the Multi-Client TCP Chat project
(Person 2 deliverable)

Topology
--------
                 ctl0 (10.0.0.100, Ryu telemetry port, in the VM's root namespace)
                  |
   h1 (chat server) -- s1 ==== 10 Mbit/s bottleneck ==== s2 -- h2 (client)
   10.0.0.1                  (s1-eth1 <-> s2-eth1)         |-- h3 (client)
                                                           '-- h4 (iperf background traffic)

   h1 10.0.0.1   h2 10.0.0.2   h3 10.0.0.3   h4 10.0.0.4   (all /24)
   Ryu controller: 127.0.0.1:6653      Telemetry target for server.py: 10.0.0.100:9999

The bottleneck link is rate-limited and given 3 queues by Open vSwitch (HTB):
   queue 0 = default / best effort      queue 1 = VIP (high priority)
   queue 2 = throttled (1 Mbit/s cap)

Usage (must be run with sudo):
   sudo python3 topology.py                       # interactive Mininet CLI
   sudo python3 topology.py --experiment baseline --chat-dir ~/CHAT_CLIENT
   sudo python3 topology.py --experiment sdn      --chat-dir ~/CHAT_CLIENT
(Start Ryu FIRST in another terminal, with SDN_MODE=baseline or SDN_MODE=sdn.)
"""
import argparse
import os
import subprocess
import sys
import time
from functools import partial

from mininet.cli import CLI
from mininet.link import Link
from mininet.log import info, setLogLevel
from mininet.net import Mininet
from mininet.node import OVSKernelSwitch, RemoteController

CTRL_IP = "10.0.0.100"       # address of the controller's telemetry interface
SERVER_IP = "10.0.0.1"
SERVER_PORT = 5000
TELEMETRY_PORT = 9999


def sh(cmd, check=False):
    """Run a root-namespace shell command, return stdout."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and r.returncode != 0:
        info("*** Command failed: %s\n%s\n" % (cmd, r.stderr))
    return r.stdout


# ------------------------------------------------------------------ QoS setup
def setup_qos(ifname, bw_mbit):
    """Create an HTB QoS with 3 queues on an OVS port."""
    bw = int(bw_mbit * 1_000_000)
    cmd = (
        "ovs-vsctl -- set port {i} qos=@newqos "
        "-- --id=@newqos create qos type=linux-htb other-config:max-rate={bw} "
        "queues:0=@q0 queues:1=@q1 queues:2=@q2 "
        "-- --id=@q0 create queue other-config:min-rate={q0min} other-config:max-rate={bw} other-config:priority=1 "
        "-- --id=@q1 create queue other-config:min-rate={q1min} other-config:max-rate={bw} other-config:priority=0 "
        "-- --id=@q2 create queue other-config:max-rate={q2max} other-config:priority=2"
    ).format(i=ifname, bw=bw, q0min=int(bw * 0.2), q1min=int(bw * 0.6), q2max=int(bw * 0.1))
    sh(cmd, check=True)
    info("*** QoS queues configured on %s (%.0f Mbit/s)\n" % (ifname, bw_mbit))


def clear_qos():
    sh("ovs-vsctl --all destroy QoS")
    sh("ovs-vsctl --all destroy Queue")


# --------------------------------------------- root-namespace telemetry port
def add_telemetry_port():
    """Give the controller (running in the VM) an address on the Mininet network.

    h1's UDP telemetry goes to 10.0.0.100:9999. A veth pair connects s1 to the VM
    root namespace, where Ryu is listening. /24 is used so the VM's own 10.0.2.x
    (VirtualBox NAT) network is not affected.
    """
    sh("ip link del ctl0 2>/dev/null")
    sh("ip link add ctl0 type veth peer name ctl1", check=True)
    sh("ovs-vsctl add-port s1 ctl1", check=True)
    sh("ip addr add %s/24 dev ctl0" % CTRL_IP)
    sh("ip link set ctl0 up; ip link set ctl1 up")
    info("*** Telemetry port ready: controller reachable at %s (UDP %d)\n" % (CTRL_IP, TELEMETRY_PORT))


def remove_telemetry_port():
    sh("ip link del ctl0 2>/dev/null")


# ---------------------------------------------------------------- the network
def build(bw_mbit):
    net = Mininet(controller=None,
                  switch=partial(OVSKernelSwitch, protocols="OpenFlow13"),
                  link=Link, autoSetMacs=True)
    net.addController("c0", controller=RemoteController, ip="127.0.0.1", port=6653)
    s1 = net.addSwitch("s1")
    s2 = net.addSwitch("s2")
    h1 = net.addHost("h1", ip="10.0.0.1/24")
    h2 = net.addHost("h2", ip="10.0.0.2/24")
    h3 = net.addHost("h3", ip="10.0.0.3/24")
    h4 = net.addHost("h4", ip="10.0.0.4/24")
    # explicit port numbers: port 1 on each switch = bottleneck trunk
    net.addLink(s1, s2, port1=1, port2=1)
    net.addLink(h1, s1, port2=2)
    net.addLink(h2, s2, port2=2)
    net.addLink(h3, s2, port2=3)
    net.addLink(h4, s2, port2=4)
    return net


# ------------------------------------------------------------- experiment run
def run_experiment(net, label, chat_dir, results_dir, bg_mbit, bg_seconds,
                   rtt_messages, scale_clients, scale_messages, repeats):
    h1, h2, h4 = net.get("h1", "h2", "h4")
    os.makedirs(results_dir, exist_ok=True)
    csv_path = os.path.join(results_dir, "results_%s.csv" % label)
    log_path = os.path.join(results_dir, "run_%s.log" % label)
    events = os.path.join(results_dir, "events_%s.jsonl" % label)
    if os.path.exists(csv_path):
        os.rename(csv_path, csv_path + ".old.%d" % int(time.time()))

    info("*** Waiting for controller / switches\n")
    time.sleep(3)
    net.pingAll()
    time.sleep(1)

    info("*** Starting chat server on h1\n")
    h1.cmd("cd %s && python3 server.py --host 0.0.0.0 --port %d --controller %s:%d "
           "--event-log %s > %s/server_%s.log 2>&1 &"
           % (chat_dir, SERVER_PORT, CTRL_IP, TELEMETRY_PORT, events, results_dir, label))
    time.sleep(2)

    info("*** Starting background UDP congestion (%s Mbit/s each way)\n" % bg_mbit)
    h1.cmd("iperf -s -u > /dev/null 2>&1 &")
    h4.cmd("iperf -s -u > /dev/null 2>&1 &")
    time.sleep(1)
    h4.cmd("iperf -c %s -u -b %sM -t %d > %s/iperf_to_server_%s.txt 2>&1 &"
           % (SERVER_IP, bg_mbit, bg_seconds, results_dir, label))
    h1.cmd("iperf -c 10.0.0.4 -u -b %sM -t %d > %s/iperf_from_server_%s.txt 2>&1 &"
           % (bg_mbit, bg_seconds, results_dir, label))
    time.sleep(2)

    with open(log_path, "a") as log:
        for r in range(1, repeats + 1):
            info("*** [%s] repeat %d/%d: RTT test\n" % (label, r, repeats))
            out = h2.cmd("cd %s && python3 test_clients.py rtt --host %s --port %d "
                         "--messages %d --interval 0.05 --csv %s"
                         % (chat_dir, SERVER_IP, SERVER_PORT, rtt_messages, csv_path))
            log.write("--- repeat %d rtt ---\n%s\n" % (r, out))
            info(out + "\n")
            info("*** [%s] repeat %d/%d: scale test (%d clients)\n" % (label, r, repeats, scale_clients))
            out = h2.cmd("cd %s && python3 test_clients.py scale --host %s --port %d "
                         "--clients %d --messages %d --interval 0.05 --csv %s"
                         % (chat_dir, SERVER_IP, SERVER_PORT, scale_clients, scale_messages, csv_path))
            log.write("--- repeat %d scale ---\n%s\n" % (r, out))
            info(out + "\n")
            time.sleep(2)

    info("*** Saving switch evidence (flows + queue stats)\n")
    ev = os.path.join(results_dir, "switch_evidence_%s.txt" % label)
    with open(ev, "w") as f:
        for sw in ("s1", "s2"):
            f.write("===== %s flows =====\n" % sw)
            f.write(sh("ovs-ofctl -O OpenFlow13 dump-flows %s" % sw))
            f.write("===== %s queue stats =====\n" % sw)
            f.write(sh("ovs-ofctl -O OpenFlow13 queue-stats %s" % sw))
    h1.cmd("pkill -f 'server.py --host 0.0.0.0'; pkill iperf")
    h4.cmd("pkill iperf")
    info("*** Done. Results: %s\n*** Evidence: %s\n*** Log: %s\n" % (csv_path, ev, log_path))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--bw", type=float, default=10.0, help="bottleneck bandwidth in Mbit/s")
    p.add_argument("--experiment", metavar="LABEL",
                   help="run automated experiment, e.g. baseline or sdn, then exit")
    p.add_argument("--chat-dir", default=os.path.expanduser("~/CHAT_CLIENT"),
                   help="folder containing server.py / client.py / test_clients.py")
    p.add_argument("--results-dir", default=os.path.abspath("results"))
    p.add_argument("--bg-mbit", type=float, default=12.0, help="background UDP load each way")
    p.add_argument("--rtt-messages", type=int, default=200)
    p.add_argument("--scale-clients", type=int, default=10)
    p.add_argument("--scale-messages", type=int, default=20)
    p.add_argument("--repeats", type=int, default=3)
    args = p.parse_args()

    if os.geteuid() != 0:
        sys.exit("Run with sudo:  sudo python3 topology.py")

    setLogLevel("info")
    net = build(args.bw)
    net.start()
    try:
        setup_qos("s1-eth1", args.bw)
        setup_qos("s2-eth1", args.bw)
        add_telemetry_port()

        if args.experiment:
            bg_seconds = int(args.repeats * (args.rtt_messages * 0.1 + 60) + 30)
            run_experiment(net, args.experiment, os.path.expanduser(args.chat_dir),
                           args.results_dir, args.bg_mbit, bg_seconds, args.rtt_messages,
                           args.scale_clients, args.scale_messages, args.repeats)
        else:
            info("\n*** Hosts: h1=10.0.0.1 (server)  h2=10.0.0.2  h3=10.0.0.3  h4=10.0.0.4 (iperf)\n")
            info("*** Server cmd (on h1): python3 server.py --host 0.0.0.0 --port 5000 "
                 "--controller 10.0.0.100:9999 --event-log events.jsonl\n")
            info("*** Try: nodes / net / dump / pingall / xterm h1 h2 h3\n\n")
            CLI(net)
    finally:
        net.stop()
        remove_telemetry_port()
        clear_qos()


if __name__ == "__main__":
    main()
