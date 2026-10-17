"""Copy pinned JumpStart 8B artifacts within Ohio; no weight downloads to host."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import urllib.request
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sagemaker-bedrock'))
from base_import import aws,save
ROOT=Path(__file__).resolve().parent
BUCKET='box-hackathon-experiment-20261017-549803795565'
STATE=ROOT/'evidence/mirror.json'
TAGS=[{'Key':'project','Value':'box-hackathon'},{'Key':'poc','Value':'model-experiment'}]


def main():
    state=json.loads(STATE.read_text()) if STATE.exists() else {}
    if not state.get('bucket_created'):
        aws('s3api','create-bucket','--bucket',BUCKET,'--create-bucket-configuration','{"LocationConstraint":"us-east-2"}')
        state['bucket_created']=True;save(state,STATE)
    aws('s3api','put-bucket-tagging','--bucket',BUCKET,'--tagging',json.dumps({'TagSet':TAGS}))
    aws('s3api','put-public-access-block','--bucket',BUCKET,'--public-access-block-configuration',json.dumps(dict.fromkeys(['BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets'],True)))
    aws('s3api','put-bucket-encryption','--bucket',BUCKET,'--server-side-encryption-configuration',json.dumps({'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]}))
    hub=aws('sagemaker','describe-hub-content','--hub-name','SageMakerPublicHub','--hub-content-type','Model','--hub-content-name','huggingface-reasoning-qwen3-8b','--hub-content-version','3.15.0')
    doc=json.loads(hub['HubContentDocument'])
    if doc.get('GatedBucket') or doc['License']!='Apache 2.0':raise ValueError('Unexpected license/gating')
    src,prefix=doc['HostingArtifactUri'].removeprefix('s3://').split('/',1)
    if src!='jumpstart-cache-prod-us-east-2' or doc['HostingArtifactCompressionType']!='None':raise ValueError('Unexpected source')
    state.update(hub_arn=hub['HubContentArn'],hub_document=doc,source=doc['HostingArtifactUri'],bucket=BUCKET)
    state.setdefault('files',{});save(state,STATE)
    for o in aws('s3api','list-objects-v2','--bucket',src,'--prefix',prefix)['Contents']:
        name=o['Key'].removeprefix(prefix)
        if '/' in name or name.startswith(('.','__')) or name.endswith('.py') or name=='version':continue
        if name in state['files']:continue
        if o['Size']>=5*1024**3:raise ValueError('Needs multipart copy')
        result=aws('s3api','copy-object','--bucket',BUCKET,'--key','base8/'+name,'--copy-source',src+'/'+o['Key'],'--checksum-algorithm','SHA256','--tagging-directive','REPLACE','--tagging','project=box-hackathon&poc=model-experiment')
        state['files'][name]={'source_key':o['Key'],'source_etag':o['ETag'],'bytes':o['Size'],'copy':result};save(state,STATE)
        print('Copied '+name,flush=True)
    with tempfile.NamedTemporaryFile(prefix='experiment-config-') as f:
        aws('s3api','get-object','--bucket',BUCKET,'--key','base8/config.json',f.name)
        original=Path(f.name).read_bytes();config=json.loads(original)
        if config['architectures']!=['Qwen3ForCausalLM']:raise ValueError('Wrong architecture')
        state['original_config_sha256']=hashlib.sha256(original).hexdigest()
        config['max_position_embeddings']=32768
        Path(f.name).write_text(json.dumps(config,indent=2)+'\n')
        aws('s3api','put-object','--bucket',BUCKET,'--key','base8/config.json','--body',f.name,'--tagging','project=box-hackathon&poc=model-experiment')
        state['config_sha256']=hashlib.sha256(Path(f.name).read_bytes()).hexdigest()
    url='https://huggingface.co/Qwen/Qwen3-8B/raw/main/LICENSE'
    license_data=urllib.request.urlopen(url).read()
    if b'Apache License' not in license_data:raise ValueError('Unexpected LICENSE')
    with tempfile.NamedTemporaryFile(prefix='experiment-license-') as f:
        f.write(license_data);f.flush()
        aws('s3api','put-object','--bucket',BUCKET,'--key','base8/LICENSE','--body',f.name,'--tagging','project=box-hackathon&poc=model-experiment')
    state.update(license_source=url,license_sha256=hashlib.sha256(license_data).hexdigest(),completed_at=datetime.now(timezone.utc).isoformat())
    save(state,STATE);print('Mirror ready',flush=True)


if __name__=='__main__':main()
