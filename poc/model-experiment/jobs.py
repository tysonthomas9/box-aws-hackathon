"""Bounded SageMaker experiment jobs; explicit ownership, inputs, and spend caps."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'sagemaker-bedrock'))
from base_import import aws,save
ROOT=Path(__file__).resolve().parent
BUCKET='box-hackathon-experiment-20261017-549803795565'
BASE4='s3://box-hackathon-poc1-base-20261017-549803795565/base/'
BASE8=f's3://{BUCKET}/base8/'
IMAGE='763104351884.dkr.ecr.us-east-2.amazonaws.com/pytorch-training@sha256:ec77d5e5d0e9871c8bb20331a74d1e8c308cdda9143b909b4b5eb99bba795d4d'
TAGS=[{'Key':'project','Value':'box-hackathon'},{'Key':'poc','Value':'model-experiment'}]


def launch(kind,state,path,prepare_only=False):
    from budget import check
    check()
    if state.get('job_arn'):raise RuntimeError('Already submitted; use status')
    size=kind[-1]; training=kind.startswith('train')
    name=f'box-hackathon-experiment-{kind}-20261017'
    instance='ml.g5.2xlarge' if size=='4' else 'ml.g6.2xlarge'
    quota='L-2D6DEB3C' if size=='4' else 'L-A1025C0C'
    assert aws('sts','get-caller-identity')['Account']=='549803795565'
    assert aws('service-quotas','get-service-quota','--service-code','sagemaker','--quota-code',quota)['Quota']['Value']>=1
    active=aws('sagemaker','list-training-jobs','--status-equals','InProgress')['TrainingJobSummaries']
    for job in active:
        details=aws('sagemaker','describe-training-job','--training-job-name',job['TrainingJobName'])
        if details['ResourceConfig']['InstanceType']==instance:raise RuntimeError('Instance quota occupied by '+job['TrainingJobName'])
    assert aws('s3api','get-bucket-location','--bucket',BUCKET)['LocationConstraint']=='us-east-2'
    manifest=json.loads((ROOT/'data/manifest.json').read_text())
    for filename in ['train-v2.jsonl','dev.jsonl']:
        assert hashlib.sha256((ROOT/'data'/filename).read_bytes()).hexdigest()==manifest[filename]['sha256']
    if size=='8': assert json.loads((ROOT/'evidence/mirror.json').read_text()).get('completed_at')
    script=ROOT/('train.py' if training else 'eval_runtime.py')
    data=ROOT/'data'/('train-v2.jsonl' if training else 'evaluation.json')
    prefix=f'control/{kind}'
    data_name='train.jsonl' if training else 'evaluation.json'
    if not training:
        report_path=ROOT/'evidence'/f'train{size}-report.json'
        report=json.loads(report_path.read_text())
        evaluation=json.loads(data.read_text())
        evaluation['candidate_files']={k.rsplit('/',1)[1]:v for k,v in report['files'].items() if '/merged/' in k}
        data=ROOT/'data'/f'evaluation{size}.json'
        data.write_text(json.dumps(evaluation,indent=2)+'\n')
    for source,key in [(script,prefix+'/'+script.name),(data,prefix+'/'+data_name)]:
        aws('s3api','put-object','--bucket',BUCKET,'--key',key,'--body',str(source),'--tagging','project=box-hackathon&poc=model-experiment')
    state.update(kind=kind,name=name,instance=instance,script_sha256=hashlib.sha256(script.read_bytes()).hexdigest(),data_sha256=hashlib.sha256(data.read_bytes()).hexdigest(),control_prefix=prefix)
    save(state,path)
    if not state.get('role_arn'):
        trust={'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'sagemaker.amazonaws.com'},'Action':'sts:AssumeRole','Condition':{'StringEquals':{'aws:SourceAccount':'549803795565'},'ArnLike':{'aws:SourceArn':f'arn:aws:sagemaker:us-east-2:549803795565:training-job/{name}'}}}]}
        role=aws('iam','create-role','--role-name',name,'--assume-role-policy-document',json.dumps(trust),'--tags',json.dumps(TAGS))
        state.update(role_arn=role['Role']['Arn'],role_name=name);save(state,path)
    source=BASE4 if size=='4' else BASE8
    sources=[source,f's3://{BUCKET}/{prefix}/']
    if not training:sources.append(f's3://{BUCKET}/training/train{size}/merged/')
    source_arns=['arn:aws:s3:::'+s.removeprefix('s3://')+'*' for s in sources]
    buckets=sorted({s.removeprefix('s3://').split('/')[0] for s in sources})
    output=('training' if training else 'evaluation')+'/'+kind
    policy={'Version':'2012-10-17','Statement':[
        {'Effect':'Allow','Action':'s3:ListBucket','Resource':['arn:aws:s3:::'+b for b in buckets]},
        {'Effect':'Allow','Action':'s3:GetObject','Resource':source_arns},
        {'Effect':'Allow','Action':['s3:PutObject','s3:PutObjectTagging','s3:AbortMultipartUpload'],'Resource':[f'arn:aws:s3:::{BUCKET}/{output}/*',f'arn:aws:s3:::{BUCKET}/artifacts/{kind}/*']},
        {'Effect':'Allow','Action':'ecr:GetAuthorizationToken','Resource':'*'},
        {'Effect':'Allow','Action':['ecr:BatchGetImage','ecr:GetDownloadUrlForLayer','ecr:BatchCheckLayerAvailability'],'Resource':'arn:aws:ecr:us-east-2:763104351884:repository/pytorch-training'},
        {'Effect':'Allow','Action':['logs:CreateLogStream','logs:PutLogEvents'],'Resource':f'arn:aws:logs:us-east-2:549803795565:log-group:/aws/sagemaker/TrainingJobs:log-stream:{name}*'}]}
    aws('iam','put-role-policy','--role-name',name,'--policy-name','OwnedJob','--policy-document',json.dumps(policy))
    state['policy']=policy;save(state,path)
    group='/aws/sagemaker/TrainingJobs'
    groups=aws('logs','describe-log-groups','--log-group-name-prefix',group)['logGroups']
    if not any(g['logGroupName']==group for g in groups):
        aws('logs','create-log-group','--log-group-name',group,'--tags','project=box-hackathon,poc=model-experiment')
        state['created_log_group']=group;save(state,path)
        aws('logs','put-retention-policy','--log-group-name',group,'--retention-in-days','1')
    channels=[]
    for channel,uri in [('base',source),('code',f's3://{BUCKET}/{prefix}/{script.name}'),('data',f's3://{BUCKET}/{prefix}/{data_name}')]+([] if training else [('candidate',f's3://{BUCKET}/training/train{size}/merged/')]):
        channels.append({'ChannelName':channel,'DataSource':{'S3DataSource':{'S3DataType':'S3Prefix','S3Uri':uri,'S3DataDistributionType':'FullyReplicated'}}})
    bootstrap='python -m pip install --no-cache-dir transformers==4.51.3 peft==0.15.2 accelerate==1.6.0 safetensors==0.5.3 && python /opt/ml/input/data/code/'+script.name
    request={'TrainingJobName':name,'RoleArn':state['role_arn'],'AlgorithmSpecification':{'TrainingImage':IMAGE,'TrainingInputMode':'File','ContainerEntrypoint':['bash','-lc',bootstrap]},
        'InputDataConfig':channels,'OutputDataConfig':{'S3OutputPath':f's3://{BUCKET}/artifacts/{kind}/'},
        'ResourceConfig':{'InstanceType':instance,'InstanceCount':1,'VolumeSizeInGB':120},
        'StoppingCondition':{'MaxRuntimeInSeconds':2400 if training else 1800,'MaxPendingTimeInSeconds':1800},
        'EnableManagedSpotTraining':False,'EnableNetworkIsolation':False,
        'Environment':{'AWS_REGION':'us-east-2','POC_BUCKET':BUCKET,'POC_OUTPUT_PREFIX':output,'POC_NAME':'model-experiment','POC_EPOCHS':'3','POC_SEED':'17','POC_LEARNING_RATE':'0.0002','POC_MAX_LENGTH':'512','POC_GRAD_ACCUMULATION':'4','AWS_SDK_UA_APP_ID':'AWSSkill-SageMaker','TOKENIZERS_PARALLELISM':'false'},'Tags':TAGS}
    state['request']=request;save(state,path)
    if prepare_only:
        print(json.dumps({'prepared':name,'role_arn':state['role_arn']}));return
    result=aws('sagemaker','create-training-job','--cli-input-json',json.dumps(request))
    state.update(job_arn=result['TrainingJobArn'],submitted_at=datetime.now(timezone.utc).isoformat());save(state,path)
    print(json.dumps({'name':name,'job_arn':state['job_arn']}))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','launch','status']);parser.add_argument('kind',choices=['train4','train8','eval4','eval8']);args=parser.parse_args()
    path=ROOT/'evidence'/(args.kind+'.json');state=json.loads(path.read_text()) if path.exists() else {}
    if args.action in ['prepare','launch']:launch(args.kind,state,path,args.action=='prepare')
    else:
        status=aws('sagemaker','describe-training-job','--training-job-name',state['name']);state['status']=status;save(state,path)
        print(json.dumps({k:status.get(k) for k in ['TrainingJobName','TrainingJobStatus','FailureReason','TrainingTimeInSeconds','BillableTimeInSeconds','SecondaryStatus']}))


if __name__=='__main__':main()
