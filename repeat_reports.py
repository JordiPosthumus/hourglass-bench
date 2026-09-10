"""Average completed repeats only within identical recorded comparison conditions."""
import copy
import hashlib
import json
import statistics
import report_charts


def group_key(report):
    config=report.get('configuration_key')
    if not config or report.get('state')!='final' or report.get('is_current_run') or report.get('repair') or report.get('caveats'):return None
    fields=('benchmark_version','bank_fingerprint','machine_key','scoring','timing_policy','question_timeout_policy','execution')
    return json.dumps([config,*[report.get(k) for k in fields],report.get('experiment',{}).get('parameters')],sort_keys=True)


def average(reports):
    groups={};order=[]
    for report in reports:
        key=group_key(report) or 'individual:'+report['run_key']
        if key not in groups:groups[key]=[];order.append(key)
        groups[key].append(report)
    output=[]
    for key in order:
        members=groups[key]
        if len(members)==1:output.append(members[0]);continue
        result=copy.deepcopy(members[0]);n=len(members)
        result.update(run_key=hashlib.sha256(key.encode()).hexdigest()[:24],repeat_count=n,
                      member_run_keys=[r['run_key'] for r in members],is_current_run=False)
        result['display_name']=(result.get('display_name') or result['model'])+f' · mean of {n}'
        for field in ('weighted_points','raw_correct','gross_points','net_points','incorrect_questions','abstained_questions','penalty_points','completed_questions','clock_adjustment_seconds','unsupported_vision_questions'):
            if all(isinstance(r.get(field),(float,int)) for r in members):result[field]=statistics.mean(r[field] for r in members)
        times=sorted({0,3600,*[p['seconds'] for r in members for p in r['curve']]})
        def value(r,t,field,before):
            points=[p for p in r['curve'] if p['seconds']<t or (not before and p['seconds']==t)]
            return points[-1][field] if points else 0
        result['curve']=[{'seconds':t,**{field:statistics.mean(value(r,t,field,before) for r in members) for field in ('weighted','correct')}} for t in times for before in (True,False)]
        for field in ('breakdown','timeouts','run_date'):result.pop(field,None)
        result['active_seconds']=3600
        result['auc']=report_charts.auc(result['curve'],final=True)
        result['auc']['scoring_policy']=result['scoring']
        result['efficiency']={'token_data_complete':False}
        result['aggregation']='Arithmetic mean of completed equivalent runs; individual runs retained.'
        output.append(result)
    return output
