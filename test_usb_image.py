import hashlib
import io
from pathlib import Path
import stat
import tempfile
import unittest
import warnings
import zipfile

import usb_image


class SnapshotTests(unittest.TestCase):
    def archive(self, directory, entries):
        archive = directory / 'input.zip'
        with warnings.catch_warnings(), zipfile.ZipFile(archive, 'w') as output:
            warnings.simplefilter('ignore', UserWarning)
            for name, data in entries:
                output.writestr(name, data)
        return archive

    def test_snapshot_preserves_inner_zip_and_does_not_follow_source_edits(self):
        nested = io.BytesIO()
        with zipfile.ZipFile(nested, 'w') as output:
            output.writestr('app.apk', b'app payload')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.archive(root, [('NEMESIS.data', b'marker'),
                                         ('packages/app.zip', nested.getvalue())])
            before = hashlib.sha256(archive.read_bytes()).digest()
            target = root / 'snapshot'
            result = usb_image.extract_snapshot(archive, target)
            self.assertTrue(target.is_dir(), 'ZIP snapshot was not created')
            self.assertEqual(hashlib.sha256(archive.read_bytes()).digest(), before)
            self.assertEqual((target / 'packages/app.zip').read_bytes(), nested.getvalue())
            self.assertGreater(result, len(nested.getvalue()))
            archive.write_bytes(b'changed later')
            self.assertEqual((target / 'NEMESIS.data').read_bytes(), b'marker')

    def test_unsafe_or_ambiguous_paths_are_rejected_before_extracting(self):
        examples = [('../outside',), ('/absolute',), ('C:/windows',),
                    ('a\\b',), ('a/./b',), ('folder/file.',), ('NUL.txt',),
                    ('A/file', 'a/other'), ('same', 'same'),
                    ('file', 'file/child'), ('name', 'NAME')]
        for names in examples:
            with self.subTest(names=names), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = self.archive(root, [(name, b'data') for name in names])
                target = root / 'snapshot'
                with self.assertRaises(ValueError):
                    usb_image.extract_snapshot(archive, target)
                self.assertFalse(target.exists())

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            info = zipfile.ZipInfo('escape')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive = self.archive(root, [(info, b'/etc/passwd')])
            with self.assertRaises(ValueError):
                usb_image.extract_snapshot(archive, root / 'snapshot')

    def test_unpacked_limit_is_checked_before_extracting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = self.archive(root, [('large', b'x' * 101)])
            target = root / 'snapshot'
            with self.assertRaises(ValueError):
                usb_image.extract_snapshot(archive, target, limit=100)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
