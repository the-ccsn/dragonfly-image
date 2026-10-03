#!/usr/bin/env python3
"""Verify CPU selection and real Dragonfly operations under emulated CPUs."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time


def probe(cpu, helper):
    return subprocess.check_output(
        ["qemu-x86_64", "-cpu", cpu, helper],
        text=True,
    ).strip()


def command(*parts):
    with socket.create_connection(("127.0.0.1", 16379), timeout=5) as connection:
        payload = f"*{len(parts)}\r\n".encode()
        for part in parts:
            value = str(part).encode()
            payload += f"${len(value)}\r\n".encode() + value + b"\r\n"
        connection.sendall(payload)
        stream = connection.makefile("rb")

        def read():
            line = stream.readline()
            if not line:
                raise RuntimeError("Dragonfly closed the connection")
            kind, value = line[:1], line[1:-2]
            if kind == b"-":
                raise RuntimeError(value.decode())
            if kind == b"+":
                return value.decode()
            if kind == b":":
                return int(value)
            if kind == b"$":
                size = int(value)
                if size == -1:
                    return None
                result = stream.read(size)
                assert stream.read(2) == b"\r\n"
                return result.decode()
            if kind == b"*":
                return [read() for _ in range(int(value))]
            raise RuntimeError(f"Unexpected RESP response: {line!r}")

        return read()


def run_server(cpu, mode, directory, restore=False):
    binary = f"/usr/local/lib/dragonfly/dragonfly-{mode}"
    prefix = ["qemu-x86_64", "-cpu", cpu] if cpu else []
    with tempfile.TemporaryFile(mode="w+") as log:
        process = subprocess.Popen(
            [*prefix, binary, "--logtostderr",
             "--bind=127.0.0.1", "--port=16379", "--proactor_threads=1",
             "--maxmemory=256mb", "--cache_mode=true", f"--dir={directory}", "--dbfilename=smoke",
             "--snapshot_cron="],
            stdout=log, stderr=log,
        )
        try:
            deadline = time.monotonic() + 60
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"Dragonfly exited with {process.returncode}")
                try:
                    if command("PING") == "PONG":
                        break
                except (OSError, RuntimeError):
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("Dragonfly readiness timed out")
                time.sleep(0.2)

            if restore:
                assert command("GET", "persist") == "cross-build"
                assert command("HGET", "hash", "field") == "value"
                assert command("LRANGE", "queue", 0, -1) == ["job1", "job2"]
                assert json.loads(command("JSON.GET", "json", ".")) == {"answer": 42}
            else:
                assert command("SET", "persist", "cross-build") == "OK"
                assert command("HSET", "hash", "field", "value") == 1
                assert command("RPUSH", "queue", "job1", "job2") == 2
                assert command("SADD", "set", "one", "two") == 2
                assert command("ZADD", "scores", 1, "one") == 1
                assert command("JSON.SET", "json", ".", '{"answer":42}') == "OK"
                assert command("EVAL", "return 42", 0) == 42
                assert command("EVAL", "return redis.call('GET', KEYS[1])", 1, "persist") == "cross-build"
                # Repeated writes exercise more paths than an idle PING probe.
                for index in range(300):
                    assert command("SET", f"cache:{index}", "x" * 1024, "EX", 60) == "OK"
                assert command("GET", "cache:299") == "x" * 1024
                assert command("SAVE") == "OK"
                assert list(Path(directory).glob("smoke*")), "Missing snapshot"
            assert command("PING") == "PONG"
            print(f"Operations passed: CPU={cpu or 'native'}, build={mode}, restore={restore}", flush=True)
        except Exception:
            # Let a failing child finish writing its signal/exit diagnostics.
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
            print(f"Server failure: CPU={cpu}, build={mode}, exit={process.poll()}", flush=True)
            log.seek(0)
            print(log.read(), flush=True)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selector-only", action="store_true")
    parser.add_argument("--cpu-helper", default="/usr/local/bin/dragonfly-cpu-mode")
    arguments = parser.parse_args()
    for cpu, expected in [
        ("Nehalem", "generic"),
        ("SandyBridge", "generic"),
        ("Haswell", "avx2"),
        ("Haswell,-avx", "generic"),
        ("Haswell,-avx2", "generic"),
        ("Haswell,-fma", "generic"),
        ("Haswell,-bmi2", "generic"),
        ("Haswell,-xsave", "generic"),
    ]:
        assert probe(cpu, arguments.cpu_helper) == expected, f"Incorrect selection for {cpu}"
        print(f"CPU selection: {cpu} -> {expected}", flush=True)

    if arguments.selector_only:
        return

    # Verify the actual launcher preserves arguments and rejects invalid overrides.
    for mode in ["auto", "generic", "avx2"]:
        environment = {**os.environ, "DRAGONFLY_CPU_MODE": mode}
        detected = subprocess.check_output(["dragonfly-cpu-mode"], text=True).strip()
        result = subprocess.run(["dragonfly", "--version"], env=environment,
                                capture_output=True, text=True)
        if mode == "avx2" and detected != "avx2":
            assert result.returncode != 0
        else:
            assert result.returncode == 0, result.stderr
            selected = detected if mode == "auto" else mode
            assert f"selected {selected} build" in result.stderr
    result = subprocess.run(["dragonfly", "--version"],
                            env={**os.environ, "DRAGONFLY_CPU_MODE": "invalid"},
                            capture_output=True, text=True)
    assert result.returncode != 0

    # Separate native build failures from user-mode emulator failures.
    for mode in ["generic", "avx2"]:
        if mode == "avx2" and detected != "avx2":
            continue
        with tempfile.TemporaryDirectory() as directory:
            run_server(None, mode, directory)

    # A snapshot written on one CPU must remain usable after rescheduling to another.
    with tempfile.TemporaryDirectory() as directory:
        run_server("Nehalem", "generic", directory)
        run_server("Haswell", "avx2", directory, restore=True)
    with tempfile.TemporaryDirectory() as directory:
        run_server("Haswell", "avx2", directory)
        run_server("Nehalem", "generic", directory, restore=True)
    print("PASS: no-AVX operations, AVX2 operations, and cross-build snapshot restore")


if __name__ == "__main__":
    main()
