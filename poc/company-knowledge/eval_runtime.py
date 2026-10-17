"""Evaluation only: exact merged weights, sealed prompts, no optimizer or training."""
import hashlib
import json
import os
from pathlib import Path
import time
import boto3
from botocore.config import Config
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed

LABEL = 'served via SageMaker/transformers, not Bedrock'


def main():
    start = time.monotonic()
    base = Path('/opt/ml/input/data/base')
    data = json.loads(Path('/opt/ml/input/data/data/prompts.json').read_text())
    verified = {}
    for key, expected in data['merged_files'].items():
        name = key.rsplit('/', 1)[1]
        path = base / name
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(8*1024*1024), b''):
                digest.update(chunk)
        if path.stat().st_size != expected['bytes'] or digest.hexdigest() != expected['sha256']:
            raise ValueError('Merged artifact changed: ' + name)
        verified[name] = expected
    set_seed(17)
    tokenizer = AutoTokenizer.from_pretrained(base, local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(base, torch_dtype=torch.bfloat16,
        device_map={'': 0}, local_files_only=True, attn_implementation='sdpa')
    model.eval()
    loaded = time.monotonic()
    answers = []
    for row in data['prompts']:
        encoded = tokenizer(row['prompt'], add_special_tokens=False, return_tensors='pt').to('cuda')
        with torch.inference_mode():
            output = model.generate(**encoded, do_sample=False, max_new_tokens=256,
                pad_token_id=tokenizer.eos_token_id)
        generated = output[0, encoded['input_ids'].shape[1]:]
        answers.append({'id': row['id'], 'prompt': row['prompt'],
            'answer': tokenizer.decode(generated, skip_special_tokens=True),
            'generated_tokens': len(generated),
            'finish_reason': 'length' if len(generated) >= 256 else 'stop',
            'serving_runtime': LABEL})
        print('Answered ' + row['id'], flush=True)
    report = {'serving_runtime': LABEL, 'answers': answers, 'verified_files': verified,
        'hidden_sha256': data['hidden_sha256'], 'addendum_sha256': data['addendum_sha256'],
        'prompt_manifest_sha256': hashlib.sha256(Path('/opt/ml/input/data/data/prompts.json').read_bytes()).hexdigest(),
        'decoding': {'temperature': 0, 'do_sample': False, 'max_new_tokens': 256},
        'load_and_verify_seconds': loaded-start, 'generation_seconds': time.monotonic()-loaded,
        'torch': torch.__version__, 'cuda_max_memory_bytes': torch.cuda.max_memory_allocated()}
    payload = json.dumps(report, indent=2).encode()
    client = boto3.client('s3', region_name='us-east-2', config=Config(retries={'mode':'adaptive','total_max_attempts':4}))
    client.put_object(Bucket=os.environ['POC_BUCKET'], Key='evaluation/seed17/responses.json',
        Body=payload, ContentType='application/json', Tagging='project=box-hackathon&poc=company-knowledge')
    Path('/opt/ml/model/evaluation.json').write_bytes(payload)
    print(json.dumps({'serving_runtime': LABEL, 'answers': len(answers), 'generation_seconds': report['generation_seconds']}), flush=True)


if __name__ == '__main__':
    main()
