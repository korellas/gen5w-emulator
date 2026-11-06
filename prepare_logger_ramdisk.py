#!/usr/bin/env python3
"""Build the approved VM-only FIFO diagnostic ramdisk from the root-console trial."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('GEN5W_DATA_DIR', SOURCE_ROOT)).expanduser().resolve()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--oem-storage-env', action='store_true',
                    help='Restore the original board storage exports in the VM board rc.')
parser.add_argument('--without-micom', action='store_true',
                    help='Exclude the physical MICOM daemon from the VM-only comparison.')
parser.add_argument('--micom-sim', action='store_true',
                    help='Start the private socket simulator before OEM framework services.')
args = parser.parse_args()
if args.without_micom and not args.oem_storage_env:
    parser.error('The MICOM comparison requires the restored storage environment baseline.')
if args.micom_sim and not args.without_micom:
    parser.error('The simulator requires the physical MICOM daemon to be excluded.')
sys.path.insert(0, str(ROOT / 'reference'))
from prepare import read_newc, write_newc

source = ROOT / 'build/v039-ranchu-root-console-services.cpio.gz'
source_bytes = source.read_bytes()
assert hashlib.sha256(source_bytes).hexdigest() == 'bd6f762714c556801a9d4f137077dc4d7817659d3aea59187061b853ec9ba155'
records = read_newc(gzip.decompress(source_bytes))
original = {n: (h, p) for h, n, p in records}
output = []
changed = []
max_inode = max(int(h[6:14], 16) for h, _, _ in records)
template = next(h for h, n, _ in records if n == b'init.environ.rc\0')
trailer = records[-1]
assert trailer[1] == b'TRAILER!!!\0'
for header, name, payload in records[:-1]:
    path = name[:-1].decode().removeprefix('./')
    data = payload
    if path == 'init.rc':
        text = payload.decode()
        assert text.count('    class_start core\n    class_start main\n') == 1
        # Preserve later OEM property-driven restarts, gating the initial start only.
        text = text.replace('    class_start core\n    class_start main\n',
                            '    start vm-log-reader\n')
        text += '''
# Off-car diagnostic gate: leave initial framework stopped if readers fail.
on property:vm.logger.ready=1
    class_start core
    class_start main

service vm-log-reader /system/bin/sh /sbin/vm-log-reader.sh
    disabled
    oneshot
    user root
    group root log
    seclabel u:r:init:s0
    console
'''
        data = text.encode()
        if args.micom_sim:
            data = data.replace(b'on property:vm.logger.ready=1\n',
                                b'on property:vm.logger.ready=1\n    start vm-micom\n\non property:vm.micom.ready=1\n')
            data += b'''
# Private socket fixture; never connect this ramdisk to vehicle hardware.
service vm-micom /sbin/vm-micom /data/local/tmp/vm-micom.log
    disabled
    oneshot
    user root
    group root log
    seclabel u:r:init:s0
'''
    elif path == 'init.daudio.rc' and args.without_micom:
        block = b'service micomd /system/bin/micomd /dev/ttyTCC2\n    class main\n'
        assert payload.count(block) == 1
        for _, other_name, other_payload in records:
            if other_name[:-1].decode().endswith('.rc'):
                assert not any(line.split()[:2] in ([b'start', b'micomd'], [b'restart', b'micomd'])
                               for line in other_payload.splitlines())
        data = payload.replace(block, block + b'    disabled\n')
    elif path == 'init.ranchu.rc':
        data += b'\non init\n    mkdir /dev/log 0755 root root\n'
        for channel in ('main', 'radio', 'events', 'system', 'mobis'):
            data += f'    symlink /vm-logger/{channel} /dev/log/{channel}\n'.encode()
        if args.oem_storage_env:
            board_rc = next(p for _, n, p in records if n == b'init.tcc803x.rc\0')
            for variable in ('EXTERNAL_STORAGE', 'EMULATED_STORAGE_SOURCE', 'EMULATED_STORAGE_TARGET'):
                lines = [line for line in board_rc.splitlines()
                         if line.strip().startswith(f'export {variable} '.encode())]
                assert len(lines) == 1
                data += lines[0] + b'\n'
    if data != payload:
        changed.append(path)
    output.append((header, name, data))

additions = [('vm-logger', 0o40755, b''),
             ('sbin/vm-log-reader.sh', 0o100644, (SOURCE_ROOT / 'vm-log-reader.sh').read_bytes())]
additions += [(f'vm-logger/{channel}', 0o10666, b'')
              for channel in ('main', 'radio', 'events', 'system', 'mobis')]
if args.micom_sim:
    additions.append(('sbin/vm-micom', 0o100755, (ROOT / 'build/vm-micom').read_bytes()))
for index, (path, mode, data) in enumerate(additions, 1):
    name = path.encode() + b'\0'
    assert name not in original
    header = bytearray(template)
    for field, value in {0: max_inode + index, 1: mode, 2: 0, 3: 0,
                         4: 2 if mode == 0o40755 else 1, 6: len(data),
                         11: len(name), 12: 0}.items():
        header[6 + field * 8:14 + field * 8] = f'{value:08x}'.encode()
    output.append((bytes(header), name, data))
output.append(trailer)
packed = write_newc(output)
checked = read_newc(packed)
for header, name, payload in checked:
    if name in original and name[:-1].decode().removeprefix('./') not in changed:
        assert (header, payload) == original[name]
assert set(changed) == ({'init.rc', 'init.daudio.rc', 'init.ranchu.rc'} if args.without_micom
                        else {'init.rc', 'init.ranchu.rc'})
suffix = '-storage' if args.oem_storage_env else ''
if args.without_micom:
    suffix += '-no-micom'
if args.micom_sim:
    suffix += '-micom-sim'
path = ROOT / f'build/v039-ranchu-root-console-logger{suffix}-services.cpio.gz'
path.write_bytes(gzip.compress(packed, mtime=0))
report = {
    'purpose': 'Private off-car VM boot diagnosis only; never install on a head unit',
    'source_sha256': hashlib.sha256(source_bytes).hexdigest(),
    'output_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
    'changed_existing_entries': changed,
    'added_entries': [path for path, _, _ in additions],
    'original_init_and_sepolicy_identical': all(
        next(p for _, n, p in checked if n == name) == original[name][1]
        for name in (b'init\0', b'sepolicy\0', b'file_contexts\0')),
    'capture_upper_bound_per_channel_bytes': 4096 * 2048,
    'original_board_storage_exports_restored': args.oem_storage_env,
    'physical_micom_service_disabled_for_vm': args.without_micom,
    'socket_simulator_sha256': (hashlib.sha256((ROOT / 'build/vm-micom').read_bytes()).hexdigest()
                               if args.micom_sim else None),
    'limitations': 'FIFO payload only, no logger ioctl or PID/TID/time/length headers; short reads may reduce capture size',
}
assert report['original_init_and_sepolicy_identical']
(ROOT / f'build/logger{suffix}-ramdisk-verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
