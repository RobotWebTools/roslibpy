"""Benchmark roslibpy WebSocket transports against a running rosbridge.

This is an opt-in development helper, not a pytest test. Start a rosbridge on
the chosen host/port, then run for example:

    python benchmarks/transport.py --host 127.0.0.1 --port 9090

The benchmark compares connection setup, blocking rosapi service calls, and
topic publish/subscribe round-trip latency for the ``twisted`` and ``asyncio``
transports.

The GitHub Actions benchmark runs on shared CI infrastructure, so occasional
topic latency spikes are expected. Prefer medians and throughput for quick
comparisons, and compare p95/max values across several runs before drawing
conclusions about tail latency.
"""

from __future__ import print_function

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time

from roslibpy import Message, Ros, Service, ServiceRequest, Topic


def service_ping(ros):
    """Distro-agnostic rosapi round-trip used to measure service latency.

    Calls ``/rosapi/get_time`` but, unlike ``Ros.get_time()``, does not parse
    the response (whose shape differs between ROS 1 ``secs``/``nsecs`` and ROS 2
    ``sec``/``nanosec``), so the benchmark runs unchanged against either."""
    service = Service(ros, "/rosapi/get_time", "rosapi/GetTime")
    return service.call(ServiceRequest(), timeout=5)


CASES = {
    "twisted": {
        "transport": "twisted",
        "event_loop": None,
        "compression": None,
    },
    "asyncio": {
        "transport": "asyncio",
        "event_loop": "default",
        "compression": "deflate",
    },
    "asyncio-uvloop": {
        "transport": "asyncio",
        "event_loop": "uvloop",
        "compression": "deflate",
    },
    "asyncio-no-compression": {
        "transport": "asyncio",
        "event_loop": "default",
        "compression": None,
    },
    "asyncio-uvloop-no-compression": {
        "transport": "asyncio",
        "event_loop": "uvloop",
        "compression": None,
    },
}


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
    return (
        "{:<30} {:<16} mean={mean:7.3f} ms median={median:7.3f} ms "
        "p95={p95:7.3f} ms max={max:7.3f} ms".format(transport, label, **data)
    )


def print_summary(transport, label, values):
    print(format_summary_line(transport, label, values))


def markdown_row(transport, metric, values=None, value=None):
    if values is not None:
        data = summary(values)
        return (
            "| {transport} | {metric} | {mean:.3f} ms | {median:.3f} ms | "
            "{p95:.3f} ms | {max:.3f} ms | |".format(
                transport=transport, metric=metric, **data
            )
        )
    return "| {} | {} | | | | | {} |".format(transport, metric, value)


def wait_connected(ros, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if ros.is_connected:
            return
        time.sleep(0.005)
    raise RuntimeError("Timed out waiting for connection")


def wait_rosbridge_ready(transport, args):
    deadline = time.time() + args.ready_timeout
    last_error = None
    while time.time() < deadline:
        ros = None
        try:
            ros = Ros(args.host, args.port, transport=transport)
            ros.run()
            wait_connected(ros, args.connect_timeout)
            service_ping(ros)
            return
        except Exception as error:
            last_error = error
            time.sleep(args.ready_interval)
        finally:
            if ros is not None:
                try:
                    ros.close()
                except Exception:
                    pass
    raise RuntimeError(
        "Timed out waiting for rosbridge readiness: {}".format(last_error)
    )


def service_latency(ros, count, warmup):
    for _ in range(warmup):
        service_ping(ros)
    timings = []
    for _ in range(count):
        start = time.perf_counter()
        service_ping(ros)
        timings.append(time.perf_counter() - start)
    return timings


def topic_latency(ros, case_name, count, warmup, delay):
    topic_name = "/roslibpy_transport_benchmark_{}".format(case_name.replace("-", "_"))
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
        raise RuntimeError(
            "Timed out after receiving {} of {} messages".format(len(timings), count)
        )

    total = time.perf_counter() - start_total
    listener.unsubscribe()
    publisher.unadvertise()
    return timings, len(timings) / total


def configure_case(case_name):
    case = CASES[case_name]
    if case["event_loop"] == "uvloop":
        import uvloop

        uvloop.install()

    if case["transport"] == "asyncio":
        from roslibpy.comm.comm_asyncio import AsyncioRosBridgeClientFactory

        AsyncioRosBridgeClientFactory.compression = case["compression"]

    return case


def run_case(case_name, args):
    case = configure_case(case_name)
    transport = case["transport"]

    wait_rosbridge_ready(transport, args)

    ros = Ros(args.host, args.port, transport=transport)
    start = time.perf_counter()
    ros.run()
    wait_connected(ros, args.connect_timeout)
    connect_time = time.perf_counter() - start

    services = service_latency(ros, args.service_count, args.warmup)
    topics, topic_rate = topic_latency(
        ros, case_name, args.topic_count, args.warmup, args.topic_delay
    )

    print(
        "{:<30} {:<16} {:7.3f} ms".format(
            case_name, "initial connect", connect_time * 1000.0
        )
    )
    print_summary(case_name, "get_time", services)
    print_summary(case_name, "topic rtt", topics)
    print("{:<30} {:<16} {:7.1f} msg/s".format(case_name, "topic rate", topic_rate))

    ros.close()
    time.sleep(0.5)
    return {
        "connect": [connect_time],
        "services": services,
        "topics": topics,
        "topic_rate": topic_rate,
    }


def run_case_subprocess(case_name, args):
    with tempfile.NamedTemporaryFile(delete=False) as result_file:
        result_path = result_file.name

    command = [
        sys.executable,
        os.path.abspath(__file__),
        "--case",
        case_name,
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--service-count",
        str(args.service_count),
        "--topic-count",
        str(args.topic_count),
        "--warmup",
        str(args.warmup),
        "--topic-delay",
        str(args.topic_delay),
        "--connect-timeout",
        str(args.connect_timeout),
        "--ready-timeout",
        str(args.ready_timeout),
        "--ready-interval",
        str(args.ready_interval),
        "--json-result",
        result_path,
    ]
    try:
        subprocess.check_call(command)
        with open(result_path) as fh:
            return json.load(fh)
    finally:
        try:
            os.remove(result_path)
        except OSError:
            pass


def write_markdown(path, results):
    lines = [
        "# roslibpy transport benchmark",
        "",
        "These numbers are sampled on shared CI infrastructure. Topic p95 and max",
        "latencies can be noisy because of runner scheduling, Docker networking,",
        "and rosbridge timing. Prefer medians and throughput for quick comparisons;",
        "interpret tail latency across several runs.",
        "",
        "| Transport | Metric | Mean | Median | P95 | Max | Value |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for transport, result in results:
        lines.append(markdown_row(transport, "initial connect", result["connect"]))
        lines.append(markdown_row(transport, "get_time service", result["services"]))
        lines.append(markdown_row(transport, "topic round trip", result["topics"]))
        lines.append(
            markdown_row(
                transport,
                "topic throughput",
                value="{:.1f} msg/s".format(result["topic_rate"]),
            )
        )
    lines.append("")
    with open(path, "w") as fh:
        fh.write("\n".join(lines))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--cases", nargs="+")
    parser.add_argument("--transports", nargs="+", help=argparse.SUPPRESS)
    parser.add_argument("--case", choices=sorted(CASES), help=argparse.SUPPRESS)
    parser.add_argument("--json-result", help=argparse.SUPPRESS)
    parser.add_argument("--service-count", type=int, default=1000)
    parser.add_argument("--topic-count", type=int, default=1000)
    parser.add_argument("--warmup", type=int, default=50)
    parser.add_argument("--topic-delay", type=float, default=0.00005)
    parser.add_argument("--connect-timeout", type=float, default=5.0)
    parser.add_argument("--ready-timeout", type=float, default=30.0)
    parser.add_argument("--ready-interval", type=float, default=0.5)
    parser.add_argument(
        "--markdown", help="Write a Markdown summary table to this path"
    )
    args = parser.parse_args()

    if args.case:
        result = run_case(args.case, args)
        if args.json_result:
            with open(args.json_result, "w") as fh:
                json.dump(result, fh)
        return

    cases = args.cases or args.transports or ["twisted", "asyncio"]

    results = []
    for case_name in cases:
        if case_name not in CASES:
            raise ValueError(
                "Unknown benchmark case {!r}; expected one of {}".format(
                    case_name, sorted(CASES)
                )
            )
        results.append((case_name, run_case_subprocess(case_name, args)))

    if args.markdown:
        write_markdown(args.markdown, results)


if __name__ == "__main__":
    main()
