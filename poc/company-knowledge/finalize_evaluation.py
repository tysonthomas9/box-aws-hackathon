"""Validate cached 52-answer GLM evidence and combine with immutable Bedrock baselines."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from review_training import parse_json

ROOT = Path(__file__).resolve().parent
LABEL = 'served via SageMaker/transformers, not Bedrock'


def main():
    folder = ROOT / 'evaluation/lora-seed17-sagemaker'
    summary = json.loads((folder / 'summary.json').read_text())
    baseline = json.loads((ROOT / 'evaluation/combined-v2.json').read_text())
    assert hashlib.sha256((ROOT/'evaluation/combined-v2.json').read_bytes()).hexdigest() == '52297c855cab3c4494806451ca98c7ee3bbb22bd3be022d2eed644bb5e0c1ec7'
    source = json.loads((ROOT/'evidence/seed17-sagemaker-responses.json').read_text())
    prompts_bytes = (ROOT/'sealed/eval-prompts.json').read_bytes()
    prompts = json.loads(prompts_bytes)
    assert source['prompt_manifest_sha256'] == hashlib.sha256(prompts_bytes).hexdigest()
    assert source['verified_files'] == {k.rsplit('/',1)[1]:v for k,v in prompts['merged_files'].items()}
    assert summary['serving_runtime'] == source['serving_runtime'] == LABEL
    assert summary['hidden_sha256'] == baseline['original_hidden_sha256']
    assert summary['addendum_sha256'] == prompts['addendum_sha256']
    by_id = {a['id']:a for a in source['answers']}
    assert len(by_id) == len(summary['responses']) == len(summary['decisions']) == 52
    cached_decisions = []
    for path in sorted(folder.glob('judge-*.json')):
        e = json.loads(path.read_text())
        assert hashlib.sha256(json.dumps(e['request'],sort_keys=True).encode()).hexdigest() == e['request_sha256']
        cached_decisions.extend(parse_json(''.join(c.get('text','') for c in e['response']['output']['message']['content'])))
    lookup = {(v['mode'],v['id']):v for v in cached_decisions}
    counts = {}
    for row in summary['responses']:
        ident = row['id']; raw = by_id[ident]
        assert raw['answer'] == row['answer'] and row['serving_runtime'] == LABEL
        e = json.loads((folder/f'lora-{ident}.json').read_text())
        assert hashlib.sha256(json.dumps(e['request'],sort_keys=True).encode()).hexdigest() == e['request_sha256']
        assert e['request']['payload']['prompt'] == raw['prompt']
        assert e['request']['payload']['max_gen_len'] == 256 and e['request']['payload']['temperature'] == 0
        assert json.loads((folder/f'lora-{ident}.body.json').read_text()) == e['response']
        decision = lookup[('lora',ident)]
        recorded = next(d for d in summary['decisions'] if d['id']==ident)
        assert all(recorded[k]==decision[k] for k in ['correct','invented','reason'])
        kind = 'procedure' if row['kind'] in ['heldout_procedure','procedure'] else row['kind']
        c = counts.setdefault(kind, {'correct':0,'total':0,'invented':0})
        c['total'] += 1;c['correct'] += decision['correct'];c['invented'] += decision['invented']
    output = {'verified_at':datetime.now(timezone.utc).isoformat(),
        'counts':{**baseline['counts'],'lora_sagemaker':counts},
        'lora_serving_runtime':LABEL,'baseline_runtime':'served via Bedrock',
        'hidden_sha256':summary['hidden_sha256'],'addendum_sha256':summary['addendum_sha256'],
        'training_sha256':'92edb882d2233b7604b2072abe98c46d81dced97b0a54356788f160dddac1a72',
        'finish_reasons':dict(Counter(a['finish_reason'] for a in source['answers'])),
        'limitations':['Single seed17;52 exploratory model-judged questions; no confidence claim.',
            'LoRA served via SageMaker/transformers, not Bedrock. Runtime differs from baselines; no matched-transformers base control.',
            'Seen-rule addendum authored after dataset generation but sealed before LoRA; original46 sealed before generation.',
            'Raw GLM decisions preserved. Contradictory procedural prose can be overcredited; inspect A03,A04,A06 and baseline retrievalA03.',
            'Bedrock candidate imported but never answered during bounded11call/10minute readiness test.'],
        'recommendation':'ADJUST: use search as authoritative company knowledge; do not ship this LoRA as sole factual source or claim Bedrock-serving acceptance.',
        'summary_sha256':hashlib.sha256((folder/'summary.json').read_bytes()).hexdigest()}
    (ROOT/'evaluation/final-comparison.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output,indent=2))


if __name__ == '__main__':
    main()
