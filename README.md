# SDN-Integrated Multi-Client TCP Chat Application

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Running the Project](#2-running-the-project)
3. [System Architecture](#3-system-architecture)
4. [Repository Structure](#4-repository-structure)
5. [Chat Application](#5-chat-application)
6. [Telemetry Specification](#6-telemetry-specification)
7. [SDN Controller and Policies](#7-sdn-controller-and-policies)
8. [Network Topology and QoS](#8-network-topology-and-qos)
9. [Testing and Benchmarks](#9-testing-and-benchmarks)
10. [Results](#10-results)
11. [Limitations](#11-limitations)
12. [Team](#12-team)

---

## 1. Project Overview

This project is a multi-client chat application built on low-level TCP sockets and integrated with a Software-Defined Networking (SDN) controller running in a Mininet environment. Users can register, send private messages, create and join chat rooms, and broadcast messages to room members.

The chat server also emits out-of-band UDP telemetry (JSON) describing what users are doing. A Ryu OpenFlow controller consumes this telemetry and applies network policies, such as prioritising selected chat connections or throttling spammers, on a congested link. The project compares a Baseline network (no policies) against an SDN-enabled network under the same load.

---

## 2. Running the Project

### 2.1 Requirements

| Part | Requirements |
| ----- | ----- |
| Chat application | Python 3.8+ (standard library only, nothing to install) |
| SDN experiment | Ubuntu 22.04 (VM or native) with sudo, Mininet, Open vSwitch, iperf, Ryu |

### 2.2 Quick start: chat only (1 minute, any OS)

```bash
git clone https://github.com/Abhivbk/CHAT_CLIENT
cd CHAT_CLIENT

# Terminal 1: server
python3 server.py

# Terminal 2 and 3: clients
python3 client.py --host 127.0.0.1 --port 5000 --user alice
python3 client.py --host 127.0.0.1 --port 5000 --user bob

# Terminal 4: automated checks (server must be running)
python3 test_clients.py functional --host 127.0.0.1 --port 5000
```

Try in a client: `/create vip`, `/join vip`, `/roommsg vip hello`, `/msg bob hi`, `/help`.

### 2.3 Full setup: Mininet + Open vSwitch + Ryu

**Step 1: Install dependencies (one time).** Installs Mininet, Open vSwitch, iperf, Wireshark tools, and Ryu inside a virtual environment at `~/ryu-env`.

```bash
git clone https://github.com/Abhivbk/CHAT_CLIENT ~/CHAT_CLIENT
cd ~/CHAT_CLIENT/sdn
bash scripts/install_deps.sh
bash scripts/cleanup.sh
```

**Step 2: Run the automated Baseline vs SDN experiment.** Use two terminals, both in `~/CHAT_CLIENT/sdn`. Run the whole sequence once with `baseline` and once with `sdn`, with `cleanup.sh` in between. Each run takes several minutes.

```bash
# Terminal 1: start the controller (baseline or sdn)
bash scripts/start_controller.sh baseline

# Terminal 2: build the network and run the experiment
sudo python3 topology.py --experiment baseline --chat-dir ~/CHAT_CLIENT
# wait for "*** Done", then Ctrl+C in Terminal 1 and run: bash scripts/cleanup.sh
# repeat both terminals with "sdn" in place of "baseline"
```

**Step 3: Compare the results.**

```bash
python3 compare_results.py
```

This writes `results/comparison.csv` and `results/comparison.png`. Raw per-run data is in `results/results_baseline.csv` and `results/results_sdn.csv`.

**Optional: interactive demo.** Start the controller in `sdn` mode, then open the network without an experiment:

```bash
# Terminal 1
bash scripts/start_controller.sh sdn
# Terminal 2
sudo python3 topology.py
mininet> xterm h1 h2 h3
```

```bash
# h1 (server, reporting to the controller at 10.0.0.100)
cd ~/CHAT_CLIENT
python3 server.py --host 0.0.0.0 --port 5000 --controller 10.0.0.100:9999 --event-log events.jsonl

# h2 and h3 (clients)
cd ~/CHAT_CLIENT
python3 client.py --host 10.0.0.1 --port 5000 --user alice      # --user bob on h3
# inside a client: /create vip, /join vip, /roommsg vip hello
```

When a client joins room `vip`, the controller log prints `POLICY A: prioritising ...`. In a third terminal, run `bash scripts/show_flows.sh` to see the `set_queue` flow rules and queue statistics.

### 2.4 Hosts and addresses

| Node | Address | Role |
| ----- | ----- | ----- |
| h1 | 10.0.0.1 | Chat server (TCP 5000) |
| h2, h3 | 10.0.0.2, 10.0.0.3 | Chat clients |
| h4 | 10.0.0.4 | Background traffic (iperf) |
| ctl0 | 10.0.0.100 | Controller telemetry address (UDP 9999) |
| Ryu | 127.0.0.1:6653 | OpenFlow controller |

### 2.5 Troubleshooting

| Problem | Fix |
| ----- | ----- |
| `ryu-manager: command not found` | `source ~/ryu-env/bin/activate` |
| Ryu import error (`ALREADY_HANDLED`) | `pip install "eventlet==0.30.2"` in the Ryu virtual environment |
| `pingall` shows 100% dropped | Start Ryu first; its log must show `Switch connected` twice |
| `Unable to contact the remote controller` | Ryu is not running on port 6653 |
| No `EVENT` lines in the controller log | Server was not started with `--controller 10.0.0.100:9999` |
| No `set_queue` flows | Controller is in `baseline` mode, or no client joined a VIP room |
| `iperf: command not found` | `sudo apt install iperf` |
| Leftover state or odd errors | `bash scripts/cleanup.sh` |

---

## 3. System Architecture

```
                  CONTROL PLANE
        +-------------------------------+
        |  Ryu SDN Controller           |
        |  - UDP telemetry listener     |
        |  - session / flow mapper      |
        |  - policy engine (A and B)    |
        +-------------------------------+
           ^                       |
           | UDP JSON events       | OpenFlow 1.3
           | (port 9999)           | (flow rules, set_queue)
           |                       v
                  DATA PLANE (Mininet)

 h1 chat server ---- s1 ====== 10 Mbit/s bottleneck ====== s2 ---- h2 client
 10.0.0.1                  q0 default                       |---- h3 client
                           q1 VIP                           '---- h4 iperf noise
                           q2 throttled
```

**How it works:**

1. Clients connect to the chat server over TCP.
2. For every state change (register, room join, message, disconnect) the server sends one UDP JSON packet to the controller containing the client's IP and TCP source port.
3. The controller maps that `(ip, port)` to a user and room, and decides whether the connection should be prioritised or throttled.
4. It installs OpenFlow rules matching that exact TCP 5-tuple in both directions, sending the packets to a specific Open vSwitch queue on the bottleneck link.

---

## 4. Repository Structure

| Path | Description |
| ----- | ----- |
| `server.py` | Multi-threaded TCP chat server |
| `event_emitter.py` | UDP JSON telemetry emitter used by the server |
| `client.py` | Interactive and scriptable chat client (also exposes the `ChatClient` class for tests) |
| `test_clients.py` | Functional, RTT and scalability test runner |
| `sdn/topology.py` | Mininet topology, OVS QoS queues, and experiment runner |
| `sdn/sdn_controller.py` | Ryu controller: learning switch, telemetry listener, policies |
| `sdn/compare_results.py` | Builds the Baseline vs SDN table and graph |
| `sdn/scripts/` | `install_deps.sh`, `start_controller.sh`, `show_flows.sh`, `cleanup.sh` |
| `sdn/results/` | Raw results, logs, switch evidence, comparison graph |
| `docs/D1_Design_Document.pdf` | Design document |

---

## 5. Chat Application

### 5.1 Server (`server.py`)

* One thread per client on a single TCP port (default `5000`).
* Locks protect the online-user registry, room memberships, and per-client socket writes.
* Line framing: UTF-8, `\n` terminated. Handles split and merged packets and rejects lines over `1024` characters without crashing.
* Usernames and room names: alphanumeric ASCII, maximum 16 characters.
* Rooms must be created before they can be joined, and empty rooms are deleted automatically.

### 5.2 Protocol

| Command | Arguments | Behaviour |
| ----- | ----- | ----- |
| `/register` | `<username>` | Registers the connection. Required before other chat commands. |
| `/users` | none | Returns `Online users: u1, u2, ...` |
| `/msg` | `<user> <text>` | Sends `[Private] <sender>: <text>` to the target and `[To <user>] <text>` to the sender. |
| `/create` | `<room>` | Creates a room. Rejected if it already exists. |
| `/join` | `<room>` | Joins an existing room. |
| `/leave` | `<room>` | Leaves a room. The room is deleted when its last member leaves. |
| `/rooms` | none | Returns active rooms and member counts, e.g. `Rooms: r1(2), r2(1)` |
| `/roommsg` | `<room> <text>` | Broadcasts `[<room>] <sender>: <text>` to all members. |
| `/help` | none | Prints the command list. |
| `/quit` | none | Closes the connection. |

### 5.3 Client (`client.py`)

Interactive mode:

```bash
python3 client.py --host 127.0.0.1 --port 5000 --user alice
```

Scripted mode, for automated demos. Create `cmds.txt`:

```
/create general
/join general
sleep 1
/roommsg general Hello everyone!
/users
```

```bash
python3 client.py --host 127.0.0.1 --port 5000 --user alice --script cmds.txt --delay 0.5 --linger 2.0
```

### 5.4 Server options

```bash
python3 server.py                                   # listens on 0.0.0.0:5000
python3 server.py --host 0.0.0.0 --port 5000 \
    --controller 10.0.0.100:9999 \
    --event-log events.jsonl                        # with SDN telemetry and a local event log
```

---

## 6. Telemetry Specification

When `--controller IP:PORT` is given, the server sends one UDP packet (UTF-8 JSON) for every state change. The `ip` and `port` fields are the client's source IP and source TCP port as seen by the server. With the server address and port 5000, they give the controller the full TCP 5-tuple needed for per-connection OpenFlow rules.

| Event | Keys | SDN use |
| ----- | ----- | ----- |
| `connect` | `ts`, `event`, `ip`, `port` | Track new flows |
| `register` | `ts`, `event`, `user`, `ip`, `port` | Bind a flow to a username |
| `private_msg` | `ts`, `event`, `user`, `to`, `ip`, `port`, `bytes` | Monitor 1-to-1 volume, rate limits |
| `room_join` | `ts`, `event`, `user`, `room`, `ip`, `port` | Assign the flow to a queue based on the room |
| `room_leave` | `ts`, `event`, `user`, `room`, `ip`, `port` | Reset priority |
| `room_msg` | `ts`, `event`, `user`, `room`, `ip`, `port`, `bytes`, `recipients` | Detect spam, throttle |
| `disconnect` | `ts`, `event`, `user`, `ip`, `port` | Remove the client's flow rules |

Sample payload:

```json
{"ts": 1792763662.541, "event": "room_join", "user": "alice", "room": "vip", "ip": "10.0.0.2", "port": 48122}
```

---

## 7. SDN Controller and Policies

`sdn/sdn_controller.py` is a Ryu application (OpenFlow 1.3) that provides:

1. **L2 learning switch.** Learns MAC addresses so ARP, ping and TCP work normally.
2. **Telemetry listener.** A background thread on UDP 9999 that parses events and keeps a session table keyed by `(ip, port)`.
3. **Policy A: priority.** A connection that joins a VIP room (`vip`, `load`) or registers as a VIP user (`rttA`, `rttB`) gets rules in both directions with `set_queue:1`. The rules are removed on `room_leave` or `disconnect`.
4. **Policy B: spam throttle.** A user sending more than 40 messages per second is moved to queue 2 (capped at 10% of the link) for 10 seconds.

Mode and settings are controlled with environment variables:

| Variable | Default | Meaning |
| ----- | ----- | ----- |
| `SDN_MODE` | `sdn` | `baseline` = learning switch only; `sdn` = policies enabled |
| `VIP_ROOMS` | `vip,load` | Rooms that get priority |
| `VIP_USERS` | `rttA,rttB` | Users that get priority |
| `SPAM_LIMIT` | `40` | Messages per second before throttling |
| `THROTTLE_SECONDS` | `10` | Throttle duration |
| `CHAT_SERVER_IP` / `CHAT_SERVER_PORT` | `10.0.0.1` / `5000` | Chat server address |
| `TELEMETRY_PORT` | `9999` | UDP listen port |

---

## 8. Network Topology and QoS

`sdn/topology.py` builds the Mininet network: two OpenFlow switches (`s1`, `s2`) joined by a 10 Mbit/s bottleneck link, with the server on `s1` and the clients and noise generator on `s2`. A virtual port `ctl0` (10.0.0.100) connects the server to the controller's telemetry listener.

Open vSwitch HTB queues are configured on both bottleneck ports:

| Queue | Purpose | Settings |
| ----- | ----- | ----- |
| 0 | Default / best effort | min 20% of link |
| 1 | VIP (high priority) | min 60% of link, highest priority |
| 2 | Throttled | max 10% of link |

In experiment mode, `topology.py` also starts the chat server, runs the `rtt` and `scale` tests from h2, and saturates the bottleneck with 12 Mbit/s UDP iperf traffic in each direction (options: `--bw`, `--bg-mbit`, `--repeats`).

---

## 9. Testing and Benchmarks

Start `server.py` first, then run `test_clients.py`:

```bash
# Pass/fail checks for all commands and framing
python3 test_clients.py functional --host 127.0.0.1 --port 5000

# Private-message acknowledgement and delivery latency
python3 test_clients.py rtt --host 127.0.0.1 --port 5000 --messages 200 --interval 0.05 --csv results.csv

# N clients in one room, M messages each
python3 test_clients.py scale --host 127.0.0.1 --port 5000 --clients 20 --messages 10 --interval 0.05 --csv results.csv
```

---

## 10. Results

Setup: 10 Mbit/s bottleneck, 12 Mbit/s UDP background load in each direction, `rtt` test (200 messages) and `scale` test (10 clients x 20 messages), 3 repeats per configuration. Mean of 3 runs:

| Metric | Baseline | SDN |
| ----- | ----- | ----- |
| Delivery latency avg (ms) | 1.95 | 3.46 |
| Delivery latency p95 (ms) | 5.65 | 12.22 |
| Delivery latency max (ms) | 26.1 | 29.3 |
| Messages lost / delivery ratio (scale) | 0 / 1.00 | 0 / 1.00 |

No messages were lost in either configuration. In two of three SDN runs the p95 delivery latency (2.9 ms and 3.3 ms) was lower than every baseline run (4.2 to 7.4 ms), but the third SDN run was much worse (30.5 ms), which raises the SDN mean above baseline. With only 3 repeats, no reliable improvement can be claimed. Switch evidence confirms that the VIP chat traffic used queue 1 while the iperf flood used queue 0.

Files: `sdn/results/comparison.png`, `comparison.csv`, `results_baseline.csv`, `results_sdn.csv`, `switch_evidence_*.txt`.

---

## 11. Limitations

* Priority is applied per TCP connection, not per message.
* Telemetry is unauthenticated, best-effort UDP; lost events mean missed policy changes.
* The experiment uses 3 repeats on a virtual network, so latency numbers are indicative only.
* The default VIP rooms and users match the names used by the test suite.

---

## 12. Team

| Member | SRN | Contribution |
| ----- | ----- | ----- |
| Abhinav Kulkarni | PES1UG25CS014 | Chat application: TCP server, client, protocol, UDP telemetry, test suite |
| Akshith Singh | PES1UG25CS048 | SDN: Ryu controller, priority and spam-throttle policies, Baseline vs SDN comparison |
| Amogh B | PES1UG25CS053 | Mininet: topology, bottleneck link, OVS QoS queues, background traffic, experiment automation |

Design document: `docs/D1_Design_Document.pdf`
