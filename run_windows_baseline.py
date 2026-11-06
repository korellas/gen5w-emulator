#!/usr/bin/env python3
"""Bounded off-car classic Goldfish trial using disposable image copies."""
import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('GEN5W_DATA_DIR', ROOT)))
parser.add_argument('--tools-dir', type=Path, help='SDK 25.2.5 tools directory')
parser.add_argument('--adb', type=Path, help='platform-tools adb.exe')
parser.add_argument('--image-dir', type=Path, help='API19 armeabi-v7a image directory')
parser.add_argument('--port', type=int, default=5588)
parser.add_argument('--adb-port', type=int, default=5042)
parser.add_argument('--userdata', type=Path)
parser.add_argument('--v039', choices=('console', 'services'))
parser.add_argument('--seconds', type=int, default=600)
parser.add_argument('--network', choices=('none', 'isolated'))
parser.add_argument('--observe-seconds', type=int, default=15)
parser.add_argument('--cpu')
parser.add_argument('--ranchu', action='store_true')
parser.add_argument('--trace', action='store_true')
parser.add_argument('--ramdisk', type=Path)
parser.add_argument('--serial-port', type=int)
parser.add_argument('--buffer-count-two', action='store_true')
parser.add_argument('--display-size', type=int, nargs=2, metavar=('WIDTH', 'HEIGHT'),
                    default=(800, 480))
args = parser.parse_args()
if min(args.display_size) <= 0:
    parser.error('Display dimensions must be positive.')
ports = [args.port, args.port + 1, args.adb_port]
if args.serial_port is not None:
    ports.append(args.serial_port)
if len(set(ports)) != len(ports) or args.port % 2 or any(not 1 <= p <= 65535 for p in ports):
    parser.error('Use distinct TCP ports and an even emulator port.')
if sys.platform != 'win32':
    parser.error('This launcher requires Windows; macOS uses run_mac.py. Linux is unverified.')
ROOT = args.data_dir.expanduser().resolve()
serial = f'emulator-{args.port}'
display_width, display_height = args.display_size
if args.buffer_count_two and (not args.ranchu or args.v039 != 'services'):
    parser.error('The approved buffer-count trial requires Ranchu V039 services.')
if args.v039:
    if args.network != 'isolated':
        parser.error('V039 requires --network isolated and the task firewall rules.')
    firewall_check = '''$ErrorActionPreference='Stop';
$names=@('Gen5W-Emulator-Engine','Gen5W-Emulator-Launcher');
$rules=@(Get-NetFirewallRule -PolicyStore ActiveStore -Name $names |
Where-Object {$_.Enabled -eq 'True' -and $_.Direction -eq 'Outbound' -and $_.Action -eq 'Block'});
if($rules.Count -ne $names.Count){exit 1}
'''
    subprocess.run(['powershell', '-NoProfile', '-Command', firewall_check],
                   capture_output=True, timeout=20, check=True)
tools = (args.tools_dir or ROOT / 'deps/classic-sdk/tools').expanduser().resolve()
image = (args.image_dir or ROOT / 'deps/api19/armeabi-v7a').expanduser().resolve()
adb = (args.adb or ROOT / 'deps/platform-tools/adb.exe').expanduser().resolve()
stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
label = ('ranchu-' if args.ranchu else '') + ('v039-' + args.v039 if args.v039 else 'baseline')
trial = ROOT / 'runs' / (label + '-' + stamp)
trial.mkdir(parents=True)
for port in ports:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', port))
avd_home = trial / 'avd'
avd = avd_home / 'aosp19.avd'
avd.mkdir(parents=True)
(avd_home / 'aosp19.ini').write_text(f'path={avd}\ntarget=android-19\n')
relative_image = os.path.relpath(image, tools.parent).replace(os.sep, '/')
(avd / 'config.ini').write_text(
    'AvdId=aosp19\nabi.type=armeabi-v7a\nhw.cpu.arch=arm\nhw.ramSize=1024\n'
    f'hw.keyboard=yes\nhw.lcd.width={display_width}\nhw.lcd.height={display_height}\nhw.lcd.density=160\n'
    f'image.sysdir.1={relative_image}\n' + ('hw.sdCard=no\n' if args.ranchu else ''))
for name in ('system.img', 'userdata.img'):
    source = args.userdata if name == 'userdata.img' and args.userdata else image / name
    if name == 'system.img' and args.v039:
        source = ROOT / 'inputs/v039/system.ext4'
    shutil.copyfile(source, trial / name)
if args.buffer_count_two:
    source = ROOT / 'inputs/v039/system.ext4'
    original_hash = hashlib.file_digest(source.open('rb'), 'sha256').hexdigest()
    assert original_hash == 'a39eea41c95d0a65dc6e7217cdc376ef1c5ca09285243ea2491839a81b8d8452'
    offset = 1260903612
    with (trial / 'system.img').open('r+b') as changed:
        changed.seek(offset)
        assert changed.read(8) == bytes.fromhex('03 21 03 68 5a 6a 90 47')
        changed.seek(offset)
        changed.write(b'\x02')
    changed_hash = hashlib.sha256()
    with source.open('rb') as original, (trial / 'system.img').open('rb') as changed:
        position = 0
        differences = 0
        while block := original.read(4 << 20):
            candidate = changed.read(len(block))
            assert len(candidate) == len(block)
            changed_hash.update(candidate)
            if candidate != block:
                delta = [i for i, pair in enumerate(zip(block, candidate)) if pair[0] != pair[1]]
                assert delta == [offset - position]
                assert block[delta[0]] == 3 and candidate[delta[0]] == 2
                differences += len(delta)
            position += len(block)
        assert differences == 1 and not changed.read(1)
    (trial / 'patch-verification.json').write_text(json.dumps({
        'original_system_sha256': original_hash,
        'patched_system_sha256': changed_hash.hexdigest(),
        'changed_bytes': differences, 'image_byte_offset': offset,
        'file': '/system/lib/libsurfaceflinger.so', 'file_offset': '0x1dcbc',
        'old_instruction': 'movs r1,#3', 'new_instruction': 'movs r1,#2',
    }, indent=2) + '\n')
ramdisk = ROOT / f'inputs/v039/v039-{args.v039}.cpio.gz' if args.v039 else image / 'ramdisk.img'
if args.ranchu:
    ramdisk = (ROOT / f'inputs/v039/v039-ranchu-{args.v039}.cpio.gz' if args.v039
               else ROOT / 'inputs/public/aosp19-ranchu.cpio.gz')
if args.ramdisk:
    ramdisk = args.ramdisk.resolve(strict=True)
env = dict(os.environ)
env.update(ANDROID_SDK_HOME=str(trial / 'sdk-home'),
           ANDROID_AVD_HOME=str(avd_home), ANDROID_USER_HOME=str(trial / 'adb-home'),
           ANDROID_EMULATOR_HOME=str(trial / 'emulator-home'),
           ANDROID_SDK_ROOT=str(tools.parent), ANDROID_ADB_SERVER_PORT=str(args.adb_port))
command = [str(tools / 'emulator.exe'), '-avd', 'aosp19', '-engine', 'classic',
           '-force-32bit', '-sysdir', str(image), '-datadir', str(trial),
           '-kernel', str(image / 'kernel-qemu'), '-ramdisk', str(ramdisk),
           '-system', str(trial / 'system.img'), '-data', str(trial / 'userdata.img'),
           '-no-snapshot', '-no-audio', '-no-window', '-gpu', 'off',
           '-camera-back', 'none', '-camera-front', 'none', '-show-kernel',
           '-memory', '1024', '-skin', f'{display_width}x{display_height}', '-port', str(args.port), '-verbose']
if args.v039:
    partition_mb = ((trial / 'system.img').stat().st_size + (1 << 20) - 1) // (1 << 20)
    command.extend(['-partition-size', str(partition_mb)])
if args.ranchu:
    command[command.index('-engine') + 1] = 'qemu2'
    command.remove('-force-32bit')
    command.remove('-no-audio')
    command[command.index('-kernel') + 1] = str(ROOT / 'inputs/public/arm-ranchu-3.10-kernel')
    env['QEMU_AUDIO_DRV'] = 'none'
if args.serial_port:
    command.extend(['-shell-serial', f'tcp:127.0.0.1:{args.serial_port},server'])
command.extend(['-qemu', '-cpu', args.cpu or ('cortex-a15' if args.ranchu else 'cortex-a8')])
if args.network == 'isolated':
    if not args.ranchu:
        command.extend(['-net', 'nic', '-net', 'user'])
elif args.v039 or args.network == 'none':
    command.extend(['-net', 'none'])
if args.trace:
    command.extend(['-d', 'in_asm'])
report = {'command': command, 'duration_limit_seconds': args.seconds,
          'buffer_count_two': args.buffer_count_two, 'checks': []}
subprocess.run([str(adb), '-P', str(args.adb_port), 'start-server'], env=env,
               capture_output=True, timeout=10, check=True)
with (trial / 'emulator.stdout.log').open('wb') as out, (trial / 'emulator.stderr.log').open('wb') as err:
    process = subprocess.Popen(command, cwd=trial, env=env, stdout=out, stderr=err,
                               creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    report['pid'] = process.pid
    (trial / 'launch.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'TRIAL={trial}\nPID={process.pid}', flush=True)
    started = time.monotonic()
    try:
        while time.monotonic() - started < report['duration_limit_seconds']:
            if process.poll() is not None:
                break
            try:
                probe = 'getprop ro.build.version.incremental' if args.v039 == 'console' else 'getprop sys.boot_completed'
                p = subprocess.run([str(adb), '-P', str(args.adb_port), '-s', serial,
                                    'shell', probe],
                                   env=env, capture_output=True, timeout=10)
                value = p.stdout.decode(errors='replace').strip()
                check = {'elapsed_seconds': round(time.monotonic() - started, 1),
                         'boot_completed': value if args.v039 != 'console' else '',
                         'console_incremental': value if args.v039 == 'console' else ''}
                report['checks'].append(check)
                print(json.dumps(check), flush=True)
                ready = (value == 'eng.vmadmin.20260902.181101' if args.v039 == 'console' else value == '1')
                if ready:
                    for name, shell in [('properties', 'getprop'),
                                        ('mounts', 'cat /proc/mounts'),
                                        ('init-status', 'cat /proc/1/status'),
                                        ('processes', 'ps'), ('logcat', 'logcat -d -t 250')]:
                        result = subprocess.run([str(adb), '-P', str(args.adb_port), '-s',
                                                 serial, 'shell', shell],
                                                env=env, capture_output=True, timeout=20)
                        (trial / (name + '.txt')).write_bytes(result.stdout + result.stderr)
                    if args.v039 != 'console':
                        result = subprocess.run([str(adb), '-P', str(args.adb_port), '-s', serial,
                                                 'shell', 'dumpsys SurfaceFlinger'],
                                                env=env, capture_output=True, timeout=20)
                        (trial / 'surfaceflinger.txt').write_bytes(result.stdout + result.stderr)
                        subprocess.run([str(adb), '-P', str(args.adb_port), '-s', serial,
                                        'shell', 'screencap -p /data/local/tmp/baseline.png'],
                                       env=env, capture_output=True, timeout=20)
                        subprocess.run([str(adb), '-P', str(args.adb_port), '-s', serial,
                                        'pull', '/data/local/tmp/baseline.png', str(trial / 'baseline.png')],
                                       env=env, capture_output=True, timeout=20)
                    observation_end = time.monotonic() + args.observe_seconds
                    while process.poll() is None and time.monotonic() < observation_end:
                        time.sleep(1)
                    report['alive_after_boot_observation'] = process.poll() is None
                    break
            except subprocess.TimeoutExpired:
                print('ADB request timed out; continuing bounded startup observation', flush=True)
            time.sleep(10)
    finally:
        if args.v039:
            for name, shell in [('end-properties', 'getprop'), ('end-logcat', 'logcat -d -t 400'),
                                ('end-processes', 'ps'), ('end-mounts', 'cat /proc/mounts')]:
                try:
                    result = subprocess.run([str(adb), '-P', str(args.adb_port), '-s', serial,
                                             'shell', shell], env=env, capture_output=True, timeout=5)
                    (trial / (name + '.txt')).write_bytes(result.stdout + result.stderr)
                except subprocess.TimeoutExpired:
                    (trial / (name + '.txt')).write_text('ADB collection timed out\n')
        report['stopped_by_controller'] = process.poll() is None
        if process.poll() is None:
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            process.wait(timeout=15)
        report['exit_code'] = process.returncode
        subprocess.run([str(adb), '-P', str(args.adb_port), 'kill-server'], env=env,
                       capture_output=True, timeout=10)
(trial / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({'trial': str(trial), 'boot_completed': any(c['boot_completed'] == '1'
                  for c in report['checks']), 'exit_code': report['exit_code']}), flush=True)
