"""Isolated overlap auditor. Hidden content never goes to the data builder."""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'company-knowledge'))
from audit import norm
ROOT=Path(__file__).resolve().parent
POC=ROOT.parent/'company-knowledge'


def rows(path):return [json.loads(x) for x in path.read_text().splitlines()]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def similarity(q,t):
    a,b=set(q.split()),set(t.split())
    return max(SequenceMatcher(None,q,t).ratio(),len(a&b)/len(a|b))
def write(path,data):path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in data))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--dev-only',action='store_true');args=parser.parse_args()
    freeze=json.loads((POC/'sealed/freeze.json').read_text())
    add=json.loads((POC/'sealed/addendum-v2-manifest.json').read_text())
    assert sha(POC/'pack.json')==freeze['pack_sha256']
    assert sha(POC/'sealed/hidden.jsonl')==freeze['hidden_sha256']
    assert sha(POC/'sealed/addendum-v2.jsonl')==add['addendum_sha256']
    hidden=rows(POC/'sealed/hidden.jsonl')+rows(POC/'sealed/addendum-v2.jsonl')
    targets=[(r['id'],norm(r['question'])) for r in hidden]
    base=rows(POC/'generated/kimi-k3/train-final.jsonl')
    assert len(base)==386
    pack=json.loads((POC/'pack.json').read_text())
    report={'threshold':.78,'hidden_sha256':freeze['hidden_sha256'],'addendum_sha256':add['addendum_sha256'],
            'base_training_sha256':sha(POC/'generated/kimi-k3/train-final.jsonl'),'exclusions':[]}
    seen=set()
    def accept(row,split,extra=()):
        assert [m['role'] for m in row['messages']]==['system','user','assistant']
        assert row['messages'][0]['content']==pack['system_prompt']
        assert all(m['content'].strip() for m in row['messages'])
        q=norm(row['messages'][1]['content'])
        if 'z83' in norm(' '.join(m['content'] for m in row['messages'])):reason='held-out procedure'
        elif q in seen:reason='duplicate'
        else:
            matches=[i for i,t in targets+list(extra) if similarity(q,t)>=.78]
            reason='overlap:'+','.join(matches) if matches else None
        if reason:
            report['exclusions'].append({'id':row['id'],'split':split,'reason':reason});return False
        seen.add(q);return True
    assert all(accept(r,'original') for r in base),'Original386 no longer pass strict audit'
    base_targets=[(r['id'],norm(r['messages'][1]['content'])) for r in base]
    dev=[];counts=Counter();target={'fact':8,'two_fact':3,'procedure':4,'near_miss':3,'unknown':8,'general':4}
    frozen_dev=ROOT/'data/dev.jsonl'
    candidates=rows(frozen_dev if frozen_dev.exists() else ROOT/'data/dev/reviewed.jsonl')
    for row in candidates:
        if counts[row['kind']]>=target[row['kind']]:continue
        if accept(row,'dev',base_targets):dev.append(row);counts[row['kind']]+=1
    if counts!=target:raise ValueError('Too few separate dev examples: '+str(counts))
    if frozen_dev.exists():assert dev==rows(frozen_dev),'Frozen dev changed or no longer passes'
    else:write(frozen_dev,dev)
    dev_report={'dev_sha256':sha(frozen_dev),'rows':len(dev),'by_kind':dict(counts),
                'base_training_sha256':report['base_training_sha256'],
                'hidden_sha256':report['hidden_sha256'],'addendum_sha256':report['addendum_sha256'],
                'threshold':.78,'exclusions':report['exclusions'],
                'generation':'Kimi K3','review':'GLM-5','separation':'Frozen against original386 and hidden; later training additions must avoid this dev set'}
    dev_manifest=ROOT/'data/dev-manifest.json'
    if not dev_manifest.exists():dev_manifest.write_text(json.dumps(dev_report,indent=2)+'\n')
    else:assert json.loads(dev_manifest.read_text())['dev_sha256']==sha(frozen_dev)
    if args.dev_only:print(json.dumps(dev_report,indent=2));return
    dev_targets=[(r['id'],norm(r['messages'][1]['content'])) for r in dev]
    additions=[];counts=Counter()
    for row in rows(ROOT/'data/train/reviewed.jsonl'):
        goal={'unknown':130,'near_miss':40}[row['kind']]
        if counts[row['kind']]>=goal:continue
        assert len(row['item_ids'])<=1
        if accept(row,'train',dev_targets):additions.append(row);counts[row['kind']]+=1
    if counts!={'unknown':130,'near_miss':40}:raise ValueError('Too few reviewed clean additions: '+str(counts))
    train=base+additions
    for name,data in [('train-v2.jsonl',train),('dev.jsonl',dev)]:
        path=ROOT/'data'/name;write(path,data)
        report[name]={'sha256':sha(path),'rows':len(data),'by_kind':dict(Counter(r['kind'] for r in data))}
    report.update(original386_preserved=True,hidden_exploratory=True,builder_saw_hidden=False,
                  train_dev_overlap_collisions=0,strict_overlap_collisions=0)
    (ROOT/'data/manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
