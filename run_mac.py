#!/usr/bin/env python3
"""Run the private ARM32 work image in the installed ARM64 Mac Android emulator."""
import argparse
import datetime
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def cut_guest_network(path, process, system_image):
    deadline = time.monotonic() + 30
    channel = socket.socket(socket.AF_UNIX)
    while True:
        try:
            channel.connect(str(path))
            break
        except (FileNotFoundError, ConnectionRefusedError):
            if process.poll() is not None or time.monotonic() >= deadline:
                channel.close()
                raise RuntimeError('QMP unavailable before guest startup')
            time.sleep(.1)
    channel.settimeout(5)
    with channel, channel.makefile('rwb') as stream:
        greeting = json.loads(stream.readline())
        if 'QMP' not in greeting:
            raise RuntimeError('Invalid QMP greeting')

        def command(name, arguments=None):
            message = {'execute': name, 'id': name}
            if arguments is not None:
                message['arguments'] = arguments
            stream.write(json.dumps(message).encode() + b'\n')
            stream.flush()
            while True:
                reply = json.loads(stream.readline())
                if reply.get('id') != name:
                    continue
                if 'error' in reply:
                    raise RuntimeError('QMP: ' + json.dumps(reply['error']))
                return reply['return']

        command('qmp_capabilities')
        before = command('query-status')
        if before['running']:
            raise RuntimeError('Guest ran before the network gate')
        blocks = command('query-block')
        system = next(block for block in blocks if block['device'] == 'system')
        if system['inserted']['file'] != str(system_image) or not system['inserted']['ro']:
            raise RuntimeError('Engine attached a different system image')
        command('netdev_del', {'id': 'mynet'})
        network = command('human-monitor-command', {'command-line': 'info network'})
        # info network retains the deleted peer's display text until the NIC is freed.
        usernet = command('human-monitor-command', {'command-line': 'info usernet'})
        if usernet.strip():
            raise RuntimeError('Active user networking remains: ' + usernet)
        command('cont')
        return {'before': before, 'netdev_del': 'mynet', 'network_after': network,
                'active_usernet_after': usernet, 'system_block': system,
                'after': command('query-status')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path, default=Path(os.environ.get(
        'ANDROID_SDK_ROOT') or os.environ.get('ANDROID_HOME') or Path.home() / 'Library/Android/sdk'))
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('GEN5W_DATA_DIR', ROOT)),
                        help='Private inputs, build artifacts and runtime directory')
    parser.add_argument('--cpus', type=int, default=2)
    parser.add_argument('--memory', type=int, default=1024, help='Guest RAM in MiB')
    parser.add_argument('--display-size', type=int, nargs=2, default=(1920, 720),
                        metavar=('WIDTH', 'HEIGHT'))
    parser.add_argument('--density', type=int, default=240)
    parser.add_argument('--port', type=int, default=5588, help='Even emulator console port; ADB uses port + 1')
    parser.add_argument('--adb-port', type=int, default=5041, help='Dedicated host ADB server port')
    parser.add_argument('--console-port', type=int, default=5590, help='Loopback guest root UART port')
    parser.add_argument('--public', action='store_true', help='Use public AOSP for baseline validation')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--usb', action='store_true', help='Use the PCI/USB-enabled virtual board and locally built kernel')
    parser.add_argument('--seconds', type=int, default=28800)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('Duration must be positive')
    if min(args.cpus, args.memory, args.density, *args.display_size) <= 0:
        parser.error('CPU, RAM and display values must be positive')
    ports = (args.port, args.port + 1, args.adb_port, args.console_port)
    if len(set(ports)) != len(ports):
        parser.error('Ports must be distinct')
    if args.port % 2 or any(not 1 <= port <= 65535 for port in ports):
        parser.error('Use an even emulator port and valid TCP ports')
    if sys.platform != 'darwin' or platform.machine() not in ('arm64', 'aarch64'):
        parser.error('This launcher supports Apple Silicon macOS; Windows uses start_windows.ps1. Linux is unverified.')
    data = args.data_dir.expanduser().resolve()
    width, height = args.display_size
    serial = f'emulator-{args.port}'
    sdk = args.sdk.expanduser().resolve()
    tools = sdk / 'emulator'
    binary = tools / ('qemu/darwin-aarch64/qemu-system-armel-headless' if args.headless
                      else 'qemu/darwin-aarch64/qemu-system-armel')
    adb = sdk / 'platform-tools/adb'
    for required in (binary, adb):
        if not required.is_file():
            parser.error(f'Missing SDK executable: {required}; set --sdk or ANDROID_SDK_ROOT')
    profile = ROOT / 'loopback-only.sb'
    kernel = data / 'inputs/public/arm-ranchu-3.10-kernel'
    expected_kernel = '651c69ba250f0c3161b39c10ec6a444593d1ca1aae2d5c824454681e7328b39a'
    if args.usb:
        kernel = data / 'build/usb-kernel-318'
        expected_kernel = json.loads((data / 'build/usb-kernel-verification.json').read_text())['kernel_sha256']
    if digest(kernel) != expected_kernel:
        raise ValueError('Unexpected kernel')
    image = data / 'deps/api19/armeabi-v7a'
    source = image / 'system.img' if args.public else data / 'build/v039-native-gpu.ext4'
    ramdisk = data / ('inputs/public/aosp19-ranchu.cpio.gz' if args.public else
                      'build/v039-ranchu-root-console-logger-storage-no-micom-micom-sim-services.cpio.gz')
    if args.usb and not args.public:
        ramdisk = data / 'build/v039-usb-services.cpio.gz'
        expected = json.loads((data / 'build/usb-ramdisk-verification.json').read_text())['output_sha256']
        if digest(ramdisk) != expected:
            raise ValueError('USB ramdisk differs from its verification record')
    if not args.public:
        check = json.loads((data / 'build/gpu-image-verification.json').read_text())
        if digest(source) != check['work_image_sha256']:
            raise ValueError('Work image differs from its verification record')
    for port in ports:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(('127.0.0.1', port))
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    trial = data / 'runtime' / (('mac-public-' if args.public else 'mac-v039-') + stamp)
    avd_home = trial / 'avd'
    avd = avd_home / 'gen5w.avd'
    avd.mkdir(parents=True)
    (avd_home / 'gen5w.ini').write_text(f'path={avd}\ntarget=android-19\n')
    (avd / 'config.ini').write_text(
        f'AvdId=gen5w\nabi.type=armeabi-v7a\nhw.cpu.arch=arm\nhw.cpu.ncore={args.cpus}\n'
        f'hw.ramSize={args.memory}\nhw.keyboard=yes\nhw.sdCard=no\nhw.trackBall=no\nhw.dPad=no\nhw.screen=touch\n'
        f'hw.lcd.width={width}\nhw.lcd.height={height}\nhw.lcd.density={args.density}\n'
        f'image.sysdir.1={trial}\n')
    shutil.copyfile(source, trial / 'system.img')
    shutil.copyfile(image / 'userdata.img', trial / 'userdata.img')
    shutil.copyfile(image / 'build.prop', trial / 'build.prop')
    env = dict(os.environ)
    env.update(DYLD_LIBRARY_PATH=f'{tools}/lib64:{tools}/lib64/qt/lib',
               QT_QPA_PLATFORM_PLUGIN_PATH=f'{tools}/lib64/qt/plugins',
               ANDROID_SDK_ROOT=str(sdk), ANDROID_SDK_HOME=str(trial / 'sdk-home'),
               ANDROID_AVD_HOME=str(avd_home), ANDROID_USER_HOME=str(trial / 'adb-home'),
               ANDROID_EMULATOR_HOME=str(trial / 'emulator-home'),
               ANDROID_ADB_SERVER_PORT=str(args.adb_port), QEMU_AUDIO_DRV='none')
    report = {'scope': 'Public AOSP' if args.public else 'Private OEM work copy',
              'source_sha256': digest(source), 'ramdisk_sha256': digest(ramdisk),
              'kernel_sha256': digest(kernel), 'sandbox_sha256': digest(profile),
              'boot_completed': False}
    subprocess.run([str(adb), '-P', str(args.adb_port), 'start-server'], capture_output=True, timeout=12, check=True)
    with tempfile.TemporaryDirectory(prefix='gen5w-qmp-', dir='/private/tmp') as qmp_dir:
        qmp = Path(qmp_dir) / 'qmp.sock'
        # sandbox-exec is SIP-protected and strips inherited DYLD variables.
        command = ['/usr/bin/sandbox-exec', '-f', str(profile), '/usr/bin/env',
                   f"DYLD_LIBRARY_PATH={env['DYLD_LIBRARY_PATH']}", str(binary),
                   '-avd', 'gen5w', '-engine', 'qemu2', '-sysdir', str(trial),
                   '-datadir', str(trial), '-kernel', str(kernel), '-ramdisk', str(ramdisk),
                   '-system', str(trial / 'system.img'), '-data', str(trial / 'userdata.img'),
                   '-no-snapshot', '-no-metrics', '-gpu', 'host', '-show-kernel',
                   '-memory', str(args.memory), '-skin', f'{width}x{height}', '-port', str(args.port), '-verbose']
        if not args.public:
            partition_size = (source.stat().st_size + (1 << 20) - 1) // (1 << 20)
            command.extend(['-partition-size', str(partition_size), '-shell-serial',
                            f'tcp:127.0.0.1:{args.console_port},server,nowait'])
        command.extend(['-qemu', '-cpu', 'cortex-a15', '-machine', 'virt,highmem=off' if args.usb else 'ranchu',
                        '-global', 'goldfish-events.have-touch=true',
                        '-global', 'goldfish-events.have-trackball=false',
                        '-global', 'goldfish-events.have-multitouch=false',
                        '-S', '-qmp', f'unix:{qmp},server,nowait'])
        if args.usb:
            command.extend(['-device', 'qemu-xhci,id=zip-usb-controller,addr=01.0'])
        report['command'] = command
        with (trial / 'emulator.log').open('wb') as log:
            process = subprocess.Popen(command, env=env, cwd=trial, stdout=log,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            report['pid'] = process.pid
            (trial / 'launch.json').write_text(json.dumps(report, indent=2) + '\n')
            (data / 'runtime/current-mac.json').write_text(json.dumps({
                'trial': str(trial), 'pid': process.pid, 'qmp': str(qmp),
                'usb': args.usb, 'sdk': str(sdk), 'root_console_port': args.console_port}) + '\n')
            print(f'TRIAL={trial}\nPID={process.pid}', flush=True)
            started = time.monotonic()
            try:
                report['network_gate'] = cut_guest_network(qmp, process, trial / 'system.img')
                (trial / 'network-gate.json').write_text(json.dumps(report['network_gate'], indent=2) + '\n')
                print('Guest network removed while CPU paused; resumed', flush=True)
                while process.poll() is None and time.monotonic() - started < args.seconds:
                    if not report['boot_completed']:
                        try:
                            result = subprocess.run([str(adb), '-P', str(args.adb_port), '-s', serial,
                                                     'shell', 'getprop sys.boot_completed'],
                                                    capture_output=True, timeout=5)
                            if result.stdout.strip() == b'1':
                                report['boot_completed'] = True
                                report['boot_observed_seconds'] = round(time.monotonic() - started, 2)
                                print('BOOT_COMPLETED=1', flush=True)
                        except subprocess.TimeoutExpired:
                            pass
                    time.sleep(1)
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                report['exit_code'] = process.returncode
                subprocess.run([str(adb), '-P', str(args.adb_port), 'kill-server'], capture_output=True, timeout=10)
                (trial / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'trial': str(trial), 'boot_completed': report['boot_completed']}), flush=True)


if __name__ == '__main__':
    main()
