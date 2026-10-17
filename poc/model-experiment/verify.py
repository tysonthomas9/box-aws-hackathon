"""Read-only evidence checks and independent paired-count reconstruction; no AWS calls."""
from collections import Counter
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_text())
def pair_counts(left,right,ids):
    counts={'both_correct':0,'4B_only':0,'8B_only':0,'both_wrong':0}
    for i in ids:
        key='both_correct' if left[i] and right[i] else '4B_only' if left[i] else '8B_only' if right[i] else 'both_wrong'
        counts[key]+=1
    return counts


def main():
    manifest=load(ROOT/'data/manifest.json');mapping=load(ROOT/'scores/mapping.json');result=load(ROOT/'scores/results.json')
    for name in ['dev.jsonl','train-v2.jsonl']:assert sha(ROOT/'data'/name)==manifest[name]['sha256']
    assert len(mapping)==284 and len({r['blind_id'] for r in mapping})==284
    lookup={r['blind_id']:r for r in mapping};decisions={}
    for path in sorted((ROOT/'scores').glob('judge-*.json')):
        e=load(path)
        assert hashlib.sha256(json.dumps(e['request'],sort_keys=True).encode()).hexdigest()==e['request_sha256']
        assert e['request']['modelId']=='zai.glm-5' and e['response']['stopReason']=='end_turn'
        prompt=e['request']['messages'][0]['content'][0]['text']
        provided=json.loads(prompt.split('\n',1)[1])
        assert all(set(r)=={'id','test','answer'} for r in provided)
        assert all(r['test']==lookup[r['id']]['test'] and r['answer']==lookup[r['id']]['answer'] for r in provided)
        text=''.join(c.get('text','') for c in e['response']['output']['message']['content']).strip()
        if text.startswith('```json\n') and text.endswith('\n```'):text=text[8:-4]
        batch=json.loads(text)
        assert {r['id'] for r in batch}=={r['id'] for r in provided} and len(batch)==len(provided)
        for d in batch:
            assert d['id'] not in decisions and type(d['correct'])is bool and type(d['invented'])is bool
            decisions[d['id']]=d
    assert decisions=={d['id']:d for d in result['decisions']}
    for size in ['4','8']:
        raw=load(ROOT/f'evidence/eval{size}-responses.json');state=load(ROOT/f'evidence/eval{size}.json')
        assert raw['evaluation_sha256']==sha(ROOT/f'data/evaluation{size}.json')==state['data_sha256']
        assert state['script_sha256']==sha(ROOT/'eval_runtime.py')
        raw_lookup={(r['mode'],r['id']):r for r in raw['answers']}
        for r in mapping:
            if r['size']==size:assert r['answer']==raw_lookup[(r['mode'],r['id'])]['answer']
    counts={};pairs={};totals={}
    for split in ['dev','hidden']:
        counts[split]={};pairs[split]={};totals[split]={}
        for size in ['4','8']:
            for mode in ['base','search','lora']:
                selected=[r for r in mapping if r['split']==split and r['size']==size and r['mode']==mode]
                if not selected:continue
                key=size+'B-'+mode;counts[split][key]={}
                for kind in sorted({r['kind'] for r in selected}):
                    subset=[r for r in selected if r['kind']==kind]
                    counts[split][key][kind]={'correct':sum(decisions[r['blind_id']]['correct'] for r in subset),'total':len(subset),'invented':sum(decisions[r['blind_id']]['invented'] for r in subset)}
                totals[split][key]={'correct':sum(decisions[r['blind_id']]['correct'] for r in selected),'total':len(selected)}
        for mode in ['base','search','lora']:
            left={r['id']:decisions[r['blind_id']]['correct'] for r in mapping if r['split']==split and r['size']=='4' and r['mode']==mode}
            right={r['id']:decisions[r['blind_id']]['correct'] for r in mapping if r['split']==split and r['size']=='8' and r['mode']==mode}
            if not left:continue
            assert left.keys()==right.keys()
            kinds={r['id']:r['kind'] for r in mapping if r['split']==split}
            pairs[split][mode]={'all':pair_counts(left,right,left)}
            for kind in sorted(set(kinds.values())):
                ids=[i for i in left if kinds[i]==kind]
                pairs[split][mode][kind]=pair_counts(left,right,ids)
    assert counts==result['counts']
    output={'verified':True,'totals':totals,'counts':counts,'paired_4B_8B':pairs,'paired_baseline_lora':result['paired'],
        'training_sha256':manifest['train-v2.jsonl']['sha256'],'dev_sha256':manifest['dev.jsonl']['sha256'],
        'results_sha256':sha(ROOT/'scores/results.json'),'raw_response_sha256':{s:sha(ROOT/f'evidence/eval{s}-responses.json') for s in ['4','8']},
        'checks':['All284 blinded decisions reproduced from cached GLM-5 responses','No model size or mode in judge examples','Counts independently recomputed','Exact source response/data/control hashes match','Frozen training and dev hashes preserved']}
    (ROOT/'scores/verification.json').write_text(json.dumps(output,indent=2)+'\n');print(json.dumps({'totals':totals,'pairs':{s:{m:p['all'] for m,p in modes.items()} for s,modes in pairs.items()}},indent=2))


if __name__=='__main__':main()
