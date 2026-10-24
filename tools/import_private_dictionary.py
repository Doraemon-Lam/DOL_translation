"""Filter a user-supplied dictionary locally; never uploads it."""
import argparse
import json
from pathlib import Path

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    data=json.loads(args.input.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict):raise ValueError('Expected a JSON object')
    selected={}
    for source,target in data.items():
        if not isinstance(source,str) or not isinstance(target,str) or not source or not target:continue
        if any(ord(c)<32 and c not in '\r\n' for c in source+target):continue
        if len(source.encode('utf-16-le'))>8192 or len(target.encode('utf-16-le'))>8192:continue
        selected[source]=target
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as output:json.dump(selected,output,ensure_ascii=False,indent=2)
    print(json.dumps({'accepted':len(selected),'excluded':len(data)-len(selected)}))

if __name__=='__main__':main()
