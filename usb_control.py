"""Control one ZIP-backed virtual USB disk in the current local emulator."""
import json
import os
import argparse
import fcntl
from pathlib import Path
import re
import secrets
import socket
import time

from usb_image import create_image


class QMP:
    def __init__(self, path):
        self.channel = socket.socket(socket.AF_UNIX)
        self.channel.settimeout(10)
        self.channel.connect(str(path))
        self.stream = self.channel.makefile('rwb')
        self.events = []
        self.sequence = 0
        if 'QMP' not in json.loads(self.stream.readline()):
            self.__exit__(None, None, None)
            raise RuntimeError('QMP greeting is missing')
        self.command('qmp_capabilities')

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.stream.close()
        self.channel.close()

    def command(self, name, arguments=None):
        self.channel.settimeout(10)
        self.sequence += 1
        message = {'execute': name, 'id': self.sequence}
        if arguments is not None:
            message['arguments'] = arguments
        self.stream.write(json.dumps(message).encode() + b'\n')
        self.stream.flush()
        while True:
            line = self.stream.readline()
            if not line:
                raise RuntimeError('에뮬레이터의 QMP 연결이 종료됐습니다.')
            reply = json.loads(line)
            if 'event' in reply:
                self.events.append(reply)
            if reply.get('id') == self.sequence:
                if 'error' in reply:
                    raise RuntimeError(reply['error']['desc'])
                return reply['return']

    def deleted(self, identifier, timeout=30):
        deadline = time.monotonic() + timeout
        while True:
            if any(event.get('event') == 'DEVICE_DELETED'
                   and event.get('data', {}).get('device') == identifier for event in self.events):
                return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            self.channel.settimeout(remaining)
            try:
                line = self.stream.readline()
            except TimeoutError:
                return False
            if not line:
                return False
            self.events.append(json.loads(line))


def guest_command(port, command, timeout=35):
    marker = '__USB_' + secrets.token_hex(8)
    script = f'\necho; echo {marker}_BEGIN; {command}; usb_rc=$?; echo; echo {marker}_END $usb_rc\n'
    deadline = time.monotonic() + timeout
    data = bytearray()
    with socket.create_connection(('127.0.0.1', port), timeout=5) as channel:
        channel.settimeout(2)
        channel.sendall(script.encode())
        while time.monotonic() < deadline:
            try:
                block = channel.recv(65536)
            except TimeoutError:
                continue
            if not block:
                break
            data.extend(block)
            text = data.decode(errors='replace').replace('\r', '')
            start = text.find('\n' + marker + '_BEGIN\n')
            end = re.search(r'\n' + marker + r'_END (\d+)\n', text)
            if start >= 0 and end:
                if end.group(1) != '0':
                    raise RuntimeError('게스트 명령이 실패했습니다: ' + text[start:end.start()][-1000:])
                return text[start + len(marker) + 8:end.start()]
    raise RuntimeError('게스트 콘솔 응답을 확인하지 못했습니다. USB 연결은 유지합니다.')


def mounts(port):
    text = guest_command(port, 'cat /proc/mounts')
    lines = [line.split() for line in text.splitlines() if line.strip()]
    if not any(len(fields) >= 3 and fields[1] == '/' for fields in lines):
        raise RuntimeError('게스트 마운트 목록을 확인하지 못했습니다.')
    return [fields for fields in lines if len(fields) >= 3
            and fields[1] in ('/storage/usb0', '/mnt/media_rw/usb0')]


def eject_disk(monitor, port):
    if mounts(port):
        guest_command(port, 'vdc volume unmount /storage/usb0; sync')
    if mounts(port):
        raise RuntimeError('USB가 사용 중이거나 마운트 해제에 실패했습니다. 연결을 유지합니다.')
    monitor.command('device_del', {'id': 'zip-usb'})
    if not monitor.deleted('zip-usb'):
        raise RuntimeError('USB 제거 완료를 확인하지 못했습니다. 디스크 사본을 보존합니다.')
    monitor.command('blockdev-del', {'node-name': 'zip-usb-disk'})


def control(root, action, archive=None):
    current = root / 'runtime/current-mac.json'
    if not current.exists():
        raise RuntimeError('USB를 지원하는 에뮬레이터를 먼저 실행하세요.')
    session = json.loads(current.read_text())
    if not session.get('usb'):
        raise RuntimeError('에뮬레이터를 --usb 옵션으로 실행하세요.')
    trial = Path(session['trial'])
    if trial.parent != root / 'runtime':
        raise RuntimeError('에뮬레이터 작업 폴더가 일치하지 않습니다.')
    state_file = trial / 'usb-state.json'
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    port = session['root_console_port']
    with QMP(session['qmp']) as monitor:
        devices = monitor.command('qom-list', {'path': '/machine/peripheral'})
        identifiers = {device['name'] for device in devices}
        if 'zip-usb-controller' not in identifiers:
            raise RuntimeError('가상 USB 컨트롤러가 준비되지 않았습니다.')
        attached = 'zip-usb' in identifiers
        ready = guest_command(port, 'getprop sys.boot_completed').strip() == '1'
        if action == 'insert':
            if attached:
                raise RuntimeError('현재 USB를 먼저 꺼내세요.')
            if not ready:
                raise RuntimeError('에뮬레이터의 부팅이 완료된 뒤 USB를 삽입하세요.')
            image = trial / 'usb' / (secrets.token_hex(8) + '.img')
            create_image(archive, image)
            monitor.command('blockdev-add', {'node-name': 'zip-usb-disk', 'driver': 'raw',
                                            'file': {'driver': 'file', 'filename': str(image)}})
            try:
                monitor.command('device_add', {'driver': 'usb-storage', 'id': 'zip-usb',
                                              'drive': 'zip-usb-disk', 'bus': 'zip-usb-controller.0',
                                              'removable': True})
            except Exception:
                monitor.command('blockdev-del', {'node-name': 'zip-usb-disk'})
                raise
            state = {'source_name': Path(archive).name, 'image': str(image)}
            temporary = state_file.with_suffix('.tmp')
            temporary.write_text(json.dumps(state, ensure_ascii=False) + '\n')
            temporary.replace(state_file)
            deadline = time.monotonic() + 35
            while not any(fields[1] == '/storage/usb0' for fields in mounts(port)):
                if time.monotonic() >= deadline:
                    raise RuntimeError('USB는 연결됐지만 자동 마운트를 확인하지 못했습니다. 꺼내기로 제거할 수 있습니다.')
                time.sleep(.5)
            attached = True
        elif action == 'eject':
            if attached:
                eject_disk(monitor, port)
            attached = False
        mounted = attached and any(fields[1] == '/storage/usb0' for fields in mounts(port))
        message = 'USB가 연결되지 않았습니다.'
        if attached:
            message = (('연결됨: ' if mounted else '마운트 미완료: ')
                       + state.get('source_name', 'USB 디스크'))
        if not ready and not attached:
            message = '에뮬레이터 부팅 중…'
        return {'attached': attached, 'ready': ready, 'mounted': mounted, 'message': message}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(os.environ.get('GEN5W_DATA_DIR', Path(__file__).resolve().parent)))
    parser.add_argument('action', choices=('status', 'insert', 'eject'))
    parser.add_argument('archive', nargs='?', type=Path)
    args = parser.parse_args()
    if args.action == 'insert' and args.archive is None:
        parser.error('insert requires a ZIP archive')
    root = args.root.expanduser().resolve()
    try:
        with (root / 'runtime/usb.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = control(root, args.action, args.archive)
    except BlockingIOError:
        result = {'error': '다른 USB 작업이 진행 중입니다.'}
    except Exception as error:
        result = {'error': str(error)}
    print(json.dumps(result, ensure_ascii=False))
    return 1 if 'error' in result else 0


if __name__ == '__main__':
    raise SystemExit(main())
