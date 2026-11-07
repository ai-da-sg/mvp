"""Evidence-based GEO entity analysis and comparable baseline/retest reports."""
import copy
import hashlib
import json
import random
import re
from urllib.parse import urlsplit

from kf_ai import AIError
from kf_geo import string, url


def names(value, limit=10):
    if not isinstance(value,list) or len(value)>limit:raise AIError('Invalid brand aliases')
    result=[]
    for item in value:
        item=string(item,'alias',200,True)
        if item.casefold() not in {v.casefold() for v in result}:result.append(item)
    return result


def domains(value):
    if not isinstance(value,list) or len(value)>10:raise AIError('Use at most 10 owned domains')
    result=[]
    for item in value:
        item=string(item,'domain',253,True).lower().rstrip('.')
        canonical=urlsplit(url('https://'+item)).hostname
        parsed=urlsplit('https://'+item)
        if parsed.hostname!=item or parsed.path or parsed.query or parsed.fragment or parsed.port:raise AIError('Enter a domain without path or port')
        result.append(canonical.removeprefix('www.'))
    return sorted(set(result))


def clean_entities(profile):
    competitors=profile.get('competitors',[])
    if not isinstance(competitors,list) or len(competitors)>10:raise AIError('Use at most 10 competitors')
    clean=[];seen={profile['brand'].casefold(),*(v.casefold() for v in names(profile.get('aliases',[])))}
    for item in competitors:
        if not isinstance(item,dict):raise AIError('Invalid competitor')
        name=string(item.get('name',''),'competitor',200,True)
        aliases=names(item.get('aliases',[]))
        identities={name.casefold(),*(v.casefold() for v in aliases)}
        if seen & identities:raise AIError('Brand and competitor names or aliases must be distinct')
        seen.update(identities)
        clean.append({'name':name,'aliases':aliases,'domains':domains(item.get('domains',[]))})
    return {'aliases':names(profile.get('aliases',[])),'owned_domains':domains(profile.get('owned_domains',[])),'competitors':clean}


def identity(profile):
    value={k:profile.get(k,[] if k!='brand' else '') for k in ('brand','aliases','owned_domains','competitors')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def mentioned(answer,names):
    answer=answer.casefold()
    for name in names:
        name=name.casefold()
        if name and (bool(re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',answer)) if name.isascii() else name in answer):return True
    return False


def entities(profile):
    return [{'name':profile['brand'],'aliases':profile.get('aliases',[]),'domains':profile.get('owned_domains',[]),'target':True}]+[
        dict(c,target=False) for c in profile.get('competitors',[])]


def signals(observation,profile):
    hosts={urlsplit(c).hostname.removeprefix('www.') for c in observation['citations'] if urlsplit(c).hostname}
    return [dict(name=e['name'],target=e['target'],mentioned=mentioned(observation['answer'],[e['name']]+e['aliases']),
                 cited=bool(hosts & set(e['domains']))) for e in entities(profile)]


def overview(data,domain):
    groups={};reviews={r['observation_id']:r for r in data.get('reviews',[])}
    source_reviews={r['domain']:r for r in data.get('source_reviews',[])}
    for o in data['observations']:
        if o['status']!='success':continue
        profile=copy.deepcopy(o.get('entity_profile',{'brand':o['brand']}))
        if not profile.get('owned_domains'):profile['owned_domains']=[domain.removeprefix('www.')]
        key=(o['platform'],o['channel'],o['model'],o['mode'],o['environment'],o['question']['language'],o['question']['market'],identity(profile),o.get('protocol_version','operator_record_v1'))
        group=groups.setdefault(key,{'platform':key[0],'channel':key[1],'model':key[2],'mode':key[3],'environment':key[4],
            'language':key[5],'market':key[6],'identity':key[7],'samples':0,'entities':{},'sources':{}})
        group['samples']+=1
        for signal in signals(o,profile):
            entity=group['entities'].setdefault(signal['name'],{'name':signal['name'],'target':signal['target'],'mentions':0,'citations':0,'recommendations':0,'recommendation_reviews':0,'accurate':0,'accuracy_reviews':0})
            review=reviews.get(o['id'],{}) if signal['target'] else {}
            entity['mentions']+=int(review.get('mentioned',o['brand_mentioned'] if signal['target'] else signal['mentioned']))
            entity['citations']+=int(signal['cited'])
            for field,positive,count in [('recommended','recommendations','recommendation_reviews'),('accurate','accurate','accuracy_reviews')]:
                if review.get(field) is not None:entity[count]+=1;entity[positive]+=int(review[field])
        owned=set(profile.get('owned_domains',[]))|{domain.removeprefix('www.')}
        for host in {urlsplit(c).hostname.removeprefix('www.') for c in o['citations'] if urlsplit(c).hostname}:
            source=group['sources'].setdefault(host,{'domain':host,'answers':0,'observation_ids':[],
                'category':source_reviews.get(host,{}).get('category','owned' if host in owned else 'unknown'),
                'review':source_reviews.get(host)})
            source['answers']+=1;source['observation_ids'].append(o['id'])
    for group in groups.values():
        total=sum(e['mentions'] for e in group['entities'].values())
        group['mention_events']=total
        group['entities']=list(group['entities'].values())
        for entity in group['entities']:entity['share_of_voice']=entity['mentions']/total if total else None
        group['sources']=sorted(group['sources'].values(),key=lambda s:(-s['answers'],s['domain']))
    return list(groups.values())


def comparison(data,baseline,retest):
    if baseline==retest:raise AIError('Select different baseline and retest batches')
    selected={b:[o for o in data['observations'] if o['batch']==b] for b in (baseline,retest)}
    if any(not v for v in selected.values()):raise AIError('Selected batch has no observations')
    for items in selected.values():
        versions={}
        for o in items:versions.setdefault(o['question']['id'],set()).add(o['question']['version'])
        if any(len(v)>1 for v in versions.values()):return {'comparable':False,'reason':'A batch mixes versions of the same question','rows':[],'summaries':[]}
    def key(o):
        q=o['question']
        return (o['platform'],o['channel'],o['model'],o['mode'],o['environment'],q['language'],q['market'],
                identity(o.get('entity_profile',{'brand':o['brand']})),o.get('protocol_version','operator_record_v1'),q['id'],q['version'])
    groups={b:{} for b in selected}
    for batch,items in selected.items():
        for o in items:groups[batch].setdefault(key(o),[]).append(o)
    if set(groups[baseline])!=set(groups[retest]):
        return {'comparable':False,'reason':'Question versions, entity definitions or sampling conditions differ','rows':[],'summaries':[]}
    rows=[];summaries={};reviews={r['observation_id']:r for r in data.get('reviews',[])}
    for k,left in groups[baseline].items():
        right=groups[retest][k]
        def rate(items):
            good=[o for o in items if o['status']=='success']
            return {'success':len(good),'total':len(items),'mentions':sum(int(reviews.get(o['id'],{}).get('mentioned',o['brand_mentioned'])) for o in good),
                    'dates':sorted({o['observed_at'][:10] for o in items})}
        a,b=rate(left),rate(right)
        delta=b['mentions']/b['success']-a['mentions']/a['success'] if a['success'] and b['success'] else None
        stratum=hashlib.sha256(json.dumps(k[:-2]).encode()).hexdigest()[:16]
        rows.append({'stratum':stratum,'question_id':k[-2],'question_version':k[-1],'question':left[0]['question']['text'],'platform':k[0],
                     'baseline':a,'retest':b,'mention_delta':delta})
        summary=summaries.setdefault(k[:-2],{'platform':k[0],'channel':k[1],'model':k[2],'mode':k[3],'environment':k[4],'language':k[5],'market':k[6],
            'identity':k[7],'protocol_version':k[8],'stratum':stratum,'deltas':[],'missing_questions':0})
        if delta is None:summary['missing_questions']+=1
        else:summary['deltas'].append(delta)
    for summary in summaries.values():
        ds=summary.pop('deltas');summary['questions']=len(ds)
        summary['mean_question_delta']=sum(ds)/len(ds) if ds and not summary['missing_questions'] else None
        summary['interval']=None
        if len(ds)>=2 and not summary['missing_questions']:
            # Resample whole question blocks, retaining their repeats and dates.
            rng=random.Random(0);samples=sorted(sum(rng.choice(ds) for _ in ds)/len(ds) for _ in range(2000))
            summary['interval']=[samples[49],samples[1949]]
        summary['method']='paired_question_cluster_bootstrap_95; cross-question date correlation not modeled; descriptive not causal'
    return {'comparable':True,'baseline':baseline,'retest':retest,'rows':rows,'summaries':list(summaries.values())}
