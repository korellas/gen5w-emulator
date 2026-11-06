"""Check launch configuration without starting a VM or using OEM inputs."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import run_mac


class MacLaunchTests(unittest.TestCase):
    def test_external_data_and_sdk_use_configured_display_and_ports(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = root / 'private data'
            sdk = root / 'sdk'
            build = data / 'build'
            image = data / 'deps/api19/armeabi-v7a'
            build.mkdir(parents=True)
            image.mkdir(parents=True)
            binary = sdk / 'emulator/qemu/darwin-aarch64/qemu-system-armel'
            binary.parent.mkdir(parents=True)
            binary.touch()
            adb = sdk / 'platform-tools/adb'
            adb.parent.mkdir(parents=True)
            adb.touch()
            for name, contents in [('usb-kernel-318', b'kernel'),
                                   ('v039-usb-services.cpio.gz', b'ramdisk'),
                                   ('v039-native-gpu.ext4', b'system')]:
                (build / name).write_bytes(contents)
            for name, key, contents in [('usb-kernel-verification.json', 'kernel_sha256', b'kernel'),
                                        ('usb-ramdisk-verification.json', 'output_sha256', b'ramdisk'),
                                        ('gpu-image-verification.json', 'work_image_sha256', b'system')]:
                (build / name).write_text(json.dumps({key: hashlib.sha256(contents).hexdigest()}))
            (image / 'userdata.img').write_bytes(b'data')
            (image / 'build.prop').write_text('ro.build.version.sdk=19\n')
            process = Mock(pid=123, returncode=0)
            process.poll.return_value = 0
            argv = ['run_mac.py', '--sdk', str(sdk), '--data-dir', str(data), '--usb',
                    '--cpus', '3', '--memory', '1536', '--display-size', '1280', '480',
                    '--density', '160', '--port', '5600', '--adb-port', '5051',
                    '--console-port', '5602', '--seconds', '1']
            with patch('sys.argv', argv), patch('sys.platform', 'darwin'), \
                    patch('platform.machine', return_value='arm64'), \
                    patch('run_mac.socket.socket'), patch('run_mac.subprocess.run'), \
                    patch('run_mac.subprocess.Popen', return_value=process) as launch, \
                    patch('run_mac.cut_guest_network', return_value={'isolated': True}) as gate, \
                    contextlib.redirect_stdout(io.StringIO()):
                run_mac.main()
            command = launch.call_args.args[0]
            self.assertEqual(command[command.index('-memory') + 1], '1536')
            self.assertEqual(command[command.index('-skin') + 1], '1280x480')
            self.assertEqual(command[command.index('-port') + 1], '5600')
            self.assertIn('tcp:127.0.0.1:5602,server,nowait', command)
            session = json.loads((data / 'runtime/current-mac.json').read_text())
            self.assertEqual(session['root_console_port'], 5602)
            trial = Path(session['trial'])
            config = (trial / 'avd/gen5w.avd/config.ini').read_text()
            self.assertIn('hw.cpu.ncore=3\n', config)
            self.assertIn('hw.lcd.width=1280\n', config)
            self.assertIn('hw.lcd.density=160\n', config)
            self.assertEqual(launch.call_args.kwargs['env']['ANDROID_ADB_SERVER_PORT'], '5051')
            self.assertEqual((trial / 'system.img').read_bytes(), b'system')
            self.assertTrue(gate.called)

    def test_colliding_ports_fail_before_launch(self):
        with patch('sys.argv', ['run_mac.py', '--adb-port', '5589']), \
                contextlib.redirect_stderr(io.StringIO()) as errors, \
                patch('run_mac.subprocess.Popen') as launch:
            with self.assertRaises(SystemExit) as error:
                run_mac.main()
            self.assertEqual(error.exception.code, 2)
            self.assertIn('Ports must be distinct', errors.getvalue())
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
