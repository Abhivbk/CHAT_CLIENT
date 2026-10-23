import argparse
import csv
import os
import queue
import statistics
import sys
import time
from client import ChatClient


def wait_for(c, prefix, timeout=3.0):
    end = time.time() + timeout
    while True:
        remaining = end - time.time()
        if remaining <= 0:
            return None
        try:
            line = c.lines.get(timeout=remaining)
        except queue.Empty:
            return None
        if line.startswith(prefix):
            return line


def connect(host, port, name=None):
    c = ChatClient(host, port).connect()
    wait_for(c, "Welcome")
    if name:
        c.send(f"/register {name}")
        if not wait_for(c, "Registered as"):
            raise RuntimeError(f"registration failed for {name}")
    return c


def write_csv(path, rows):
    if not path:
        return
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["test", "n_clients", "metric", "value"])
        w.writerows(rows)


def functional(args):
    failures = []

    def check(name, ok):
        status = 'PASS' if ok else 'FAIL'
        print(f"[{status}] {name}")
        if not ok:
            failures.append(name)

    a = connect(args.host, args.port)
    b = connect(args.host, args.port)
    c = connect(args.host, args.port)

    a.send("/register alice")
    check("register alice", wait_for(a, "Registered as alice") is not None)
    b.send("/register alice")
    check("duplicate username rejected", wait_for(b, "Username already taken") is not None)
    b.send("/register bad name!")
    check("invalid username rejected", wait_for(b, "Usage: /register") is not None)
    b.send("/register bob")
    check("register bob", wait_for(b, "Registered as bob") is not None)
    c.send("/register carol")
    wait_for(c, "Registered as carol")
    c.send("/msg alice before-register-check")
    wait_for(a, "[Private] carol")

    a.send("/users")
    users = wait_for(a, "Online users:") or ""
    check("/users lists everyone", all(n in users for n in ("alice", "bob", "carol")))
    a.send("/msg bob hi")
    check("private msg confirmation", wait_for(a, "[To bob] hi") is not None)
    check("private msg delivered", wait_for(b, "[Private] alice: hi") is not None)
    a.send("/msg ghost hi")
    check("offline user reported", wait_for(a, "User 'ghost' is offline") is not None)

    a.send("/join r1")
    check("join without create fails", wait_for(a, "does not exist") is not None)
    a.send("/create r1")
    check("create works", wait_for(a, "created successfully") is not None)
    a.send("/join r1")
    b.send("/join r1")
    c.send("/create r2")
    c.send("/join r2")
    wait_for(b, "You joined room 'r1'")
    wait_for(c, "You joined room 'r2'")
    a.send("/rooms")
    listing = wait_for(a, "Rooms:") or ""
    check("/rooms lists both rooms", "r1(2)" in listing and "r2(1)" in listing)
    a.send("/roommsg r1 hello")
    check("room msg reaches member", wait_for(b, "[r1] alice: hello") is not None)
    check("room msg does not leak to other room", wait_for(c, "[r1]", timeout=1.0) is None)
    c.send("/roommsg r1 intruder")
    check("non-member cannot post", wait_for(c, "Join 'r1' before messaging") is not None)
    a.send("/leave r1")
    check("/leave works", wait_for(a, "You left room 'r1'") is not None)

    a.send("/bogus")
    check("unknown command handled", wait_for(a, "Unknown command") is not None)
    a.send("/msg bob " + "x" * 2000)
    check("oversized message rejected", wait_for(a, "Message too long") is not None)
    a.send("/users")
    check("server still responsive after oversized line", wait_for(a, "Online users:") is not None)

    d = connect(args.host, args.port)
    d.send_raw(b"/register dave\n/users\n")
    check("framing: two commands in one send",
          wait_for(d, "Registered as dave") is not None and wait_for(d, "Online users:") is not None)

    e = connect(args.host, args.port)
    e.send_raw(b"/regis")
    time.sleep(0.3)
    e.send_raw(b"ter erin\n")
    check("framing: one command split across sends", wait_for(e, "Registered as erin") is not None)

    b.close()
    gone = False
    for i in range(10):
        a.send("/msg bob ping")
        if wait_for(a, "User 'bob' is offline", timeout=0.5):
            gone = True
            break
    check("abrupt disconnect cleaned up", gone)

    for cl in (a, c, d, e):
        cl.close()

    if failures:
        print(f"\n{len(failures)} FAILED: " + ', '.join(failures))
        return 1
    else:
        print("\nALL TESTS PASSED")
        return 0


def pct(values, p):
    values = sorted(values)
    idx = int(len(values) * p)
    if idx >= len(values):
        idx = len(values) - 1
    return values[idx]


def rtt(args):
    a = connect(args.host, args.port, "rttA")
    b = connect(args.host, args.port, "rttB")
    ack = []
    deliver = []
    lost = 0

    for i in range(args.messages):
        t0 = time.time()
        a.send(f"/msg rttB {t0:.6f}:{i}")
        if wait_for(a, "[To rttB]", timeout=2.0):
            ack.append((time.time() - t0) * 1000)
        got = wait_for(b, "[Private] rttA:", timeout=2.0)
        if got:
            deliver.append((time.time() - t0) * 1000)
        else:
            lost += 1
        time.sleep(args.interval)

    a.close()
    b.close()
    rows = []

    data_sets = [("ack_ms", ack), ("delivery_ms", deliver)]
    for name, vals in data_sets:
        if vals:
            avg_val = statistics.mean(vals)
            p50_val = pct(vals, 0.5)
            p95_val = pct(vals, 0.95)
            max_val = max(vals)
            print(f"{name}: avg={avg_val:.2f}  p50={p50_val:.2f}  p95={p95_val:.2f}  max={max_val:.2f}")
            rows.append(("rtt", 2, f"{name}_avg", round(avg_val, 3)))
            rows.append(("rtt", 2, f"{name}_p50", round(p50_val, 3)))
            rows.append(("rtt", 2, f"{name}_p95", round(p95_val, 3)))
            rows.append(("rtt", 2, f"{name}_max", round(max_val, 3)))

    print(f"lost={lost}/{args.messages}")
    rows.append(("rtt", 2, "lost", lost))
    write_csv(args.csv, rows)
    return 0


def scale(args):
    n = args.clients
    m = args.messages
    clients = []
    connect_ms = []

    for i in range(n):
        t0 = time.time()
        clients.append(connect(args.host, args.port, f"load{i + 1}"))
        connect_ms.append((time.time() - t0) * 1000)

    clients[0].send("/create load")
    time.sleep(0.5)

    for cl in clients:
        cl.send("/join load")
    time.sleep(1.0)

    for cl in clients:
        while not cl.lines.empty():
            cl.lines.get_nowait()

    t_start = time.time()
    for k in range(m):
        for i, cl in enumerate(clients):
            cl.send(f"/roommsg load {i + 1}-{k}")
        time.sleep(args.interval)
    time.sleep(args.settle)

    elapsed = time.time() - t_start
    expected = n * m * n
    received = 0

    for cl in clients:
        while not cl.lines.empty():
            line = cl.lines.get_nowait()
            if line.startswith("[load] "):
                received += 1

    for cl in clients:
        cl.close()

    ratio = 0
    if expected > 0:
        ratio = received / expected

    avg_conn = statistics.mean(connect_ms)
    print(
        f"clients={n} msgs/client={m} connect_avg_ms={avg_conn:.2f} delivered={received}/{expected} ({ratio:.1%}) elapsed_s={elapsed:.2f}")

    write_csv(args.csv, [
        ("scale", n, "connect_avg_ms", round(avg_conn, 3)),
        ("scale", n, "delivered", received),
        ("scale", n, "expected", expected),
        ("scale", n, "delivery_ratio", round(ratio, 4)),
        ("scale", n, "elapsed_s", round(elapsed, 3)),
    ])
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=["functional", "rtt", "scale"])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--clients", type=int, default=10)
    p.add_argument("--messages", type=int, default=50)
    p.add_argument("--interval", type=float, default=0.05)
    p.add_argument("--settle", type=float, default=2.0)
    p.add_argument("--csv")
    args = p.parse_args()

    if args.mode == "functional":
        sys.exit(functional(args))
    elif args.mode == "rtt":
        sys.exit(rtt(args))
    elif args.mode == "scale":
        sys.exit(scale(args))


if __name__ == "__main__":
    main()