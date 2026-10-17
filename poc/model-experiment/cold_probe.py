"""One bounded runtime probe; schedule calls 60s apart, stop after ten minutes."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
ROOT=Path(__file__).resolve().parent


def main():
    state=json.loads((ROOT/'evidence/reimport.json').read_text())
    if state.get('import_status',{}).get('status')!='Completed':raise ValueError('Import not completed')
    path=ROOT/'evidence/cold-runtime.json';report=json.loads(path.read_text()) if path.exists() else {'attempts':[]}
    now=datetime.now(timezone.utc)
    if report.get('outcome'):print(json.dumps(report));return
    if report['attempts'] and (now-datetime.fromisoformat(report['attempts'][0]['started_at'])).total_seconds()>=600:
        report['outcome']='never_served_within_10min'
    else:
        payload={'prompt':'<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\nReply with the single word READY.<|im_end|>\n<|im_start|>assistant\n','max_gen_len':16,'temperature':0}
        attempt={'started_at':now.isoformat(),'model_arn':state['model_arn'],'payload':payload}
        with tempfile.NamedTemporaryFile(prefix='model-experiment-probe-') as f:
            start=time.monotonic()
            result=subprocess.run(['aws','--profile','box-hackathon','--region','us-east-2','bedrock-runtime','invoke-model','--model-id',state['model_arn'],'--content-type','application/json','--accept','application/json','--cli-binary-format','raw-in-base64-out','--body',json.dumps(payload),'--cli-read-timeout','35',f.name],env=dict(os.environ,AWS_MAX_ATTEMPTS='1',AWS_SDK_UA_APP_ID='AWSSkill-SageMaker'),capture_output=True,text=True,timeout=45)
            attempt.update(seconds=time.monotonic()-start,exit_code=result.returncode,stdout=result.stdout,stderr=result.stderr)
            if result.returncode==0:
                attempt['response']=json.loads(Path(f.name).read_text());report['outcome']='served'
            elif 'ModelNotReadyException' not in result.stderr:
                report['outcome']='runtime_error_requires_attention'
        report['attempts'].append(attempt)
    if report.get('outcome'):
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        report['observed_elapsed_seconds']=(datetime.fromisoformat(report['finished_at'])-datetime.fromisoformat(report['attempts'][0]['started_at'])).total_seconds()
    path.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'outcome':report.get('outcome'),'attempts':len(report['attempts'])}))


if __name__=='__main__':main()
