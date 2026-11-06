"""Verify and unpack official public Google SDK archives in this task folder."""
import hashlib
import json
import os
from pathlib import Path
import zipfile

root = Path(os.environ.get('GEN5W_DATA_DIR', Path(__file__).resolve().parent)).expanduser().resolve()
report = {}
for name, destination in [('tools_r25.2.5-windows.zip', 'classic-sdk'),
                          ('armeabi-v7a-19_r05.zip', 'api19'),
                          ('platform-tools.zip', '.')]:
    source = root / 'downloads' / name
    target = (root / 'deps' / destination).resolve()
    with zipfile.ZipFile(source) as archive:
        assert archive.testzip() is None, name
        for entry in archive.infolist():
            (target / entry.filename).resolve().relative_to(target)
        archive.extractall(target)
    report[name] = {'bytes': source.stat().st_size,
                    'sha256': hashlib.file_digest(source.open('rb'), 'sha256').hexdigest(),
                    'zip_crc_valid': True}
(root / 'evidence').mkdir(parents=True, exist_ok=True)
(root / 'evidence/downloads.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
