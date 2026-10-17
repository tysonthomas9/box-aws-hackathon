"""Conservative experiment budget ledger, not a final AWS invoice."""
from datetime import datetime, timezone
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
RATES={'us.moonshotai.kimi-k3':{'inputTokens':3.30,'outputTokens':16.50,'cacheReadInputTokens':.33,'cacheWriteInputTokens':4.125},
       'zai.glm-5':{'inputTokens':1.0,'outputTokens':3.20,'cacheReadInputTokens':1.0,'cacheWriteInputTokens':1.0}}
GPU={'4':1.515,'8':1.222}
CAPS={'train4':2400,'train8':2400,'eval4':1800,'eval8':1800}


def check():
    usage={};helper_cost=0
    for folder in ['data','scores']:
        for p in (ROOT/folder).rglob('*.json'):
            value=json.loads(p.read_text())
            if not isinstance(value,dict):continue
            model=value.get('request',{}).get('modelId')
            if model not in RATES or 'response' not in value:continue
            tokens=value['response']['usage'];cost=sum(tokens.get(k,0)*rate/1e6 for k,rate in RATES[model].items())
            entry=usage.setdefault(model,{'calls':0,'cost_usd':0,'tokens':{}})
            entry['calls']+=1;entry['cost_usd']+=cost;helper_cost+=cost
            for k in RATES[model]:entry['tokens'][k]=entry['tokens'].get(k,0)+tokens.get(k,0)
    jobs={};gpu_cost=0
    for name,cap in CAPS.items():
        p=ROOT/'evidence'/(name+'.json');state=json.loads(p.read_text()) if p.exists() else {}
        status=state.get('status',{})
        done=status.get('TrainingJobStatus') in ['Completed','Failed','Stopped']
        seconds=status.get('BillableTimeInSeconds',status.get('TrainingTimeInSeconds',cap)) if done else cap
        cost=seconds/3600*GPU[name[-1]];gpu_cost+=cost
        jobs[name]={'reserved':not done,'seconds':seconds,'cost_usd':cost,'rate_per_hour':GPU[name[-1]]}
    # Reserve additional helper inference, startup billing windows and temporary storage.
    reserve={'future_helper_calls_usd':0 if (ROOT/'scores/results.json').exists() else 3.0,
             'bedrock_startup_and_model_storage_usd':1.5,'s3_ebs_logs_requests_usd':.5}
    total=helper_cost+gpu_cost+sum(reserve.values())
    result={'checked_at':datetime.now(timezone.utc).isoformat(),'limit_usd':10,'helper_usage':usage,
        'jobs':jobs,'reserves':reserve,'conservative_total_usd':total,
        'sources':['https://aws.amazon.com/bedrock/pricing/','evidence/training-prices.json'],
        'caveat':'Token usage and GPU billable seconds plus conservative remaining reserves; final bill may arrive later.'}
    (ROOT/'evidence/budget.json').write_text(json.dumps(result,indent=2)+'\n')
    if total>10:raise RuntimeError(f'Experiment budget reservation {total:.2f} exceeds $10; stop and report')
    return result


def main():print(json.dumps(check(),indent=2))
if __name__=='__main__':main()
