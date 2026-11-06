"""Collect approved VM crash diagnostics over the loopback-only serial channel."""
import json
import argparse
from pathlib import Path
import socket
import time

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--trial', type=Path)
parser.add_argument('--commands', type=Path, default=root / 'root-console-diagnostics.sh')
parser.add_argument('--output', default='serial-sf-dump.log')
parser.add_argument('--seconds', type=int, default=100)
args = parser.parse_args()
trial = args.trial or max((root / 'runs').glob('ranchu-v039-services-*'), key=lambda p: p.stat().st_mtime_ns)
command = args.commands.read_bytes()
received = bytearray()
deadline = time.monotonic() + 60
while True:
    try:
        channel = socket.create_connection(('127.0.0.1', 5590), timeout=5)
        break
    except (ConnectionRefusedError, TimeoutError):
        if time.monotonic() >= deadline:
            raise
        time.sleep(1)
started = time.monotonic()
with channel:
    channel.settimeout(5)
    channel.sendall(b'\n')
    sent = False
    with (trial / args.output).open('wb') as log:
        while time.monotonic() - started < args.seconds:
            try:
                block = channel.recv(65536)
            except socket.timeout:
                continue
            if not block:
                break
            received.extend(block)
            log.write(block)
            log.flush()
            if not sent and b'root@wp_daudioplus_hyundai_kr:/ #' in received:
                channel.sendall(command)
                sent = True
            if b'\nVM_ROOT_DIAG_END\n' in received.replace(b'\r', b''):
                break
print(json.dumps({'trial': str(trial), 'bytes': len(received),
                  'commands_sent': sent, 'uid0_observed': b'uid=0(root)' in received,
                  'complete': b'\nVM_ROOT_DIAG_END\n' in received.replace(b'\r', b'')}))
