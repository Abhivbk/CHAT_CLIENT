# Person 2 (SDN Network) — Complete Step-by-Step Guide

Project: **SDN-Integrated Multi-Client TCP Chat Application** (Mininet + Open vSwitch + Ryu)
Your part: build the virtual network, the SDN controller, the QoS queues, and prove with a Baseline vs SDN comparison that it works.

> Everything below is done **inside your Ubuntu VM** (VirtualBox), not on Windows — except taking screenshots/sending files.
> Windows Wireshark is not needed for this; you will install Wireshark/tshark *inside the VM* so it can see the virtual network.

---------------------------------------------------------------------

## 0. What your teammates already built (from the GitHub repo `Abhivbk/CHAT_CLIENT`)

| Item | Value |
|---|---|
| Chat server | `server.py`, TCP port **5000**, run on Mininet host **h1** |
| Telemetry | server sends **UDP JSON** to `--controller IP:PORT` for every event (`connect, register, private_msg, room_join, room_leave, room_msg, disconnect`) with the client's `ip` and `port` |
| Tests (Person 1/3) | `test_clients.py functional | rtt | scale --csv file.csv` |
| What the README asks YOU for | `topology.py`, `sdn_controller.py`, `scripts/`, QoS queues, Baseline vs SDN under congestion |

My files below implement exactly that handover (names match the README: `topology.py`, `sdn_controller.py`, `scripts/`, `results/`).

---------------------------------------------------------------------

## 1. Everything you need to download / install (inside the VM)

Open a terminal in the Ubuntu VM. **Ubuntu 22.04 is strongly recommended** (your teacher's manual says 20.04/22.04). Ryu is fragile on newer Python versions.

```bash
# 1. Get the team code
cd ~
git clone https://github.com/Abhivbk/CHAT_CLIENT
# (this gives you server.py, client.py, test_clients.py, event_emitter.py, main.py)

# 2. Copy my Person-2 folder into the VM (see section 2), then:
cd ~/person2_sdn
bash scripts/install_deps.sh
```

`install_deps.sh` installs: **mininet, openvswitch-switch, git, python3-pip/venv, iperf, wireshark + tshark, matplotlib, pandas, xterm**, and **Ryu** (in a virtual environment `~/ryu-env`, with `eventlet==0.30.2`).

When the Wireshark installer asks *"Should non-superusers be able to capture packets?"* choose **Yes**, then run `sudo usermod -aG wireshark $USER` and log out/in.

If Ryu fails to install, try: `pip install "setuptools<68" wheel` first, then `pip install "eventlet==0.30.2" ryu` (already in the script). If it still fails, tell me the exact error message.

### How to get my files into the VM
Easiest options:
- Drag-and-drop / shared clipboard needs *Guest Additions*; simpler: upload the zip to Google Drive/WhatsApp-to-self, open it in the VM's browser, download to `~/`. Then `unzip person2_sdn.zip -d ~/`.
- Or create a VirtualBox *Shared Folder* (Devices → Shared Folders) and copy from `/media/sf_...`.

---------------------------------------------------------------------

## 2. Files in your folder

```
person2_sdn/
├── topology.py            # Mininet: 2 switches, 4 hosts, 10 Mbit/s bottleneck, QoS queues, experiment runner
├── sdn_controller.py      # Ryu controller: learning switch + UDP listener + priority + spam-throttle policies
├── compare_results.py     # Baseline vs SDN table + graph
├── SETUP_GUIDE.md         # this file
├── scripts/
│   ├── install_deps.sh    # one-shot installer
│   ├── start_controller.sh# starts Ryu in baseline or sdn mode
│   ├── show_flows.sh      # prints flow rules + queue stats (demo evidence)
│   └── cleanup.sh         # resets Mininet/OVS
└── results/               # CSVs, logs, graphs are written here
```

### The network (draw this in your report)

```
                   ctl0 = 10.0.0.100  (Ryu listens for telemetry UDP 9999)
                    |
 h1 server ---- s1 =======10 Mbit/s bottleneck======= s2 ---- h2 client
 10.0.0.1                 (queue 0 default,                 |--- h3 client
                           queue 1 VIP, queue 2 throttled)  '--- h4 iperf noise
```

---------------------------------------------------------------------

## 3. Step-by-step

### Step 1 — Verify Mininet (teammate asked for a screenshot)
```bash
sudo apt update && sudo apt install mininet -y     # if not already done
sudo mn --test pingall
```
Expect `0% dropped`. **Screenshot #1.**

### Step 2 — Three-host network
```bash
sudo mn --topo single,3
```
Inside `mininet>` run one by one: `nodes`, `net`, `dump`, `pingall`, then `exit`. Then:
```bash
sudo mn -c
```
**Screenshot #2** (pingall showing 0% dropped). Send #1 and #2 to the team. (Your teammate's message said to do only steps 1-3 first; the rest follows.)

### Step 3 — Prove Ryu works with a stock app (sanity check)
Terminal 1:
```bash
source ~/ryu-env/bin/activate
ryu-manager ryu.app.simple_switch_13
```
Terminal 2:
```bash
sudo mn --topo single,3 --controller remote,ip=127.0.0.1,port=6653 --switch ovsk,protocols=OpenFlow13
mininet> pingall
```
Terminal 3 (while Mininet is running):
```bash
sudo ovs-ofctl -O OpenFlow13 dump-flows s1
```
You should see OpenFlow rules. **Screenshot #3** (Ryu log + pingall + dump-flows). Stop both (`exit`, Ctrl+C), then `sudo mn -c`.

### Step 4 — Run MY topology + controller in **baseline** mode
```bash
cd ~/person2_sdn
```
Terminal 1 (leave open):
```bash
bash scripts/start_controller.sh baseline
```
Terminal 2:
```bash
sudo python3 topology.py
mininet> pingall
mininet> net
```
Ryu's log must print `Switch connected: dpid=1` and `dpid=2`. **Screenshot #4.**

### Step 5 — Run the chat on Mininet hosts (manual check)
In the `mininet>` prompt:
```
mininet> xterm h1 h2 h3
```
- In **h1** xterm:
  ```bash
  cd ~/CHAT_CLIENT
  python3 server.py --host 0.0.0.0 --port 5000 --controller 10.0.0.100:9999 --event-log events.jsonl
  ```
- In **h2** xterm: `cd ~/CHAT_CLIENT && python3 client.py --host 10.0.0.1 --port 5000 --user alice`
- In **h3** xterm: same with `--user bob`
- Try: `/create vip`, `/join vip`, `/roommsg vip hello`, `/msg bob hi`
  (Person 1's README says `/createroom` but their test file uses `/create` — **ask Person 1 which is correct**; type `/help` to see.)

In the Ryu terminal you should see lines like `EVENT room_join user=alice room=vip flow=10.0.0.2:48122`. In baseline mode nothing is prioritised — events are only logged. **Screenshot #5** (two clients chatting + Ryu event log).

`10.0.0.100` is the controller: my `topology.py` creates a virtual cable (`ctl0`↔`s1`) so the server on h1 can reach Ryu, which runs on the VM. (Without this the telemetry packets would go nowhere.)

### Step 6 — SDN mode: prove the policy installs rules
Stop everything (`exit`, Ctrl+C), `bash scripts/cleanup.sh`. Then:
Terminal 1: `bash scripts/start_controller.sh sdn`
Terminal 2: `sudo python3 topology.py` and redo Step 5 (server on h1, clients on h2/h3).
In the client use the room **vip** (`/create vip`, `/join vip`). The Ryu log shows:
`POLICY A: prioritising ('10.0.0.2', 48122) (user=alice) -> queue 1`.
Terminal 3:
```bash
bash scripts/show_flows.sh
```
You should see rules with `set_queue:1` on `s2` (client→server) and on `s1` (server→client). **Screenshot #6 + save the output** (`bash scripts/show_flows.sh > results/flows_sdn_demo.txt`).

*Spam policy demo:* run a client in scripted mode sending >40 messages/second to a room → Ryu prints `POLICY B: ... throttling`, and flows with `set_queue:2` appear.

### Step 7 — Wireshark evidence (inside the VM)
Open Wireshark (`sudo wireshark`), capture on `s2-eth1` (the bottleneck) while chat runs:
- display filter `tcp.port == 5000` → chat traffic
- display filter `udp.port == 9999` → the telemetry packets to the controller (JSON visible)
Save screenshot(s) and a capture file (File → Save As → `results/chat_capture.pcapng`).

### Step 8 — Automated Baseline vs SDN experiment (the important result)
This runs the team's own `test_clients.py` (rtt + scale) from h2 against the server on h1 **while h4/h1 flood the bottleneck with 12 Mbit/s UDP in both directions**, 3 repeats each.

```bash
cd ~/person2_sdn
bash scripts/cleanup.sh

# --- BASELINE ---
# Terminal 1:  bash scripts/start_controller.sh baseline
# Terminal 2:
sudo python3 topology.py --experiment baseline --chat-dir ~/CHAT_CLIENT
# wait for "*** Done"; then Ctrl+C Terminal 1 and:
bash scripts/cleanup.sh

# --- SDN ---
# Terminal 1:  bash scripts/start_controller.sh sdn
# Terminal 2:
sudo python3 topology.py --experiment sdn --chat-dir ~/CHAT_CLIENT
```
Each run takes several minutes. Outputs appear in `results/`:
`results_baseline.csv`, `results_sdn.csv`, `run_*.log`, `switch_evidence_*.txt`, `events_*.jsonl`, `server_*.log`, `iperf_*.txt`.

Then:
```bash
python3 compare_results.py
```
→ `results/comparison.csv` and `results/comparison.png` (avg/p95 delivery time, lost messages, delivery ratio).

**How the SDN run gets prioritised:** the controller prioritises (queue 1) any connection that joins room `vip` or `load` (the room the team's `scale` test uses), or registers as `rttA`/`rttB` (the users of the `rtt` test). You can change these with `VIP_ROOMS` / `VIP_USERS` environment variables. Be honest in the report: a single TCP connection can't be told apart per message, so priority is per **connection (5-tuple)**, learned from the server's telemetry — that's exactly why Person 1 added the UDP telemetry.

If the results don't show an improvement, don't fake it: try `--bg-mbit 15`, or `--bw 5`, or more repeats, and explain what you see.

### Step 9 — Hand-over to the team
Send **Person 3** (the tester/benchmarker):
- The command to start everything (Terminal 1/2 above) and the host table: h1=10.0.0.1 (server), h2=10.0.0.2, h3=10.0.0.3, h4=10.0.0.4 (iperf), controller 10.0.0.100:9999
- `topology.py`, `sdn_controller.py`, `scripts/`
- `results_baseline.csv`, `results_sdn.csv`, `comparison.png`
- Tell them: prioritised = room `vip`/`load` or users `rttA`/`rttB`

Send **Person 1**: confirmation that telemetry reaches the controller (screenshot #5/#6), and ask which room-creation command is correct (`/create` vs `/createroom`).

---------------------------------------------------------------------

## 4. What to submit (checklist)

I could not open your teacher's Drive folder, so **check the assignment brief for the exact list**. Based on the team README, your part should include:

- [ ] `topology.py`
- [ ] `sdn_controller.py`
- [ ] `scripts/` folder
- [ ] `results/results_baseline.csv`, `results/results_sdn.csv`
- [ ] `results/comparison.png` + `comparison.csv`
- [ ] `results/switch_evidence_*.txt` (flow rules + queue stats) and `flows_sdn_demo.txt`
- [ ] Screenshots: #1 `mn --test pingall`, #2 single,3 pingall, #3 Ryu+dump-flows, #4 my topology + `Switch connected`, #5 chat across hosts + event log, #6 `set_queue` flow rules, Wireshark (chat + telemetry)
- [ ] `chat_capture.pcapng` (optional)
- [ ] A short write-up (1–2 pages): topology diagram, how telemetry → flow rules works, queue design (q0/q1/q2), the two policies, Baseline vs SDN table/graph, limitations

Everyone shares one GitHub repo — put these in the repo root (`topology.py`, `sdn_controller.py`, `scripts/`, `results/`) exactly like the README's "planned directory structure".

---------------------------------------------------------------------

## 5. Troubleshooting

| Problem | Fix |
|---|---|
| `ryu-manager: command not found` | `source ~/ryu-env/bin/activate` |
| Ryu import errors (`ALREADY_HANDLED`) | `pip install "eventlet==0.30.2"` in the venv |
| `pingall` 100% dropped | Ryu not running / wrong terminal order. Start Ryu first; check log shows `Switch connected` ×2 |
| `Unable to contact the remote controller` | Ryu not started or not on port 6653 |
| Leftover state / odd errors | `bash scripts/cleanup.sh` |
| No `EVENT` lines in Ryu | server not started with `--controller 10.0.0.100:9999`; check `ip addr show ctl0` |
| No `set_queue` flows | Ryu started in `baseline` mode, or you didn't join a VIP room |
| `iperf: command not found` | `sudo apt install iperf` |
| Internet broke after running | `bash scripts/cleanup.sh` (removes `ctl0`) |
| `python3 server.py` fails in h1 | run `cd ~/CHAT_CLIENT` first; server uses only stdlib |
| Experiment tests show errors | run `python3 test_clients.py functional --host 10.0.0.1` from an h2 xterm first |

**Honest note:** I couldn't run Mininet/Ryu here, so the code has been syntax-checked but not tested in a real VM. If something breaks, paste the exact error/log and I'll fix it.
