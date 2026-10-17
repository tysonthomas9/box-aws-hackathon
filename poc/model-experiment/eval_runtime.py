"""Evaluation-only SageMaker job: base/search dev, merged LoRA dev and hidden."""
import hashlib
import json
import os
from pathlib import Path
import time
import gc
import boto3
from botocore.config import Config
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, set_seed


def main():
    data_path=Path('/opt/ml/input/data/data/evaluation.json')
    data=json.loads(data_path.read_text());set_seed(17)
    all_answers=[];stages=[]
    for channel,modes in [('base',['base','search']),('candidate',['lora'])]:
        start=time.monotonic();path=Path('/opt/ml/input/data')/channel
        verified={}
        for name,expected in data.get('candidate_files',{}).items() if channel=='candidate' else []:
            digest=hashlib.sha256()
            with (path/name).open('rb') as source:
                for chunk in iter(lambda:source.read(8*1024*1024),b''):digest.update(chunk)
            if digest.hexdigest()!=expected['sha256'] or (path/name).stat().st_size!=expected['bytes']:raise ValueError('Candidate changed: '+name)
            verified[name]=expected
        tokenizer=AutoTokenizer.from_pretrained(path,local_files_only=True)
        model=AutoModelForCausalLM.from_pretrained(path,torch_dtype=torch.bfloat16,device_map={'':0},local_files_only=True,attn_implementation='sdpa')
        model.eval()
        for mode in modes:
            for row in data['prompts']:
                if mode!='lora' and row['split']!='dev':continue
                messages=row['search_messages'] if mode=='search' else row['messages']
                prompt=tokenizer.apply_chat_template(messages,tokenize=False,add_generation_prompt=True,enable_thinking=False)
                encoded=tokenizer(prompt,add_special_tokens=False,return_tensors='pt').to('cuda')
                with torch.inference_mode():
                    output=model.generate(**encoded,do_sample=False,max_new_tokens=256,pad_token_id=tokenizer.eos_token_id)
                generated=output[0,encoded['input_ids'].shape[1]:]
                all_answers.append({'id':row['id'],'split':row['split'],'mode':mode,'prompt':prompt,
                    'answer':tokenizer.decode(generated,skip_special_tokens=True),'generated_tokens':len(generated),
                    'finish_reason':'length' if len(generated)>=256 else 'stop'})
                print('Answered '+mode+' '+row['id'],flush=True)
        stages.append({'channel':channel,'seconds':time.monotonic()-start,'cuda_max_memory_bytes':torch.cuda.max_memory_allocated(),'verified_files':verified})
        del model;gc.collect();torch.cuda.empty_cache()
    report={'answers':all_answers,'stages':stages,'decoding':{'do_sample':False,'max_new_tokens':256,'enable_thinking':False},
            'serving_runtime':'SageMaker/transformers (not Bedrock)','evaluation_sha256':hashlib.sha256(data_path.read_bytes()).hexdigest()}
    payload=json.dumps(report,indent=2).encode()
    s3=boto3.client('s3',region_name='us-east-2',config=Config(retries={'mode':'adaptive','total_max_attempts':4}))
    s3.put_object(Bucket=os.environ['POC_BUCKET'],Key=os.environ['POC_OUTPUT_PREFIX']+'/responses.json',Body=payload,ContentType='application/json',Tagging='project=box-hackathon&poc=model-experiment')
    Path('/opt/ml/model/evaluation.json').write_bytes(payload)


if __name__=='__main__':main()
