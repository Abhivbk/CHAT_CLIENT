import argparse
import queue
import socket
import sys
import threading
import time

DEFAULT_PORT = 5000


class ChatClient:
    def __init__(self, host, port=DEFAULT_PORT, on_line=None, timeout=5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.on_line = on_line
        self.lines = queue.Queue()
        self.closed = threading.Event()
        self.sock = None
        self._thread = None

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(None)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._thread.start()
        return self

    def _recv_loop(self):
        try:
            reader = self.sock.makefile("r", encoding="utf-8", errors="replace", newline="\n")
            for line in reader:
                line = line.rstrip("\r\n")
                if self.on_line:
                    self.on_line(line)
                else:
                    self.lines.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self.closed.set()

    def send(self, text):
        self.sock.sendall((text + "\n").encode("utf-8"))

    def send_raw(self, data):
        self.sock.sendall(data)

    def close(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def run_interactive(client, user):
    if user:
        client.send(f"/register {user}")
    try:
        while not client.closed.is_set():
            try:
                line = input()
            except EOFError:
                break
            if not line.strip():
                continue
            client.send(line)
            if line.strip() == "/quit":
                time.sleep(0.3)
                break
    except (KeyboardInterrupt, OSError):
        pass


def run_script(client, user, path, delay, linger):
    if user:
        client.send(f"/register {user}")
        time.sleep(delay)
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("sleep "):
                parts = line.split()
                time.sleep(float(parts[1]))
                continue
            client.send(line)
            time.sleep(delay)
    time.sleep(linger)
    try:
        client.send("/quit")
    except OSError:
        pass
    time.sleep(0.3)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--user")
    p.add_argument("--script")
    p.add_argument("--delay", type=float, default=0.5)
    p.add_argument("--linger", type=float, default=2.0)
    args = p.parse_args()

    if args.script and args.user:
        prefix = f"[{args.user}] "
    else:
        prefix = ""

    def print_line(line):
        print(prefix + line, flush=True)

    client = ChatClient(args.host, args.port, on_line=print_line)
    try:
        client.connect()
    except OSError as error:
        print(f"Could not connect - {error}", file=sys.stderr)
        sys.exit(1)

    try:
        if args.script:
            run_script(client, args.user, args.script, args.delay, args.linger)
        else:
            run_interactive(client, args.user)
    finally:
        client.close()


if __name__ == "__main__":
    main()