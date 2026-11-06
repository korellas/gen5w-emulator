"""Precreate mount points rejected during API19 init on the Ranchu kernel."""
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

source = ROOT / 'deps/api19/armeabi-v7a/ramdisk.img'
records = read_newc(gzip.decompress(source.read_bytes()))
original = {name: payload for _, name, payload in records}
template = next(header for header, name, _ in records if name == b'data\0')
inode = max(int(header[6:14], 16) for header, _, _ in records)
output = records[:-1]
added = []
for path, mode, uid, gid in [('cache', 0o40770, 1000, 2001),
                             ('mnt', 0o40755, 0, 0),
                             ('mnt/asec', 0o40700, 0, 1000)]:
    name = path.encode() + b'\0'
    assert name not in original
    inode += 1
    header = bytearray(template)
    for field, value in {0: inode, 1: mode, 2: uid, 3: gid, 4: 2,
                         6: 0, 11: len(name), 12: 0}.items():
        header[6 + field * 8:14 + field * 8] = f'{value:08x}'.encode()
    output.append((bytes(header), name, b''))
    added.append(path)
output.append(records[-1])
packed = write_newc(output)
for _, name, payload in read_newc(packed):
    if name in original:
        assert payload == original[name]
target = ROOT / 'build/aosp19-ranchu.cpio.gz'
target.write_bytes(gzip.compress(packed, mtime=0))
report = {'source_sha256': hashlib.file_digest(source.open('rb'), 'sha256').hexdigest(),
          'output_sha256': hashlib.file_digest(target.open('rb'), 'sha256').hexdigest(),
          'added_directories': added, 'original_payloads_unchanged': True}
(ROOT / 'build/aosp19-ranchu-verification.json').write_text(json.dumps(report, indent=2) + '\n')
print(target)
