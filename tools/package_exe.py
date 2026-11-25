"""Build a portable Windows app; end users need no Python or compiler."""
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
import package

ROOT = Path(__file__).resolve().parents[1]

def main():
    build = ROOT / 'build/exe-native'
    env = dict(os.environ, PSModulePath=str(Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/Modules'))
    if '--skip-native-build' not in sys.argv:
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ROOT / 'build.ps1'), '-Python', sys.executable, '-BuildDirectory', str(build)], check=True, env=env)
    package.main(build / 'bin')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--windowed', '--onedir', '--name', 'DOL-Translation', '--distpath', str(ROOT / 'dist/exe'), '--workpath', str(ROOT / 'build/pyinstaller'), '--specpath', str(ROOT / 'build'), str(ROOT / 'tools/translation_hub.py')], check=True)
    app = ROOT / 'dist/exe/DOL-Translation'
    with zipfile.ZipFile(ROOT / 'dist/DOL_translation-windows-x86.zip') as archive:
        for member in archive.infolist():
            path = Path(member.filename)
            relative = Path(*path.parts[1:])
            if relative.parts[0] in ('bin', 'scripts', 'dictionaries', 'third_party') or relative.suffix == '.md' or relative.name == 'LICENSE':
                target = app / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(member))
    shutil.make_archive(str(ROOT / 'dist/DOL-Translation-portable'), 'zip', app.parent, app.name)
    print('Portable EXE package: ' + str(ROOT / 'dist/DOL-Translation-portable.zip'))

if __name__ == '__main__':
    main()
