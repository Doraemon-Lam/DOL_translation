"""Create a runtime ZIP from an explicit allowlist, excluding all runtime data."""
import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from dictionary import compile_dictionary

ROOT=Path(__file__).resolve().parents[1]
def main(build_bin=None):
    pairs=[]
    for name in ('dol-localizer-experimental.dll','localizer-loader.exe','translation-dictionary.bin','manifest.json'):
        pairs.append(((build_bin or ROOT/'build/bin')/name,'bin/'+name))
    for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','剧情字幕使用说明.md','启动翻译中心.cmd'):
        pairs.append((ROOT/name,name))
    for name in ('Load.ps1','Update.ps1','SetDeepSeekKey.ps1'):pairs.append((ROOT/'scripts'/name,'scripts/'+name))
    pairs.append((ROOT/'tools/dictionary.py','tools/dictionary.py'))
    pairs.append((ROOT/'tools/auto_quest.py','tools/auto_quest.py'))
    pairs.append((ROOT/'tools/story_subtitles.py','tools/story_subtitles.py'))
    pairs.append((ROOT/'tools/translation_hub.py','tools/translation_hub.py'))
    for name in ('base.json','supplement-000-0shared-auto.json','supplement-000-0shared-story.json','supplement-001.json','supplement-002.json','supplement-003.json','supplement-004.json'):
        pairs.append((ROOT/'dictionaries'/name,'dictionaries/'+name))
    for name in ('LICENSE.txt','AUTHORS.txt'):
        pairs.append((ROOT/'third_party/minhook'/name,'third_party/minhook/'+name))
    for source,_ in pairs:
        if not source.is_file():raise FileNotFoundError(source)
    folder=ROOT/'dist';folder.mkdir(exist_ok=True)
    target=folder/'DOL_translation-windows-x86.zip'
    with tempfile.TemporaryDirectory() as temp:
        clean_overlay=Path(temp)/'live-overlay.bin'
        public_supplements=[ROOT/'dictionaries'/name for name in ('supplement-000-0shared-auto.json','supplement-000-0shared-story.json','supplement-001.json','supplement-002.json','supplement-003.json','supplement-004.json')]
        compile_dictionary(public_supplements,clean_overlay,variants=True,overlay=True)
        with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
            for source,name in pairs:archive.write(source,'DOL_translation/'+name)
            archive.write(clean_overlay,'DOL_translation/bin/live-overlay.bin')
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert len(archive.namelist())==len(pairs)+1
    digest=hashlib.sha256(target.read_bytes()).hexdigest()
    (folder/'SHA256SUMS.txt').write_text(digest+'  '+target.name+'\n',encoding='ascii')
    print(json.dumps({'zip':str(target),'files':len(pairs),'sha256':digest},indent=2))

if __name__=='__main__':main()
