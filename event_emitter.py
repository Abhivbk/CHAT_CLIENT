import json
import socket
import threading
import time

class EventEmitter:
    def __init__(self, log_path=None, controller=None):
        self.lock = threading.Lock()
        if log_path:
            self.log_file = open(log_path, "a", buffering=1, encoding="utf-8")
        else:
            self.log_file = None
        self.controller = controller
        if controller:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            self.sock = None

    def emit(self, event, **fields):
        record = {"ts": round(time.time(), 6), "event": event}
        record.update(fields)
        line = json.dumps(record)
        with self.lock:
            print(f"[EVENT] {line}", flush=True)
            if self.log_file:
                self.log_file.write(line + "\n")
        if self.sock:
            try:
                self.sock.sendto(line.encode("utf-8"), self.controller)
            except OSError:
                pass