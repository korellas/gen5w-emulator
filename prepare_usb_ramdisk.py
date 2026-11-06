"""Add the VM PCI USB volume and current private MICOM fixture to a derived ramdisk."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('GEN5W_DATA_DIR', SOURCE_ROOT)).expanduser().resolve()
sys.path.insert(0, str(ROOT / 'reference'))
from prepare import read_newc, write_newc

source = ROOT / 'build/v039-ranchu-root-console-logger-storage-no-micom-micom-sim-services.cpio.gz'
records = read_newc(gzip.decompress(source.read_bytes()))
original = {name: payload for _, name, payload in records}
assert b'fstab.ranchu\0' not in original
fixture = (ROOT / 'build/vm-micom').read_bytes()
board_lines = original[b'init.tcc803x.rc\0'].splitlines()
service_index = next(i for i, line in enumerate(board_lines) if line.startswith(b'service fuse_usb0 '))
fuse_service = board_lines[service_index:service_index + 3]
assert [line.strip() for line in fuse_service[1:]] == [b'class late_start', b'disabled']
output = []
for header, name, payload in records[:-1]:
    if name == b'sbin/vm-micom\0':
        payload = fixture
    elif name == b'init.ranchu.rc\0':
        payload += b'''\non fs
    mkdir /storage/usb0 0700 root root
    mkdir /mnt/media_rw/usb0 0770 media_rw media_rw
'''
        payload += b'\n' + b'\n'.join(fuse_service) + b'\n'
    output.append((header, name, payload))
fstab = b'/devices/3f000000.pcie/pci0000:00/0000:00:01.0 /storage/usb0 vfat defaults voldmanaged=usb0:auto\n'
name = b'fstab.ranchu\0'
header = bytearray(next(h for h, n, _ in records if n == b'init.environ.rc\0'))
for field, value in {0: max(int(h[6:14], 16) for h, _, _ in records) + 1,
                     1: 0o100644, 2: 0, 3: 0, 4: 1, 6: len(fstab), 11: len(name), 12: 0}.items():
    header[6 + field * 8:14 + field * 8] = f'{value:08x}'.encode()
output.append((bytes(header), name, fstab))
output.append(records[-1])
packed = write_newc(output)
checked = {n: p for _, n, p in read_newc(packed)}
changed = (b'sbin/vm-micom\0', b'init.ranchu.rc\0')
assert all(checked[n] == p for n, p in original.items() if n not in changed)
destination = ROOT / 'build/v039-usb-services.cpio.gz'
destination.write_bytes(gzip.compress(packed, mtime=0))
report = {'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'output_sha256': hashlib.sha256(destination.read_bytes()).hexdigest(),
          'fixture_sha256': hashlib.sha256(fixture).hexdigest(),
          'added': ['fstab.ranchu'],
          'changed': [n[:-1].decode() for n in changed],
          'original_init_and_policy_preserved': True}
(ROOT / 'build/usb-ramdisk-verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
