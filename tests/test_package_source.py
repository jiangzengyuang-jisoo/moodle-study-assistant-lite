"""Source release boundaries; every fixture is generated and contains no user data."""
import importlib.util
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile

spec=importlib.util.spec_from_file_location('package_source', Path(__file__).resolve().parents[1]/'tools/release/package_source.py')
package_source=importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_source)


class PackageSourceTests(unittest.TestCase):
    def link_directory(self, link, target):
        if sys.platform == 'win32':
            script="New-Item -ItemType Junction -Path '"+str(link).replace("'", "''")+"' -Target '"+str(target).replace("'", "''")+"' -ErrorAction Stop | Out-Null"
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            link.symlink_to(target, target_is_directory=True)

    def test_only_public_allowlisted_source_is_archived(self):
        with tempfile.TemporaryDirectory(prefix='study-package-') as temp:
            root=Path(temp)
            for name in ['README.md','tools/engine.py','tests/test_synthetic.py','tools/study/light.py','tools/study/Study/private.py','tools/archive/Study/private.py','tools/.PRIVATE/private.py','tools/.local/private.py','Study/private.py','config.local.json','tools/secret.dpapi']:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('synthetic',encoding='utf8')
            with zipfile.ZipFile(package_source.package(root)) as archive:
                self.assertEqual(set(archive.namelist()),{'README.md','tools/engine.py','tools/study/light.py','tests/test_synthetic.py'})

    def test_noncanonical_study_directory_is_excluded(self):
        with tempfile.TemporaryDirectory(prefix='study-package-') as temp:
            root=Path(temp)
            path=root/'tools/Study/private.py';path.parent.mkdir(parents=True);path.write_text('synthetic',encoding='utf8')
            self.assertEqual(package_source.sources(root),[])
    def test_nested_and_top_level_directory_links_are_never_followed(self):
        with tempfile.TemporaryDirectory(prefix='study-package-') as temp:
            base=Path(temp);root=base/'project';external=base/'synthetic_external'
            (root/'tools').mkdir(parents=True);external.mkdir()
            (external/'private.py').write_text('SYNTHETIC_PRIVATE_MARKER',encoding='utf8')
            (root/'tools/engine.py').write_text('public',encoding='utf8')
            nested=root/'tools/linked';top=root/'tests'
            self.link_directory(nested,external);self.link_directory(top,external)
            try:
                with zipfile.ZipFile(package_source.package(root)) as archive:
                    self.assertEqual(archive.namelist(),['tools/engine.py'])
                    self.assertNotIn(b'SYNTHETIC_PRIVATE_MARKER',archive.read('tools/engine.py'))
                self.assertEqual((external/'private.py').read_text(),'SYNTHETIC_PRIVATE_MARKER')
            finally:
                if sys.platform == 'win32': nested.rmdir();top.rmdir()
                else: nested.unlink();top.unlink()

    def test_linked_project_root_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='study-package-') as temp:
            base=Path(temp);real=base/'real';real.mkdir();link=base/'linked'
            self.link_directory(link,real)
            try:
                with self.assertRaisesRegex(ValueError,'Source root'):
                    package_source.package(link)
            finally:
                if sys.platform == 'win32': link.rmdir()
                else: link.unlink()

    def test_linked_output_directory_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='study-package-') as temp:
            base=Path(temp);root=base/'project';root.mkdir();external=base/'synthetic_external';external.mkdir();link=root/'dist'
            self.link_directory(link,external)
            try:
                with self.assertRaisesRegex(ValueError,'Output directory'):
                    package_source.package(root)
                self.assertEqual(list(external.iterdir()),[])
            finally:
                if sys.platform == 'win32': link.rmdir()
                else: link.unlink()


if __name__=='__main__': unittest.main()

