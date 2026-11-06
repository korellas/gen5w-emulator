"""Create a private, fixed FAT USB snapshot from a ZIP archive."""
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import tempfile
import unicodedata
import zipfile


def extract_snapshot(archive, target, *, limit=8 * 1024**3):
    target = Path(target)
    paths = {}
    explicit = set()
    total = 0
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if not entries or len(entries) > 20000:
            raise ValueError('ZIP은 비어 있지 않아야 하며 항목 수는 20,000개 이하여야 합니다.')
        for item in entries:
            name = item.orig_filename
            parts = name.removesuffix('/').split('/')
            mode = stat.S_IFMT(item.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError('ZIP의 링크와 특수 파일은 지원하지 않습니다.')
            for component in parts:
                stem = component.partition('.')[0].upper()
                reserved = stem in ('CON', 'PRN', 'AUX', 'NUL') or (
                    len(stem) == 4 and stem[:3] in ('COM', 'LPT') and stem[3] in '123456789')
                if (not component or component in ('.', '..') or reserved
                        or component.endswith((' ', '.'))
                        or len(component.encode('utf-16le')) > 510
                        or any(ord(c) < 32 or c in '\\:*?"<>|' for c in component)):
                    raise ValueError('FAT USB에 안전하게 복사할 수 없는 ZIP 경로입니다: ' + name)
            for index in range(1, len(parts) + 1):
                path = '/'.join(parts[:index])
                key = unicodedata.normalize('NFC', path).casefold()
                directory = index < len(parts) or item.is_dir()
                if key in paths and paths[key] != (path, directory):
                    raise ValueError('USB에서 충돌하는 ZIP 경로입니다: ' + name)
                if index == len(parts):
                    if key in explicit:
                        raise ValueError('중복 ZIP 경로입니다: ' + name)
                    explicit.add(key)
                paths[key] = (path, directory)
            if item.file_size > 0xffffffff:
                raise ValueError('FAT32의 단일 파일 크기 제한을 넘었습니다: ' + name)
            total += item.file_size
            if total > limit:
                raise ValueError('ZIP의 압축 해제 크기 제한을 넘었습니다.')
        target.mkdir(mode=0o700)
        for item in entries:
            destination = target.joinpath(*item.filename.removesuffix('/').split('/'))
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as stream, destination.open('xb') as output:
                    shutil.copyfileobj(stream, output, 1024 * 1024)
    return total


def create_image(archive, destination):
    """Use macOS disk-image tools; never format or attach a physical disk."""
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix='usb-stage-', dir=destination.parent) as temporary:
        stage = Path(temporary)
        source = stage / 'contents'
        total = extract_snapshot(archive, source)
        count = sum(1 for _ in source.rglob('*'))
        size_mib = max(128, (total + count * 8192 + 64 * 1024**2) * 105 // (100 * 1024**2) + 1)
        output = stage / 'snapshot.cdr'
        result = subprocess.run(['/usr/bin/hdiutil', 'create', '-srcfolder', str(source),
                                 '-fs', 'MS-DOS FAT32', '-layout', 'MBRSPUD',
                                 '-format', 'UDTO', '-size', f'{size_mib}m',
                                 '-volname', 'GEN5WUSB', '-nospotlight', '-quiet', str(output)],
                                capture_output=True, timeout=600)
        if result.returncode:
            raise RuntimeError('USB 이미지 생성 실패: ' + result.stderr.decode(errors='replace').strip())
        with output.open('rb') as stream:
            mbr = stream.read(512)
            partition = mbr[446:462]
            if mbr[510:] != b'\x55\xaa' or partition[4] not in (0x0b, 0x0c):
                raise RuntimeError('생성물이 MBR/FAT32 USB 디스크가 아닙니다.')
            stream.seek(struct.unpack_from('<I', partition, 8)[0] * 512)
            if stream.read(512)[82:90] != b'FAT32   ':
                raise RuntimeError('USB 파티션의 FAT32 형식을 확인하지 못했습니다.')
        output.chmod(0o600)
        output.rename(destination)
    return {'image': str(destination), 'unpacked_bytes': total}
