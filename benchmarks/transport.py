"""Benchmark roslibpy WebSocket transports against a running rosbridge.

This is an opt-in development helper, not a pytest test. Start a rosbridge on
the chosen host/port, then run for example:

    python benchmarks/transport.py --host 127.0.0.1 --port 9090

The benchmark compares connection setup, blocking rosapi service calls, and
topic publish/subscribe round-trip latency for the ``twisted`` and ``asyncio``
transports.
"""

from __future__ import print_function

import argparse
import json
import statistics
import threading
import time

from roslibpy import Message, Ros, Topic


def percentile(values, pct):
    ordered = sorted(values)
    return ordered[int(round((len(ordered) - 1) * pct / 100.0))]


def summary(values):
    return {
        "mean": statistics.mean(values) * 1000.0,
        "median": statistics.median(values) * 1000.0,
        "p95": percentile(values, 95) * 1000.0,
        "max": max(values) * 1000.0,
    }


def format_summary_line(transport, label, values):
    data = summary(values)
    return "{:<8} {:<16} mean={mean:7.3f} ms median={median:7.3f} ms " "p95={p95:7.3f} ms max={max:7.3f} ms".format(
        transport, label, **data
    )


def print_summary(transport, label, values):
    print(format_summary_line(transport, label, values))


def markdown_row(transport, metric, values=None, value=None):
    if values is not None:
        data = summary(values)
        return "| {transport} | {metric} | {mean:.3f} ms | {median:.3f} ms | " "{p95:.3f} ms | {max:.3f} ms | |".format(
            transport=transport, metric=metric, **data
        )
    return "| {} | {} | | | | | {} |".format(transport, metric, value)


def wait_connected(ros, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ros.is_connected:
            return
        time.sleep(0.005)
    raise RuntimeError("Timed out waiting for connection")


def service_latency(ros, count, warmup):
    for _ in range(warmup):
        ros.get_time()
    timings = []
    for _ in range(count):
        start = time.perf_counter()
        ros.get_time()
        timings.append(time.perf_counter() - start)
    return timings


def topic_latency(ros, transport, count, warmup, delay):
    topic_name = "/roslibpy_transport_benchmark_{}".format(transport)
    listener = Topic(ros, topic_name, "std_msgs/String")
    publisher = Topic(ros, topic_name, "std_msgs/String")

    expected = count + warmup
    sent = {}
    timings = []
    done = threading.Event()

    def receive(message):
        payload = json.loads(message["data"])
        seq = payload["seq"]
        start = sent.get(seq)
        if start is None:
            return
        if seq >= warmup:
            timings.append(time.perf_counter() - start)
        if seq == expected - 1:
            done.set()

    listener.subscribe(receive)
    time.sleep(0.5)

    start_total = time.perf_counter()
    for seq in range(expected):
        sent[seq] = time.perf_counter()
        publisher.publish(Message({"data": json.dumps({"seq": seq})}))
        if delay:
            time.sleep(delay)

    if not done.wait(15):
        raise RuntimeError("Timed out after receiving {} of {} messages".format(len(timings), count))

    total = time.perf_counter() - start_total
    listener.unsubscribe()
    publisher.unadvertise()
    return timings, len(timings) / total


def run_transport(transport, args):
    ros = Ros(args.host, args.port, transport=transport)
    start = time.perf_counter()
    ros.run()
    wait_connected(ros, args.connect_timeout)
    connect_time = time.perf_counter() - start

    services = service_latency(ros, args.service_count, args.warmup)
    topics, topic_rate = topic_latency(ros, transport, args.topic_count, args.warmup, args.topic_delay)

    print("{:<8} {:<16} {:7.3f} ms".format(transport, "initial connect", connect_time * 1000.0))
    print_summary(transport, "get_time", services)
    print_summary(transport, "topic rtt", topics)
    print("{:<8} {:<16} {:7.1f} msg/s".format(transport, "topic rate", topic_rate))

    ros.close()
    time.sleep(0.5)
    return {
        "connect": [connect_time],
        "services": services,
        "topics": topics,
        "topic_rate": topic_rate,
    }


def write_markdown(path, results):
    lines = [
        "# roslibpy transport benchmark",
        "",
        "| Transport | Metric | Mean | Median | P95 | Max | Value |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for transport, result in results:
        lines.append(markdown_row(transport, "initial connect", result["connect"]))
        lines.append(markdown_row(transport, "get_time service", result["services"]))
        lines.append(markdown_row(transport, "topic round trip", result["topics"]))
        lines.append(markdown_row(transport, "topic throughput", value="{:.1f} msg/s".format(result["topic_rate"])))
    lines.append("")
    with open(path, "w") as fh:
        fh.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--transports", nargs="+", default=["twisted", "asyncio"])
    parser.add_argument("--service-count", type=int, default=1000)
    parser.add_argument("--topic-count", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--topic-delay", type=float, default=0.0005)
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--markdown", help="Write a Markdown summary table to this path")
    args = parser.parse_args()

    results = []
    for transport in args.transports:
        results.append((transport, run_transport(transport, args)))

    if args.markdown:
        write_markdown(args.markdown, results)


if __name__ == "__main__":
    main()
