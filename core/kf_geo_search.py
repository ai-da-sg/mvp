"""Official grounded-search adapters. No site facts, brand instructions or domain filters.

Provider-native search evidence is mandatory. Retrieved sources and answer citations
are distinct. Incomplete/no-search answers remain inspectable but are not successes.
"""
import json
import urllib.request
import urllib.error
from kf_ai import AIError, NoRedirect
from kf_geo import url, string

PROVIDERS = {'openai_search': ('OpenAI', 'https://api.openai.com/v1/responses'),
             'gemini_search': ('Gemini', 'https://generativelanguage.googleapis.com/v1beta/interactions')}


class SearchFailure(AIError):
    pass


def request(provider, config, question):
    if provider not in PROVIDERS:raise AIError('Unsupported GEO search provider')
    language = {'en':'English','zh':'Chinese'}[question['language']]
    # Brand name, facts, desired URLs and previous conversations never enter this request.
    prompt = 'Use web search to answer this question with citations. Answer in '+language+'. Target market: '+question['market']+'.\nQuestion: '+question['text']
    headers={'Content-Type':'application/json','Accept':'application/json'}
    if provider == 'openai_search':
        tool={'type':'web_search'}
        if len(question['market'])==2 and question['market'].isalpha():
            tool['user_location']={'type':'approximate','country':question['market'].upper()}
        body={'model':config['model'],'input':prompt,'tools':[tool], 'tool_choice':'required',
              'max_tool_calls':1,'max_output_tokens':int(config['max_tokens']),'store':False,
              'include':['web_search_call.action.sources']}
        headers['Authorization']='Bearer '+config['api_key']
    else:
        body={'model':config['model'],'input':prompt,'tools':[{'type':'google_search'}],
              'generation_config':{'max_output_tokens':int(config['max_tokens'])},'store':False}
        headers.update({'x-goog-api-key':config['api_key'],'Api-Revision':'2026-05-20'})
    req=urllib.request.Request(PROVIDERS[provider][1],data=json.dumps(body).encode(),headers=headers,method='POST')
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=120) as response:
            raw=response.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise SearchFailure('Search response exceeds 2 MB')
        result=json.loads(raw)
        if not isinstance(result,dict):raise ValueError()
        return result
    except urllib.error.HTTPError as exc:
        # Never expose response bodies or authentication headers, and never auto-replay paid requests.
        raise SearchFailure('Search API HTTP '+str(exc.code)+'; check model, search permissions and account quota') from None
    except (OSError,ValueError):
        raise SearchFailure('Search response unavailable or invalid; request may have been billed') from None


def parse(provider, data):
    if not isinstance(data,dict):raise SearchFailure('Invalid search response')
    parts=[]; annotations=[]; searches=[]; sources=[]; suggestions=[]
    def text_block(block, kind):
        if block.get('type')!=kind:return
        value=block.get('text','')
        if not isinstance(value,str):raise SearchFailure('Invalid answer text')
        offset=sum(len(p)+1 for p in parts)
        parts.append(value)
        for raw in block.get('annotations',[]):
            if not isinstance(raw,dict) or raw.get('type')!='url_citation':continue
            try:cited=url(raw.get('url',''))
            except AIError:continue
            start,end=raw.get('start_index'),raw.get('end_index')
            annotations.append({'url':cited,'title':str(raw.get('title',''))[:300],
                'start_index':offset+start if type(start) is int and 0<=start<=len(value) else None,
                'end_index':offset+end if type(end) is int and 0<=end<=len(value) else None})
    if provider=='openai_search':
        for step in data.get('output',[]):
            if not isinstance(step,dict):continue
            if step.get('type')=='web_search_call' and step.get('status')=='completed' and step.get('action',{}).get('type')=='search':
                searches.append(step)
                sources.extend(step.get('action',{}).get('sources',[]))
            if step.get('type')=='message' and step.get('role')=='assistant':
                for block in step.get('content',[]):text_block(block,'output_text')
    elif provider=='gemini_search':
        calls=[s for s in data.get('steps',[]) if isinstance(s,dict) and s.get('type')=='google_search_call']
        results=[s for s in data.get('steps',[]) if isinstance(s,dict) and s.get('type')=='google_search_result' and s.get('result')]
        if calls and results:searches=calls
        for step in data.get('steps',[]):
            if not isinstance(step,dict):continue
            if step.get('type')=='model_output':
                for block in step.get('content',[]):text_block(block,'text')
        for result in results:
            for item in result['result']:
                if isinstance(item,dict) and isinstance(item.get('search_suggestions'),str):suggestions.append(item['search_suggestions'])
    else:raise AIError('Unsupported GEO search provider')
    answer='\n'.join(parts)
    if len(answer)>24000:raise SearchFailure('Search answer too long to store completely')
    completed=data.get('status')=='completed'
    status='success' if completed and answer.strip() and searches else ('no_search' if completed and answer.strip() else 'failed')
    return {'status':status,'answer':answer,'citations':list(dict.fromkeys(a['url'] for a in annotations)),
            'annotations':annotations,'search_calls':searches,'retrieved_sources':sources,
            'search_suggestions':suggestions,'usage':data.get('usage',{}), 'response_id':str(data.get('id',''))[:200],
            'returned_model':str(data.get('model',''))[:120],
            'error':'' if status=='success' else 'No verified search execution' if status=='no_search' else 'Search answer incomplete or empty'}


def collect(provider, config, question, transport=request):
    raw=transport(provider,config,question)
    try:result=parse(provider,raw)
    except (AIError,TypeError,KeyError,AttributeError,ValueError):
        # Retain the bounded upstream response for diagnosis without promoting an
        # unsupported or truncated answer into a valid measurement.
        result={'status':'failed','answer':'','citations':[],'annotations':[],'search_calls':[],
                'retrieved_sources':[],'search_suggestions':[],'usage':{},'response_id':'','returned_model':'',
                'error':'Search response schema or answer size is unsupported; inspect the retained raw evidence'}
    return result,raw
