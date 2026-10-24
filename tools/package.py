"""Create a runtime ZIP from an explicit allowlist, excluding all runtime data."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def main():
    pairs=[]
    for name in ('dol-localizer-experimental.dll','localizer-loader.exe','translation-dictionary.bin','live-overlay.bin','manifest.json'):
        pairs.append((ROOT/'build/bin'/name,'bin/'+name))
    for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','加载汉化.cmd','停用汉化.cmd','更新词库.cmd'):
        pairs.append((ROOT/name,name))
    for name in ('Load.ps1','Update.ps1'):pairs.append((ROOT/'scripts'/name,'scripts/'+name))
    pairs.append((ROOT/'tools/dictionary.py','tools/dictionary.py'))
    for name in ('base.json','supplement-001.json','supplement-002.json','supplement-003.json'):
        pairs.append((ROOT/'dictionaries'/name,'dictionaries/'+name))
    for name in ('LICENSE.txt','AUTHORS.txt'):
        pairs.append((ROOT/'third_party/minhook'/name,'third_party/minhook/'+name))
    for source,_ in pairs:
        if not source.is_file():raise FileNotFoundError(source)
    folder=ROOT/'dist';folder.mkdir(exist_ok=True)
    target=folder/'DOL_translation-windows-x86.zip'
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for source,name in pairs:archive.write(source,'DOL_translation/'+name)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(pairs)
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (folder/'SHA256SUMS.txt').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    print(json.dumps({'zip':str(target),'files':len(pairs),'sha256':digest},indent=2))

if __name__=='__main__':main()
