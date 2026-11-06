#!/usr/bin/env python3
"""Create a private v39 work image with the existing API19 emulator graphics modules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

SOURCE_ROOT = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('GEN5W_DATA_DIR', SOURCE_ROOT)).expanduser().resolve()
ORIGINAL_SHA = 'a39eea41c95d0a65dc6e7217cdc376ef1c5ca09285243ea2491839a81b8d8452'
MODULES = (
    'egl/libEGL_emulation.so', 'egl/libGLESv1_CM_emulation.so', 'egl/libGLESv2_emulation.so',
    'libOpenglSystemCommon.so', 'lib_renderControl_enc.so', 'libGLESv1_enc.so',
    'libGLESv2_enc.so', 'hw/gralloc.goldfish.so',
)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--debugfs', default='debugfs')
    args = parser.parse_args()
    original = ROOT / 'inputs/v039/system.ext4'
    public = ROOT / 'deps/api19/armeabi-v7a/system.img'
    if digest(original) != ORIGINAL_SHA:
        raise ValueError('Unsupported v39 input; original is unchanged')
    build = ROOT / 'build'
    build.mkdir(exist_ok=True)
    target = build / 'v039-native-gpu.ext4'
    if target.exists():
        raise FileExistsError('Preserve existing work image; choose a clean build directory')
    modules = build / 'gpu-modules'
    modules.mkdir(exist_ok=True)
    shutil.copyfile(original, target)
    # Preserve the already-tested VM-only SurfaceFlinger adjustment.
    with target.open('r+b') as image:
        image.seek(1260903612)
        if image.read(8) != bytes.fromhex('03 21 03 68 5a 6a 90 47'):
            raise ValueError('Unexpected SurfaceFlinger bytes')
        image.seek(1260903612)
        image.write(b'\x02')
    commands = []
    hashes = {}
    label = modules / 'system-file-label'
    label.write_bytes(b'u:object_r:system_file:s0\0')
    for relative in MODULES:
        destination = '/lib/' + relative
        local = modules / relative
        local.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run([args.debugfs, '-R', f'dump {destination} "{local}"', str(public)],
                                capture_output=True, check=True)
        if not local.is_file() or local.read_bytes()[:4] != b'\x7fELF':
            raise ValueError('Missing public ELF: ' + relative)
        stat = subprocess.run([args.debugfs, '-R', 'stat ' + destination, str(original)],
                              capture_output=True, check=True)
        if b'File not found' not in stat.stderr:
            raise ValueError('Refusing to overwrite an OEM file: ' + destination)
        commands.extend([f'write "{local}" {destination}',
                         f'set_inode_field {destination} mode 0100644',
                         f'ea_set -f "{label}" {destination} security.selinux'])
        hashes[destination] = digest(local)
    # API19 Loader scans vendor EGL first. Preserve Mali bytes under a name it skips.
    mali = '/vendor/lib/egl/libGLES_mali.so'
    disabled_mali = '/vendor/lib/egl/mali-original.disabled'
    original_mali = subprocess.run([args.debugfs, '-R', 'cat ' + mali, str(original)],
                                   capture_output=True, check=True).stdout
    if original_mali[:4] != b'\x7fELF':
        raise ValueError('Expected original Mali ELF')
    commands.extend([f'link {mali} {disabled_mali}', f'unlink {mali}'])
    script = modules / 'debugfs-commands.txt'
    script.write_text('\n'.join(commands) + '\n')
    result = subprocess.run([args.debugfs, '-w', '-f', str(script), str(target)],
                            capture_output=True, check=True)
    (modules / 'debugfs-result.txt').write_bytes(result.stdout + result.stderr)
    # Verify every added payload and SELinux label using the resulting ext4 image.
    for destination, expected in hashes.items():
        check = modules / 'verified-module'
        subprocess.run([args.debugfs, '-R', f'dump {destination} "{check}"', str(target)],
                       capture_output=True, check=True)
        if digest(check) != expected:
            raise ValueError('Work image payload verification failed: ' + destination)
        ea = subprocess.run([args.debugfs, '-R', 'ea_list ' + destination, str(target)],
                            capture_output=True, check=True)
        if b'security.selinux' not in ea.stdout or b'system_file' not in ea.stdout:
            raise ValueError('Work image label verification failed: ' + destination)
    if digest(original) != ORIGINAL_SHA:
        raise ValueError('Original hash changed')
    retained = subprocess.run([args.debugfs, '-R', 'cat ' + disabled_mali, str(target)],
                              capture_output=True, check=True).stdout
    if retained != original_mali:
        raise ValueError('Preserved Mali bytes differ')
    report = {'scope': 'PC-only work image; never install on a head unit',
              'original_sha256': ORIGINAL_SHA, 'public_system_sha256': digest(public),
              'work_image_sha256': digest(target), 'added_modules': hashes,
              'oem_files_overwritten': [], 'existing_sf_patch_preserved': True,
              'renamed_mali': {'from': mali, 'to': disabled_mali,
                               'sha256': hashlib.sha256(retained).hexdigest()}}
    (build / 'gpu-image-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
