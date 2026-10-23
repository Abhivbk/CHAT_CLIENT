import argparse
import socket
import threading
from event_emitter import EventEmitter

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 5000
MAX_LINE = 1024
MAX_NAME = 16

HELP_TEXT = (
    "Commands: /register <name> | /users | /msg <user> <text> | "
    "/create <room> | /join <room> | /leave <room> | /rooms | "
    "/roommsg <room> <text> | /help | /quit"
)

emitter = EventEmitter()

class Client:
    def __init__(self, conn, addr):
        self.conn = conn
        self.ip = addr[0]
        self.port = addr[1]
        self.username = None
        self.send_lock = threading.Lock()

    def send(self, message):
        try:
            with self.send_lock:
                self.conn.sendall((message + "\n").encode("utf-8"))
            return True
        except OSError:
            return False

clients = {}
rooms = {}
state_lock = threading.Lock()

def valid_name(text):
    return bool(text) and text.isascii() and text.isalnum() and len(text) <= MAX_NAME

def broadcast_room(room, message, exclude=None):
    with state_lock:
        recipients = []
        if room in rooms:
            for name in rooms[room]:
                if name != exclude and name in clients:
                    recipients.append(clients[name])
    for target in recipients:
        target.send(message)
    return len(recipients)

def cmd_register(client, arg):
    if client.username:
        client.send(f"Already registered as {client.username}.")
        return True
    if not valid_name(arg):
        client.send(f"Usage: /register <username>")
        return True
    with state_lock:
        taken = arg in clients
        if not taken:
            clients[arg] = client
            client.username = arg
    if taken:
        client.send("Username already taken.")
    else:
        client.send(f"Registered as {arg}!")
        emitter.emit("register", user=arg, ip=client.ip, port=client.port)
    return True

def cmd_users(client, arg):
    with state_lock:
        online = sorted(clients)
    client.send("Online users: " + ", ".join(online))
    return True

def cmd_msg(client, arg):
    parts = arg.split(maxsplit=1)
    if len(parts) != 2:
        client.send("Usage: /msg <username> <message>")
        return True
    recipient = parts[0]
    content = parts[1]
    with state_lock:
        target = clients.get(recipient)
    if target is None:
        client.send(f"User '{recipient}' is offline.")
    elif target is client:
        client.send("You cannot message yourself.")
    elif target.send(f"[Private] {client.username}: {content}"):
        client.send(f"[To {recipient}] {content}")
        emitter.emit("private_msg", user=client.username, to=recipient, ip=client.ip, port=client.port, bytes=len(content.encode("utf-8")))
    else:
        client.send("Message delivery failed.")
    return True

def cmd_create(client, arg):
    if not valid_name(arg):
        client.send(f"Usage: /create <room>")
        return True
    with state_lock:
        if arg in rooms:
            client.send(f"Room '{arg}' already exists.")
            return True
        rooms[arg] = set()
    client.send(f"Room '{arg}' created successfully.")
    return True

def cmd_join(client, arg):
    if not valid_name(arg):
        client.send(f"Usage: /join <room>")
        return True
    with state_lock:
        if arg not in rooms:
            client.send(f"Room '{arg}' does not exist. Create it first.")
            return True
        members = rooms[arg]
        already = client.username in members
        members.add(client.username)
    if already:
        client.send(f"You are already in room '{arg}'")
        return True
    client.send(f"You joined room '{arg}'")
    broadcast_room(arg, f"[ROOM] {client.username} joined {arg}", exclude=client.username)
    emitter.emit("room_join", user=client.username, room=arg, ip=client.ip, port=client.port)
    return True

def cmd_leave(client, arg):
    if not arg:
        client.send("Usage: /leave <room>")
        return True
    with state_lock:
        members = rooms.get(arg)
        left = False
        if members and client.username in members:
            left = True
        if left:
            members.discard(client.username)
            if not members:
                del rooms[arg]
    if left:
        client.send(f"You left room '{arg}'")
        broadcast_room(arg, f"[ROOM] {client.username} left {arg}")
        emitter.emit("room_leave", user=client.username, room=arg, ip=client.ip, port=client.port)
    else:
        client.send(f"You are not in room '{arg}'")
    return True

def cmd_rooms(client, arg):
    with state_lock:
        listing = []
        for name in sorted(rooms.keys()):
            listing.append(f"{name}({len(rooms[name])})")
    if listing:
        client.send("Rooms: " + ", ".join(listing))
    else:
        client.send("Rooms: No active rooms")
    return True

def cmd_roommsg(client, arg):
    parts = arg.split(maxsplit=1)
    if len(parts) != 2:
        client.send("Usage: /roommsg <room> <message>")
        return True
    room = parts[0]
    content = parts[1]
    with state_lock:
        is_member = False
        if room in rooms and client.username in rooms[room]:
            is_member = True
    if not is_member:
        client.send(f"Join '{room}' before messaging.")
        return True
    delivered = broadcast_room(room, f"[{room}] {client.username}: {content}")
    emitter.emit("room_msg", user=client.username, room=room, ip=client.ip, port=client.port, bytes=len(content.encode("utf-8")), recipients=delivered)
    return True

def cmd_help(client, arg):
    client.send(HELP_TEXT)
    return True

def cmd_quit(client, arg):
    client.send("Goodbye!")
    return False

COMMANDS = {
    "/register": cmd_register,
    "/users": cmd_users,
    "/msg": cmd_msg,
    "/create": cmd_create,
    "/join": cmd_join,
    "/leave": cmd_leave,
    "/rooms": cmd_rooms,
    "/roommsg": cmd_roommsg,
    "/help": cmd_help,
    "/quit": cmd_quit,
}
ALLOWED_BEFORE_REGISTER = {"/register", "/help", "/quit"}

def remove_client(client):
    if client.username is None:
        return
    left_rooms = []
    with state_lock:
        if client.username in clients and clients[client.username] is client:
            del clients[client.username]
        for room in list(rooms):
            if client.username in rooms[room]:
                rooms[room].discard(client.username)
                left_rooms.append(room)
                if not rooms[room]:
                    del rooms[room]
    for room in left_rooms:
        broadcast_room(room, f"[ROOM] {client.username} left {room}")

def read_line(reader):
    line = reader.readline(MAX_LINE + 2)
    if not line:
        return None, False
    if not line.endswith("\n") and len(line) >= MAX_LINE + 2:
        while True:
            rest = reader.readline(4096)
            if not rest or rest.endswith("\n"):
                break
        return line, True
    return line, len(line.rstrip("\r\n")) > MAX_LINE

def handle_client(conn, addr):
    client = Client(conn, addr)
    print(f"[CONNECTED] {addr}", flush=True)
    emitter.emit("connect", ip=client.ip, port=client.port)
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        reader = conn.makefile("r", encoding="utf-8", errors="replace", newline="\n")
        client.send("Welcome! Register using /register <username>  (type /help)")
        while True:
            line, too_long = read_line(reader)
            if line is None:
                break
            if too_long:
                client.send(f"Message too long (max {MAX_LINE} characters).")
                continue
            text = line.strip()
            if not text:
                continue
            if not text.startswith("/"):
                client.send("Commands start with '/'. Type /help.")
                continue
            parts = text.partition(" ")
            cmd = parts[0]
            arg = parts[2]
            if cmd in COMMANDS:
                handler = COMMANDS[cmd]
                if client.username is None and cmd not in ALLOWED_BEFORE_REGISTER:
                    client.send("Register first: /register <username>")
                elif not handler(client, arg.strip()):
                    break
            else:
                client.send("Unknown command. Type /help.")
    except OSError as error:
        print(f"[ERROR] {addr}: {error}", flush=True)
    finally:
        remove_client(client)
        try:
            conn.close()
        except OSError:
            pass
        emitter.emit("disconnect", user=client.username, ip=client.ip, port=client.port)
        if client.username:
            print(f"[DISCONNECTED] {client.username}", flush=True)
        else:
            print(f"[DISCONNECTED] {addr}", flush=True)

def start_server(host, port):
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((host, port))
    server.listen(128)
    print(f"[LISTENING] {host}:{port}", flush=True)
    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Server stopping")
    finally:
        server.close()

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default=DEFAULT_HOST)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--controller", metavar="HOST:PORT")
    p.add_argument("--event-log", metavar="FILE")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    controller = None
    if args.controller:
        c_parts = args.controller.rpartition(":")
        c_host = c_parts[0]
        c_port = c_parts[2]
        controller = (c_host, int(c_port))
    emitter = EventEmitter(args.event_log, controller)
    start_server(args.host, args.port)