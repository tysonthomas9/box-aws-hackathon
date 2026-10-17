"""Construct inference-only manifests after freezing training and dev data."""
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'company-knowledge'))
from evaluate import retrieve
ROOT=Path(__file__).resolve().parent
POC=ROOT.parent/'company-knowledge'


def main():
    manifest=json.loads((ROOT/'data/manifest.json').read_text())
    pack=json.loads((POC/'pack.json').read_text())
    prompts=[]
    for filename,split in [(ROOT/'data/dev.jsonl','dev'),(POC/'sealed/hidden.jsonl','hidden'),(POC/'sealed/addendum-v2.jsonl','hidden')]:
        if split=='dev':assert hashlib.sha256(filename.read_bytes()).hexdigest()==manifest['dev.jsonl']['sha256']
        for line in filename.read_text().splitlines():
            row=json.loads(line)
            question=row['messages'][1]['content'] if split=='dev' else row['question']
            docs=retrieve(question,pack)
            search=question
            if docs:search+='\n\nAvailable reference documents:\n'+'\n'.join(f"{d['source']}: {d['text']}" for d in docs)
            messages=lambda text:[{'role':'system','content':pack['system_prompt']},{'role':'user','content':text}]
            prompts.append({'id':row['id'],'split':split,'messages':messages(question),'search_messages':messages(search)})
    assert len([r for r in prompts if r['split']=='dev'])==30
    assert len([r for r in prompts if r['split']=='hidden'])==52
    result={'prompts':prompts,'data_manifest_sha256':hashlib.sha256((ROOT/'data/manifest.json').read_bytes()).hexdigest(),
            'retrieval':'POC2 query-only lexical IDF top3; no expected-answer oracle','hidden_scores':'exploratory'}
    path=ROOT/'data/evaluation.json';path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'dev':30,'hidden':52,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}))


if __name__=='__main__':main()
