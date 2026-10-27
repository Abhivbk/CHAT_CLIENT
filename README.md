# SDN-Integrated Multi-Client TCP Chat Application

## 1. Project Overview

This project implements a multi-client chat application using low-level TCP sockets, designed to integrate with a Software-Defined Networking (SDN) controller inside a Mininet environment. Users can register, send private messages, explicitly create and join chat rooms, and broadcast messages to room members.

To support dynamic network management, the chat server includes an out-of-band UDP telemetry emitter that sends real-time application events (JSON) to the SDN controller, allowing the network to classify traffic, apply user/room policies, and prioritize flows dynamically.

## 2. Chat Application & Telemetry (Socket Layer)

The socket programming, application protocol, concurrency handling and automated tests are implemented:

* **Concurrent TCP Server (`server.py`):**

  * Multi-threaded architecture handling multiple simultaneous client connections over a single TCP port (default `5000`).

  * Thread-safe state management using locks for online user registries, room memberships, and per-client socket writes.

  * Robust TCP line framing (UTF-8, `\n` terminated) capable of handling split packets, merged packets, and rejecting oversized lines (`>1024` chars) without crashing.

* **Application Features:**

  * User Registration (`/register`) with duplicate and alphanumeric validation.

  * Explicit Room Management (`/create`, `/join`, `/leave`, `/rooms`) ensuring users can only join existing rooms and automatically cleaning up empty rooms on leave/disconnect.

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
| `event_emitter.py` | UDP JSON telemetry emitter used by the server. | 
| `sdn/topology.py` | Mininet topology (2 switches, 10 Mbit/s bottleneck, OVS QoS queues) and experiment runner. | 
| `sdn/sdn_controller.py` | Ryu controller: learning switch, telemetry listener, priority and spam-throttle policies. | 
| `sdn/compare_results.py` | Builds the Baseline vs SDN table and graph. | 
| `sdn/scripts/` | Helper scripts: install dependencies, start controller, show flows, cleanup. | 
| `sdn/results/` | Raw results, logs, switch evidence and comparison graph. | 
| `docs/D1_Design_Document.pdf` | Design document with build/run instructions. | 
| `README.md` | Project documentation and protocol specs. | 

*Note: The chat application uses the Python 3.8+ standard library only. The SDN part needs Mininet, Open vSwitch, iperf and Ryu (see section 6).*

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
/create general
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
| `/create` | `<room>` | Initializes a new room on the server. Rejects if room already exists. | 
| `/join` | `<room>` | Joins an existing room. Fails if `/create` was not called first. | 
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

## 6. SDN Network, Controller & Results

The server sends UDP telemetry to a Ryu controller, which gives selected chat connections a high-priority queue on a congested link.

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

### How to Run the SDN Experiment (Ubuntu 22.04 VM)

```
cd sdn
bash scripts/install_deps.sh          # one time: Mininet, OVS, iperf, Ryu (~/ryu-env)
bash scripts/cleanup.sh

# Terminal 1 - controller (sdn or baseline)
bash scripts/start_controller.sh sdn

# Terminal 2 - network + automatic experiment (results go to sdn/results/)
sudo python3 topology.py --experiment sdn --chat-dir ~/CHAT_CLIENT

# Repeat with 'baseline' in both terminals, then:
python3 compare_results.py            # writes results/comparison.csv and comparison.png
```

### Interactive Demo

Start the controller (`bash scripts/start_controller.sh sdn`), then `sudo python3 topology.py` (no `--experiment`). At the `mininet>` prompt run `xterm h1 h2 h3`, and:

```
# h1: server, reporting to the controller (10.0.0.100 is the controller's telemetry address)
python3 server.py --host 0.0.0.0 --port 5000 --controller 10.0.0.100:9999 --event-log events.jsonl
# h2 and h3: clients
python3 client.py --host 10.0.0.1 --port 5000 --user alice      # and --user bob
# in a client: /create vip, /join vip, /roommsg vip hello
bash scripts/show_flows.sh      # shows the set_queue flow rules and queue stats
```

The controller log prints `POLICY A: prioritising ...` when a client joins `vip`. Sending more than 40 messages per second from one client triggers `POLICY B`.

### Troubleshooting

| Problem | Fix |
|---|---|
| `ryu-manager: command not found` | `source ~/ryu-env/bin/activate` |
| Ryu import error (`ALREADY_HANDLED`) | `pip install "eventlet==0.30.2"` in the Ryu venv |
| `pingall` shows 100% dropped | Start Ryu first; its log must show `Switch connected` twice |
| `Unable to contact the remote controller` | Ryu is not running on port 6653 |
| No `EVENT` lines in the controller log | Server was not started with `--controller 10.0.0.100:9999` |
| No `set_queue` flows | Controller is in `baseline` mode, or no client joined a VIP room |
| Leftover state or odd errors | `bash scripts/cleanup.sh` |

See `docs/D1_Design_Document.pdf` for the design write-up.

### Policies Implemented

* **Policy A - Priority:** a connection that joins room `vip` or `load`, or registers as `rttA`/`rttB`, gets OpenFlow rules in both directions that use queue 1.
* **Policy B - Spam throttle:** a user sending more than 40 messages per second is moved to queue 2 (capped at 10% of the link) for 10 seconds.

### Results

Under 12 Mbit/s UDP congestion each way on the 10 Mbit/s link (3 repeats), no messages were lost in either configuration. SDN gave lower p95 delivery latency in 2 of 3 runs, but one outlier run made the SDN mean higher than baseline, so no reliable improvement can be claimed. See `sdn/results/comparison.png` and `comparison.csv`.
