#!/usr/bin/env python3
"""
sdn_controller.py  -  Ryu SDN controller for the Multi-Client TCP Chat project
(Person 2 deliverable)

What it does
------------
1. L2 learning switch (OpenFlow 1.3) so ARP / ping / TCP work out of the box.
2. Listens for UDP JSON telemetry from the chat server (default UDP port 9999).
   The server (Person 1) sends events: connect, register, private_msg,
   room_join, room_leave, room_msg, disconnect.  Each event carries the
   client's source IP + TCP port, i.e. the TCP 5-tuple of that chat connection.
3. Policy A - Priority: a connection that joins a VIP room (or registers as a
   VIP user) gets OpenFlow rules (both directions) that send its packets to
   OVS queue 1 (high priority, guaranteed bandwidth) on the bottleneck link.
4. Policy B - Spam throttle: a user sending more than SPAM_LIMIT messages in one
   second is moved to queue 2 (1 Mbit/s cap) for THROTTLE_SECONDS.

Run modes (environment variable SDN_MODE)
-----------------------------------------
  SDN_MODE=baseline  -> only the learning switch (no policies)  => "Baseline"
  SDN_MODE=sdn       -> learning switch + policies A and B      => "SDN-enabled"

Other optional environment variables
------------------------------------
  CHAT_SERVER_IP   (default 10.0.0.1)
  CHAT_SERVER_PORT (default 5000)
  TELEMETRY_PORT   (default 9999)
  VIP_ROOMS        (default "vip,load")      comma separated room names
  VIP_USERS        (default "rttA,rttB")     comma separated usernames
  SPAM_LIMIT       (default 40)              messages per second
  THROTTLE_SECONDS (default 10)

Start it with:   SDN_MODE=sdn ryu-manager --verbose sdn_controller.py
"""
import json
import os
import socket
import time
from collections import defaultdict, deque

from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.lib import hub
from ryu.lib.packet import arp, ethernet, ether_types, ipv4, packet
from ryu.ofproto import ofproto_v1_3

# ----------------------------------------------------------------- settings
MODE = os.environ.get("SDN_MODE", "sdn").strip().lower()
SERVER_IP = os.environ.get("CHAT_SERVER_IP", "10.0.0.1")
SERVER_PORT = int(os.environ.get("CHAT_SERVER_PORT", "5000"))
TELEMETRY_PORT = int(os.environ.get("TELEMETRY_PORT", "9999"))
VIP_ROOMS = {r.strip() for r in os.environ.get("VIP_ROOMS", "vip,load").split(",") if r.strip()}
VIP_USERS = {u.strip() for u in os.environ.get("VIP_USERS", "rttA,rttB").split(",") if u.strip()}
SPAM_LIMIT = int(os.environ.get("SPAM_LIMIT", "40"))
THROTTLE_SECONDS = int(os.environ.get("THROTTLE_SECONDS", "10"))

# Port 1 on both s1 and s2 is the s1<->s2 bottleneck link (see topology.py).
# Queues only exist on those ports, so set_queue is only used when the output
# port is the trunk port.
TRUNK_PORT = 1
QUEUE_VIP = 1
QUEUE_THROTTLE = 2

PRIO_L2 = 1
PRIO_VIP = 100
PRIO_THROTTLE = 200


class ChatSDN(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ChatSDN, self).__init__(*args, **kwargs)
        self.datapaths = {}                       # dpid -> datapath
        self.mac_to_port = defaultdict(dict)      # dpid -> {mac: port}
        self.ip_to_mac = {}                       # ip -> mac
        self.sessions = {}                        # (ip, port) -> dict
        self.msg_times = defaultdict(deque)       # user -> timestamps
        self.logger.info("=== ChatSDN started: MODE=%s server=%s:%s telemetry UDP %s ===",
                         MODE, SERVER_IP, SERVER_PORT, TELEMETRY_PORT)
        self.logger.info("VIP rooms=%s VIP users=%s spam limit=%s msg/s",
                         sorted(VIP_ROOMS), sorted(VIP_USERS), SPAM_LIMIT)
        hub.spawn(self._udp_listener)

    # ------------------------------------------------------ switch handling
    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def _switch_features(self, ev):
        dp = ev.msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        self.datapaths[dp.id] = dp
        # table-miss: send unknown packets to the controller
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofp.OFPP_CONTROLLER, ofp.OFPCML_NO_BUFFER)]
        self._add_flow(dp, 0, match, actions)
        self.logger.info("Switch connected: dpid=%s", dp.id)

    def _add_flow(self, dp, priority, match, actions, idle=0, hard=0):
        ofp, parser = dp.ofproto, dp.ofproto_parser
        inst = [parser.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=dp, priority=priority, match=match,
                                instructions=inst, idle_timeout=idle, hard_timeout=hard)
        dp.send_msg(mod)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in(self, ev):
        msg = ev.msg
        dp = msg.datapath
        ofp, parser = dp.ofproto, dp.ofproto_parser
        in_port = msg.match["in_port"]

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]
        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            return
        dst, src = eth.dst, eth.src

        # learn MAC -> port, and IP -> MAC
        self.mac_to_port[dp.id][src] = in_port
        a = pkt.get_protocol(arp.arp)
        if a:
            self.ip_to_mac[a.src_ip] = a.src_mac
        ip = pkt.get_protocol(ipv4.ipv4)
        if ip:
            self.ip_to_mac[ip.src] = src

        out_port = self.mac_to_port[dp.id].get(dst, ofp.OFPP_FLOOD)
        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofp.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self._add_flow(dp, PRIO_L2, match, actions, idle=60)

        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        out = parser.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        dp.send_msg(out)

    # ---------------------------------------------------- telemetry listener
    def _udp_listener(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("0.0.0.0", TELEMETRY_PORT))
        self.logger.info("Telemetry listener bound on UDP %s", TELEMETRY_PORT)
        while True:
            try:
                data, _addr = sock.recvfrom(4096)
                ev = json.loads(data.decode("utf-8", "replace"))
                self._handle_event(ev)
            except ValueError:
                self.logger.warning("Bad telemetry packet ignored")
            except Exception:
                self.logger.exception("Error handling telemetry")

    def _handle_event(self, ev):
        etype = ev.get("event")
        ip, port, user = ev.get("ip"), ev.get("port"), ev.get("user")
        if etype is None or ip is None or port is None:
            return
        key = (ip, int(port))
        s = self.sessions.setdefault(key, {"user": None, "rooms": set(),
                                           "vip": False, "throttled_until": 0})
        if user:
            s["user"] = user
        self.logger.info("EVENT %-11s user=%s room=%s flow=%s:%s", etype, user,
                         ev.get("room"), ip, port)

        if MODE != "sdn":          # baseline: observe only
            return

        if etype == "register":
            if user in VIP_USERS:
                self._set_vip(key, s, True)
        elif etype == "room_join":
            s["rooms"].add(ev.get("room"))
            if ev.get("room") in VIP_ROOMS:
                self._set_vip(key, s, True)
        elif etype == "room_leave":
            s["rooms"].discard(ev.get("room"))
            if not (s["rooms"] & VIP_ROOMS) and s["user"] not in VIP_USERS:
                self._set_vip(key, s, False)
        elif etype in ("room_msg", "private_msg"):
            self._rate_check(key, s)
        elif etype == "disconnect":
            self._clear(key)
            self.sessions.pop(key, None)

    # ------------------------------------------------------------- policies
    def _set_vip(self, key, s, enable):
        if enable and not s["vip"]:
            s["vip"] = True
            self.logger.info("POLICY A: prioritising %s (user=%s) -> queue %d",
                             key, s["user"], QUEUE_VIP)
            self._apply(key, QUEUE_VIP, PRIO_VIP, 0)
        elif not enable and s["vip"]:
            s["vip"] = False
            self.logger.info("POLICY A: removing priority for %s", key)
            self._clear(key)

    def _rate_check(self, key, s):
        user = s["user"] or "%s:%s" % key
        now = time.time()
        dq = self.msg_times[user]
        dq.append(now)
        while dq and now - dq[0] > 1.0:
            dq.popleft()
        if len(dq) > SPAM_LIMIT and now > s["throttled_until"]:
            s["throttled_until"] = now + THROTTLE_SECONDS
            self.logger.warning("POLICY B: %s sent %d msgs in 1s -> throttling %s for %ds",
                                user, len(dq), key, THROTTLE_SECONDS)
            self._apply(key, QUEUE_THROTTLE, PRIO_THROTTLE, THROTTLE_SECONDS)

    # ------------------------------------------------------ flow installation
    def _flow_specs(self, key):
        """Yield (match_kwargs, dst_ip) for client->server and server->client."""
        ip, port = key
        yield (dict(ipv4_src=ip, ipv4_dst=SERVER_IP, tcp_src=port, tcp_dst=SERVER_PORT), SERVER_IP)
        yield (dict(ipv4_src=SERVER_IP, ipv4_dst=ip, tcp_src=SERVER_PORT, tcp_dst=port), ip)

    def _apply(self, key, queue, priority, hard_timeout, attempt=0):
        missing = False
        for dp in list(self.datapaths.values()):
            parser = dp.ofproto_parser
            for mkw, dst_ip in self._flow_specs(key):
                dst_mac = self.ip_to_mac.get(dst_ip)
                out_port = self.mac_to_port[dp.id].get(dst_mac) if dst_mac else None
                if out_port is None:
                    missing = True
                    continue
                match = parser.OFPMatch(eth_type=0x0800, ip_proto=6, **mkw)
                actions = []
                if out_port == TRUNK_PORT:
                    actions.append(parser.OFPActionSetQueue(queue))
                actions.append(parser.OFPActionOutput(out_port))
                self._add_flow(dp, priority, match, actions, hard=hard_timeout)
        if missing and attempt < 5:
            # MAC / port not learned yet - retry shortly
            hub.spawn_after(0.5, self._apply, key, queue, priority, hard_timeout, attempt + 1)

    def _clear(self, key):
        for dp in list(self.datapaths.values()):
            ofp, parser = dp.ofproto, dp.ofproto_parser
            for mkw, _ in self._flow_specs(key):
                match = parser.OFPMatch(eth_type=0x0800, ip_proto=6, **mkw)
                mod = parser.OFPFlowMod(datapath=dp, command=ofp.OFPFC_DELETE,
                                        out_port=ofp.OFPP_ANY, out_group=ofp.OFPG_ANY,
                                        match=match)
                dp.send_msg(mod)
