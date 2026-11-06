"""Build a local native two-button app using the installed Python and SDK workspace."""
import argparse
import os
import platform
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('GEN5W_DATA_DIR', root)))
parser.add_argument('--output', type=Path, default=root / 'build/Gen5W USB.app')
args = parser.parse_args()
if sys.platform != 'darwin' or platform.machine() not in ('arm64', 'aarch64'):
    parser.error('The native USB app supports Apple Silicon macOS only')
app = args.output.expanduser().resolve()
app.parent.mkdir(parents=True, exist_ok=True)

contents = app / 'Contents'
(contents / 'MacOS').mkdir(parents=True, exist_ok=True)
(contents / 'Resources').mkdir(exist_ok=True)
subprocess.run(['xcrun', 'swiftc', '-O', '-target', 'arm64-apple-macosx13.0',
                '-module-cache-path', str(app.parent / 'swift-cache'),
                str(root / 'USBApp.swift'), '-o', str(contents / 'MacOS/Gen5WUSB')], check=True)
for name in ('usb_control.py', 'usb_image.py'):
    shutil.copyfile(root / name, contents / 'Resources' / name)
with (contents / 'Info.plist').open('wb') as stream:
    plistlib.dump({'CFBundleExecutable': 'Gen5WUSB', 'CFBundleIdentifier': 'kr.korellas.gen5w.usb',
                  'CFBundleName': 'Gen5W USB', 'CFBundlePackageType': 'APPL',
                  'CFBundleShortVersionString': '1.0', 'NSHighResolutionCapable': True,
                  'Gen5WPython': sys.executable, 'Gen5WProject': str(args.data_dir.expanduser().resolve())}, stream)
subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(app)], check=True)
print(app)
