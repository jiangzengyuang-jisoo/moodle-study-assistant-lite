"""Build a source-only ZIP without following links or Windows junctions."""
from pathlib import Path
import os
import stat
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[2]
FILES={'AGENTS.md','SKILL.md','README.md','LICENSE','THIRD_PARTY_NOTICES.md','.gitignore',
       'package.json','package-lock.json','requirements.txt','setup.cmd','setup.ps1',
       'connect.cmd','choose-courses.cmd','refresh.cmd','check-light.cmd','package-source.ps1'}
FOLDERS={'docs':{'.md'},'templates':{'.json'},'tools':{'.py','.mjs'},'tests':{'.mjs','.js','.json','.py'}}
DENIED={'__pycache__','node_modules','.venv','.private','study','.local','tmp'}


def safe_path(path, root):
    """Check every ancestor before reading, including Windows reparse points."""
    try:
        relative=path.relative_to(root)
        current=root
        for part in (None, *relative.parts):
            if part is not None:
                current=current/part
            info=current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                return False
        path.resolve(strict=True).relative_to(root.resolve(strict=True))
        return True
    except (ValueError, OSError):
        return False


def sources(root=ROOT):
    root=Path(root).absolute()
    if not safe_path(root, root):
        raise ValueError('Source root must be a real directory, not a link or junction')
    files=[]
    for name in sorted(FILES):
        path=root/name
        if safe_path(path, root) and path.is_file():
            files.append(path)
    for folder, extensions in FOLDERS.items():
        pending=[root/folder]
        while pending:
            directory=pending.pop()
            if not safe_path(directory, root) or not directory.is_dir():
                continue
            # Do not use rglob: on Windows it follows directory junctions.
            for path in sorted(directory.iterdir()):
                # tools/study is the code module; no other Study directory is public.
                denied=path.name.casefold() in DENIED and path.relative_to(root).parts != ('tools', 'study')
                if denied or not safe_path(path, root):
                    continue
                if path.is_dir():
                    pending.append(path)
                elif path.is_file() and path.suffix.casefold() in extensions:
                    files.append(path)
    return sorted(files)


def package(root=ROOT):
    root=Path(root).absolute()
    selected=sources(root)
    directory=root/'dist'
    directory.mkdir(exist_ok=True)
    if not safe_path(directory, root):
        raise ValueError('Output directory must not be a link or junction')
    out=directory/'moodle-study-light-source.zip'
    if out.exists() and not safe_path(out, root):
        raise ValueError('Output archive must not be a link or junction')
    temp=directory/f'.source-{uuid.uuid4().hex}.tmp'
    try:
        with zipfile.ZipFile(temp, 'x', zipfile.ZIP_DEFLATED) as archive:
            for path in selected:
                if not safe_path(path, root):
                    raise ValueError('A source path changed during packaging')
                archive.write(path, path.relative_to(root).as_posix())
        os.replace(temp, out)
    finally:
        temp.unlink(missing_ok=True)
    return out


if __name__=='__main__':
    print(package())

