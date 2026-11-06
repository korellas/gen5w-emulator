#!/usr/bin/env python3
"""Create off-car Goldfish ramdisks, preserving all original firmware files."""
import gzip
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

SOURCE_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('GEN5W_DATA_DIR', SOURCE_ROOT)).expanduser().resolve()
SOURCE = ROOT / 'inputs/v039'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ranchu', action='store_true')
parser.add_argument('--root-console', action='store_true')
args = parser.parse_args()
if args.root_console and not args.ranchu:
    parser.error('Root console is restricted to the off-car Ranchu trial.')
board = 'ranchu' if args.ranchu else 'goldfish'
sys.path.insert(0, str(ROOT / 'reference'))
from prepare import read_newc, write_newc

original = (SOURCE / 'boot-ramdisk.cpio').read_bytes()
records = read_newc(original)
build = ROOT / 'build'
build.mkdir(exist_ok=True)
report = {'purpose': f'PC {board} emulation only; never install on a head unit',
          'source_ramdisk_sha256': hashlib.sha256(original).hexdigest(), 'outputs': {}}
guest_rc = b'''# Off-car Goldfish guest only. No physical vehicle interfaces.
on init
    mkdir /storage/log 0770 system log
    mkdir /oem_data 0771 system system
    mkdir /storage/navi 0755 system system
    mkdir /storage/navi2 0755 system system
    mkdir /mnt/shell/emulated 0700 shell shell
    mkdir /storage/emulated 0755 root root

on fs
    wait /dev/block/mtdblock0 15
    mount ext4 /dev/block/mtdblock0 /system ro noload
    mount tmpfs tmpfs /data mode=0771,uid=1000,gid=1000
    mount tmpfs tmpfs /cache mode=0770,uid=1000,gid=2001
    mount tmpfs tmpfs /securedata mode=0771,uid=1000,gid=1000
    mount tmpfs tmpfs /oem_data mode=0771,uid=1000,gid=1000

on post-fs-data
    setprop vold.post_fs_data_done 1

on boot
    start adbd
    start console
'''
guest_ueventd = b'''/dev/graphics/fb0 0660 root graphics
/dev/binder 0666 root root
/dev/ashmem 0666 root root
'''
if args.ranchu:
    guest_rc = guest_rc.replace(b'/dev/block/mtdblock0', b'/dev/block/vda')
    guest_rc += b'''\non init
    symlink /dev/goldfish_pipe /dev/android_pipe
    symlink /dev/goldfish_pipe /dev/qemu_pipe
'''
    guest_ueventd += b'/dev/goldfish_pipe 0666 system system\n'
for mode in ('console', 'services'):
    output = []
    changed = []
    template = None
    max_inode = 0
    trailer = None
    for header, name, payload in records:
        path = name[:-1].decode().removeprefix('./')
        max_inode = max(max_inode, int(header[6:14], 16))
        if path == 'TRAILER!!!':
            trailer = (header, name, payload)
            continue
        data = payload
        if path == 'init.environ.rc':
            template = header
        if path == 'init.rc':
            text = payload.decode()
            assert text.count('import /init.usb.rc\n') == 1
            text = text.replace('import /init.usb.rc\n', '')
            if args.root_console:
                console = ('service console /system/bin/sh\n    class core\n'
                           '    console\n    disabled\n    user shell\n')
                assert text.count(console) == 1
                text = text.replace(console, console.replace('user shell', 'user root'))
            if mode == 'console':
                assert text.count('    class_start main\n') >= 1
                text = text.replace('    class_start main\n', '')
                text = text.replace('    class_start late_start\n', '')
            data = text.encode()
        elif path == 'default.prop':
            values = {'ro.secure': '0', 'ro.adb.secure': '0',
                      'ro.debuggable': '1', 'ro.board.platform': 'goldfish'}
            lines = [line for line in payload.decode().splitlines()
                     if line.partition('=')[0] not in values]
            data = ('\n'.join(lines) + '\n' + ''.join(f'{k}={v}\n' for k, v in values.items())).encode()
        if data != payload:
            changed.append(path)
        output.append((header, name, data))
    assert template and trailer
    existing = {name[:-1].decode().removeprefix('./') for _, name, _ in records}
    for index, (path, data) in enumerate(((f'init.{board}.rc', guest_rc),
                                        (f'ueventd.{board}.rc', guest_ueventd)), 1):
        assert path not in existing
        name = path.encode() + b'\0'
        header = bytearray(template)
        for field, value in {0: max_inode + index, 1: 0o100644, 2: 0, 3: 0,
                             4: 1, 6: len(data), 11: len(name), 12: 0}.items():
            header[6 + field * 8:14 + field * 8] = f'{value:08x}'.encode()
        output.append((bytes(header), name, data))
        changed.append(path)
    if args.ranchu:
        for index, (path, mode_bits, uid, gid) in enumerate([
                ('cache', 0o40770, 1000, 2001), ('mnt', 0o40755, 0, 0),
                ('mnt/asec', 0o40700, 0, 1000)], 3):
            assert path not in existing
            name = path.encode() + b'\0'
            header = bytearray(template)
            for field, value in {0: max_inode + index, 1: mode_bits, 2: uid,
                                 3: gid, 4: 2, 6: 0, 11: len(name), 12: 0}.items():
                header[6 + field * 8:14 + field * 8] = f'{value:08x}'.encode()
            output.append((bytes(header), name, b''))
            changed.append(path)
    output.append(trailer)
    packed = write_newc(output)
    check = read_newc(packed)
    old = {n: p for _, n, p in records}
    for _, name, payload in check:
        if name in old and name[:-1].decode().removeprefix('./') not in changed:
            assert payload == old[name]
    prefix = 'v039-ranchu' if args.ranchu else 'v039'
    if args.root_console:
        prefix += '-root-console'
    path = build / f'{prefix}-{mode}.cpio.gz'
    path.write_bytes(gzip.compress(packed, mtime=0))
    report['outputs'][path.name] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                  'changed_entries': changed}
    print(path)
name = ('ranchu-root-console-verification.json' if args.root_console else
        'ranchu-ramdisk-verification.json' if args.ranchu else 'ramdisk-verification.json')
(build / name).write_text(json.dumps(report, indent=2) + '\n')
