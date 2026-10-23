# SDN-Integrated Multi-Client TCP Chat Application

## 1. Project Overview

This project implements a multi-client chat application using low-level TCP sockets, designed to integrate with a Software-Defined Networking (SDN) controller inside a Mininet environment. Users can register, send private messages, explicitly create and join chat rooms, and broadcast messages to room members.

To support dynamic network management, the chat server includes an out-of-band UDP telemetry emitter that sends real-time application events (JSON) to the SDN controller, allowing the network to classify traffic, apply user/room policies, and prioritize flows dynamically.

## 2. Work Completed So Far (Part 1: Socket Layer & Telemetry)

All core socket programming, application protocol design, concurrency handling, and automated testing modules are complete and verified:

* **Concurrent TCP Server (`server.py`):**

  * Multi-threaded architecture handling multiple simultaneous client connections over a single TCP port (default `5000`).

  * Thread-safe state management using locks for online user registries, room memberships, and per-client socket writes.

  * Robust TCP line framing (UTF-8, `\n` terminated) capable of handling split packets, merged packets, and rejecting oversized lines (`>1024` chars) without crashing.

* **Application Features:**

  * User Registration (`/register`) with duplicate and alphanumeric validation.

  * Explicit Room Management (`/createroom`, `/join`, `/leave`, `/rooms`) ensuring users can only join existing rooms and automatically cleaning up empty rooms on leave/disconnect.

  * Messaging (`/msg` for 1-to-1 private messages, `/roommsg` for room-wide broadcasts).

* **SDN Integration Hook (`EventEmitter`):**

  * Non-blocking, fire-and-forget UDP socket that emits JSON-formatted events (`connect`, `register`, `private_msg`, `room_join`, `room_leave`, `room_msg`, `disconnect`) directly to the SDN controller IP/port and/or a local `.jsonl` log file.

* **Client & Testing Suite (`client.py` & `test_clients.py`):**

  * Interactive CLI mode and automated batch-script execution mode (`--script`).

  * Automated verification suite with three modes: `functional` (end-to-end command and framing checks), `rtt` (latency distribution metrics), and `scale` (high-concurrency room broadcast stress testing with CSV export).

## 3. Repository Structure

| File | Description | 
| ----- | ----- | 
| `server.py` | Multi-threaded TCP chat server and UDP SDN event emitter. | 
| `client.py` | Interactive and scriptable TCP chat client (also exposes `ChatClient` class for tests). | 
| `test_clients.py` | Automated test runner for functional verification, RTT latency, and scalability benchmarks. | 
| `README.md` | Project documentation, protocol specs, and handover architecture guide. | 

*Note: Built using Python 3.8+ standard library only. No external pip dependencies are required for the socket layer.*

## 4. How to Run & Verify

### A. Starting the Server

Run the server locally or on a designated Mininet host (e.g., `h1`):

```
# Basic run (listens on 0.0.0.0:5000)
python3 server.py

# Run with SDN Controller UDP hook and local event logging enabled
python3 server.py --host 0.0.0.0 --port 5000 \
    --controller 10.0.0.100:9999 \
    --event-log events.jsonl

```

### B. Running the Client

**Interactive Mode:**

```
python3 client.py --host 127.0.0.1 --port 5000 --user alice

```

**Scripted Mode (for automated Mininet demos):**
Create a text file (e.g., `cmds.txt`):

```
# Sample script
/createroom general
/join general
sleep 1
/roommsg general Hello everyone!
/users

```

Run the client with the script:

```
python3 client.py --host 127.0.0.1 --port 5000 --user alice --script cmds.txt --delay 0.5 --linger 2.0

```

### C. Running the Test & Benchmark Suite

Make sure `server.py` is running before executing these commands.

**1. Functional Verification (Pass/Fail checks for all requirements):**

```
python3 test_clients.py functional --host 127.0.0.1 --port 5000

```

**2. RTT Latency Benchmark (Private message acknowledgement & delivery time):**

```
python3 test_clients.py rtt --host 127.0.0.1 --port 5000 --messages 200 --interval 0.05 --csv results.csv

```

**3. Scalability Stress Test (**$N$ **clients in 1 room sending** $M$ **messages each):**

```
python3 test_clients.py scale --host 127.0.0.1 --port 5000 --clients 20 --messages 10 --interval 0.05 --csv results.csv

```

## 5. Application Protocol & SDN Telemetry Specification (Handover Reference)

### A. Wire Protocol (TCP Port 5000)

* **Encoding:** UTF-8 plain text, newline-delimited (`\n`).

* **Constraints:** Max line length = `1024` chars. Usernames and room names = alphanumeric ASCII only, max `16` chars.

| Command | Arguments | Behavior / Server Response | 
| ----- | ----- | ----- | 
| `/register` | `<username>` | Registers connection. Must be called before chat commands. | 
| `/users` | *None* | Returns `Online users: u1, u2, ...` | 
| `/msg` | `<user> <text>` | Sends `[Private] <sender>: <text>` to target; confirms `[To <user>] <text>` to sender. | 
| `/createroom` | `<room>` | Initializes a new room on the server. Rejects if room already exists. | 
| `/join` | `<room>` | Joins an existing room. Fails if `/createroom` was not called first. | 
| `/leave` | `<room>` | Removes user from room. Deletes room if member count drops to 0. | 
| `/rooms` | *None* | Returns active rooms and member counts: `Rooms: r1(2), r2(1)` | 
| `/roommsg` | `<room> <text>` | Broadcasts `[<room>] <sender>: <text>` to all current room members. | 
| `/help` | *None* | Prints command syntax list. | 
| `/quit` | *None* | Cleanly closes connection. | 

### B. SDN Controller Telemetry Format (UDP JSON)

Whenever `--controller IP:PORT` is passed to `server.py`, the server sends a single UDP packet containing a UTF-8 JSON object for every state change.

**Crucial Mapping Info for SDN:** The `ip` and `port` fields in every JSON payload represent the **client's source IP and source TCP port** as seen by the server. Together with the server's IP and port (`5000`), the SDN controller has the exact TCP 5-tuple `(src_ip, src_port, dst_ip, 5000, TCP)` needed to install granular OpenFlow rules per user or room.

| Event Type (`event`) | JSON Payload Keys | SDN Use Case | 
| ----- | ----- | ----- | 
| `connect` | `ts`, `event`, `ip`, `port` | Track new TCP flow establishment. | 
| `register` | `ts`, `event`, `user`, `ip`, `port` | Bind a TCP `(ip, port)` flow to a specific `username`. | 
| `private_msg` | `ts`, `event`, `user`, `to`, `ip`, `port`, `bytes` | Monitor 1-to-1 traffic volume; apply user-specific rate limits. | 
| `room_join` | `ts`, `event`, `user`, `room`, `ip`, `port` | Assign user's TCP flow to a high/low priority QoS queue based on `room`. | 
| `room_leave` | `ts`, `event`, `user`, `room`, `ip`, `port` | Reset flow priority when a user exits a prioritized room. | 
| `room_msg` | `ts`, `event`, `user`, `room`, `ip`, `port`, `bytes`, `recipients` | Detect heavy broadcast rooms or spam; dynamically reroute or throttle. | 
| `disconnect` | `ts`, `event`, `user`, `ip`, `port` | Clean up active OpenFlow rules for this client. | 

**Sample UDP Payload:**

```
{"ts": 1792763662.541, "event": "room_join", "user": "alice", "room": "vip", "ip": "10.0.0.2", "port": 48122}

```

## 6. Future Architecture & Next Steps (Part 2 & Part 3 Handover)

To complete the full deliverables (Mininet + SDN Implementation, Dynamic Traffic Management, Challenging Scenarios, and Performance Comparison), the upcoming phases should follow the architecture below.

### System Architecture Diagram

```
+-----------------------------------------------------------------------------------+
|                               CONTROL PLANE                                       |
|                                                                                   |
|   +---------------------------------------------------------------------------+   |
|   |                        SDN Controller (Ryu / POX)                         |   |
|   |                                                                           |   |
|   |  1. UDP Telemetry Listener (Port 9999) <--- Parses JSON events            |   |
|   |  2. User/Room Flow Mapper              <--- Maps (ip, tcp_port) to Room   |   |
|   |  3. Policy & QoS Engine                <--- Priority Queues / Rate Limits |   |
|   +---------------------------------------------------------------------------+   |
|                  ^                                              |                 |
|                  | Out-of-Band UDP JSON                         | OpenFlow 1.3    |
|                  | (Events: register, room_join, etc.)          | (Flow_Mod,      |
|                  |                                              v  Set-Queue,     |
+------------------|----------------------------------------------|-----------------+
|                  |                DATA PLANE (Mininet)          |                 |
|                  |                                              v                 |
|   +--------------+---+          +------------------+         +------------------+ |
|   |   Chat Server    |          |  OpenFlow Switch |         |  OpenFlow Switch | |
|   |    (Host h1)     |=========>|       (s1)       |========>|       (s2)       | |
|   |  10.0.0.1:5000   |          |   HTB Queues:    |  Link   |                  | |
|   +------------------+          |   q0: Default    | (10Mbps)|                  | |
|                                 |   q1: VIP Room   |         +------------------+ |
|                                 |   q2: Throttled  |            /      |      \   |
|                                 +------------------+           /       |       \  |
|                                                              h2       h3       h4 |
|                                                           (alice)   (bob)   (iperf|
|                                                                              noise|
+-----------------------------------------------------------------------------------+

```

### Planned Directory Structure for Full Repo

```
project-root/
├── server.py               # (Completed) TCP Chat Server + UDP Emitter
├── client.py               # (Completed) TCP Chat Client
├── test_clients.py         # (Completed) Automated Verification & CSV Benchmarking
├── topology.py             # (Next) Custom Mininet Python script with TCLinks & QoS Queues
├── sdn_controller.py       # (Next) Ryu SDN Controller with UDP listener thread + OpenFlow logic
├── scripts/                # (Next) Helper bash scripts to configure OVS queues and run experiments
└── results/                # (Next) Output CSVs and matplotlib scripts comparing Baseline vs SDN

```

### Step-by-Step Implementation Guide for Teammates

#### Task 1: Mininet Topology (`topology.py`)

1. Create a multi-switch topology (e.g., 2 OpenFlow switches `s1` and `s2` connected by a bottleneck link using `TCLink(bw=10, delay='5ms')`).

2. Attach `h1` (Chat Server) to `s1`, and client hosts (`h2..hN`) to `s2`.

3. Configure Open vSwitch (OVS) QoS queues on the bottleneck link using `ovs-vsctl`:

   * **Queue 0:** Default best-effort queue (standard chat & background traffic).

   * **Queue 1:** High-priority guaranteed bandwidth queue (for prioritized chat rooms, e.g., `vip` or `emergency`).

   * **Queue 2:** Low-priority / rate-limited queue (for noisy users).

#### Task 2: SDN Controller (`sdn_controller.py` using Ryu)

1. **L2 Learning Switch Baseline:** Implement standard MAC learning so ARP and basic IP/TCP connectivity work out of the box.

2. **UDP Event Thread:** Spawn a background thread in the Ryu app using `ryu.lib.hub.spawn` listening on UDP port `9999`. Parse incoming JSON lines from `server.py`.

3. **Dynamic Policy Enforcement (Deliverable D2):**

   * **Policy A — Room Prioritization:** When the UDP listener receives `{"event": "room_join", "room": "vip", "ip": X, "port": Y}`, install a high-priority OpenFlow rule matching `(ipv4_src=X, tcp_src=Y, ipv4_dst=10.0.0.1, tcp_dst=5000)` (and the reverse server-to-client direction) using action `OFPActionSetQueue(1)`.

   * **Policy B — Spammer Mitigation / Rate Limiting:** Track `room_msg` or `private_msg` frequency per `user` in the controller. If a user exceeds $K$ messages per second, dynamically install a flow rule directing their `(ip, port)` tuple to `Queue 2` (throttled) or drop their packets for a cooldown period.

#### Task 3: Challenging Scenarios & Performance Evaluation

To score full marks on the rubric for **Challenging Scenario** and **Performance Evaluation**:

1. **Baseline Run (Static Network):** Run `test_clients.py rtt` and `scale` across the Mininet topology while injecting heavy background UDP congestion on the `s1-s2` link using `iperf`. Record the CSV metrics (`results_baseline.csv`).

2. **SDN Dynamic Run (Prioritized Network):** Repeat the exact same congestion experiment with the SDN controller active and the test clients joined to the prioritized room (`vip`). Record the CSV metrics (`results_sdn.csv`).

3. **Comparison:** Plot `delivery_ms_avg`, `delivery_ms_p95`, and `delivery_ratio` comparing Baseline vs. SDN under link congestion to demonstrate how application-aware SDN control protects chat responsiveness.