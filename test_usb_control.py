import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from usb_control import QMP, eject_disk


class QMPTests(unittest.TestCase):
    def test_device_stays_attached_when_guest_unmount_did_not_complete(self):
        monitor = Mock()
        still_mounted = [['/dev/block/vold/8:1', '/mnt/media_rw/usb0', 'vfat']]
        with patch('usb_control.mounts', return_value=still_mounted), \
                patch('usb_control.guest_command', return_value='500 operation failed'):
            with self.assertRaisesRegex(RuntimeError, '연결을 유지'):
                eject_disk(monitor, 5590)
        monitor.command.assert_not_called()

    def test_event_before_command_reply_is_retained_for_eject(self):
        with tempfile.TemporaryDirectory(dir='/private/tmp') as temporary:
            path = Path(temporary) / 'qmp'
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(path))
                listener.listen()

                def server():
                    channel, _ = listener.accept()
                    with channel, channel.makefile('rwb') as stream:
                        stream.write(b'{"QMP": {}}\n')
                        stream.flush()
                        for _ in range(2):
                            command = json.loads(stream.readline())
                            if command['execute'] == 'device_del':
                                stream.write(b'{"event":"DEVICE_DELETED","data":{"device":"zip-usb"}}\n')
                            stream.write(json.dumps({'return': {}, 'id': command['id']}).encode() + b'\n')
                            stream.flush()

                worker = threading.Thread(target=server)
                worker.start()
                with QMP(path) as monitor:
                    monitor.command('device_del', {'id': 'zip-usb'})
                    self.assertTrue(monitor.deleted('zip-usb', timeout=.1))
                worker.join(timeout=2)
                self.assertFalse(worker.is_alive())


if __name__ == '__main__':
    unittest.main()
