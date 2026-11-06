"""Template browsing metadata, complete demo sites and original local artwork."""
import copy
import html
import re
from kf_ai import AIError, text
from kf_style_presets import SECTOR_SAMPLES

BLOCKS = ('hero','cards','split','stats','cta','band','gallery','quotes','table','list','rich','form')
SITE_TYPES = {
    'business': ('企业官网','Business website'),
    'portfolio': ('作品展示','Portfolio'),
    'catalog': ('产品展示','Product catalog'),
    'landing': ('单页推广','Landing page'),
    'events': ('活动介绍','Event website'),
    'education': ('课程介绍','Education website'),
}
TYPE_SECTORS = {'creative':'portfolio','photography':'portfolio','architecture':'portfolio',
    'fashion':'catalog','beauty':'catalog','food':'catalog','automotive':'catalog','industrial':'catalog',
    'events':'events','culture':'events','education':'education','technology':'landing'}


def normalize_experience(body, blueprint, sector):
    kinds = body.get('site_types', [TYPE_SECTORS.get(sector,'business')])
    if not isinstance(kinds,list) or not 1 <= len(kinds) <= len(SITE_TYPES) or any(not isinstance(k,str) or k not in SITE_TYPES for k in kinds):
        raise AIError('模板用途无效')
    kinds = list(dict.fromkeys(kinds))
    default = [{'slug':'home','title':'Home','blueprint':blueprint or ['hero','cards','split','cta']}]
    if 'landing' not in kinds or len(kinds)>1:
        default += [{'slug':'about','title':'About','blueprint':['hero','split','rich','cta']},
                    {'slug':'services','title':'Explore','blueprint':['hero','cards','table','list','cta']},
                    {'slug':'contact','title':'Contact','blueprint':['hero','list','form']}]
    pages = body.get('pages', default)
    if not isinstance(pages,list) or not 1 <= len(pages) <= 8:
        raise AIError('模板需要 1–8 个页面')
    clean=[];seen=set()
    for page in pages:
        if not isinstance(page,dict): raise AIError('模板页面格式无效')
        slug=page.get('slug')
        if not isinstance(slug,str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,19}',slug) or slug in seen:
            raise AIError('模板页面标识无效或重复')
        seen.add(slug)
        blocks=blueprint if slug=='home' and blueprint else page.get('blueprint',[])
        if not isinstance(blocks,list) or not 1<=len(blocks)<=20 or any(not isinstance(v,str) or v not in BLOCKS for v in blocks):
            raise AIError('模板页面需要 1–20 个受支持的区块')
        clean.append(dict(slug=slug,title=text(page.get('title'), '页面标题',80,True),blueprint=list(blocks)))
    if clean[0]['slug']!='home': raise AIError('模板的第一个页面必须是 home')
    return dict(site_types=kinds,pages=clean)


def sample_sections(item,page,company=None):
    """Explicit demo copy, structured for the same editor/publisher as real sites."""
    name=company or item.get('name','Your brand')
    theme=SECTOR_SAMPLES.get(item.get('sector'),dict(headline='Make room for your next chapter',offerings=['Our work','Our approach','Get in touch']))
    labels=theme['offerings'];headline=theme['headline']
    title=name if page['slug']=='home' else page['title']
    samples={
        'hero':dict(kicker='LOCAL DESIGN / SAMPLE CONTENT',title=title,text=headline,art=True,cta=dict(label='Get in touch',href='/contact/')),
        'cards':dict(title=headline,items=[dict(title=t,text='Add your verified description here. Explain what visitors can expect and how to take the next step.') for t in labels]),
        'split':dict(title=labels[1],text='A thoughtful approach starts with understanding your needs. Replace this sample story with the people, process and details behind your business.',items=labels),
        'stats':dict(items=[dict(value='—',label='Add verified metrics'),dict(value='—',label='Include a source and date')]),
        'cta':dict(title='Let’s start a conversation',text='Tell us what you have in mind. Replace this sample with your preferred contact details.',button='Get in touch',href='/contact/'),
        'band':dict(src='/template-sample-1.png',alt='Original local illustration',caption='Illustration · Sample content'),
        'gallery':dict(title=labels[0],items=[dict(src='/template-sample-%d.png'%i,label='Sample composition %d'%i) for i in range(1,4)]),
        'quotes':dict(title='Client perspectives',items=[dict(text='Add an approved customer testimonial here before publishing.',by='Sample placeholder')]),
        'table':dict(title='The details, at a glance',headers=['Offering','Details'],rows=[[t,'Add verified details'] for t in labels]),
        'list':dict(title='Your next steps',items=['Explore the available options','Share your requirements','Confirm the details together']),
        'rich':dict(html='<h2>Behind '+html.escape(name)+'</h2><p>Replace this sample passage with your own story, values and practical information. Keep the copy concise and factual.</p>'),
        'form':dict(title='Send an enquiry',lead='Use the form to share your question.',submit='Send enquiry'),
    }
    if page['slug']=='contact':
        samples['hero'].update(text='We would love to hear from you.',art=False)
        samples['list'].update(title='Before you send',items=['Add your contact email and opening hours','Include your location or service area','Review the privacy information'])
    return [dict(copy.deepcopy(samples[k]),type=k) for k in page['blueprint']]


def artwork(tokens,sector,index=1):
    """Original SVG editorial illustrations, no remote assets or trademarked artwork."""
    p=tokens['palette'];bg=p['bg'];primary=p['primary'];accent=p['accent'];surface=p['surface']
    # The palette is normalized by the caller; interpolate no free-form user text.
    art=[]
    if sector in ('architecture','real-estate','hospitality','industrial'):
        art=[f'<rect x="120" y="150" width="550" height="360" fill="{primary}"/>',
             f'<path d="M120 150 390 40 670 150Z" fill="{accent}"/>']
        art += [f'<rect x="{160+x*150}" y="{210+y*130}" width="95" height="85" rx="{45 if sector=="hospitality" else 0}" fill="{surface}"/>' for y in range(2) for x in range(3)]
        art += [f'<path d="M0 560 Q250 450 800 550V600H0Z" fill="{accent}"/>']
    elif sector in ('food','restaurant'):
        art=[f'<ellipse cx="400" cy="330" rx="280" ry="200" fill="{surface}"/>',f'<ellipse cx="400" cy="330" rx="210" ry="140" fill="{accent}"/>']
        art += [f'<ellipse cx="{250+i*80}" cy="{280+(i%2)*90}" rx="55" ry="35" transform="rotate({i*27} {250+i*80} {280+(i%2)*90})" fill="{primary}"/>' for i in range(5)]
        art += [f'<path d="M60 130V500M740 130V500" stroke="{primary}" stroke-width="12"/>']
    elif sector in ('wellness','sustainability','beauty'):
        art=[f'<path d="M180 600 Q450 320 430 80" fill="none" stroke="{primary}" stroke-width="14"/>']
        art += [f'<ellipse cx="{390-(i%2)*140}" cy="{120+i*80}" rx="100" ry="38" transform="rotate({-35 if i%2 else 30} {390-(i%2)*140} {120+i*80})" fill="{primary if i%2 else accent}"/>' for i in range(5)]
        art += [f'<rect x="530" y="290" width="140" height="230" rx="45" fill="{surface}"/><rect x="560" y="250" width="80" height="55" rx="12" fill="{accent}"/>']
    elif sector in ('technology','finance','healthcare'):
        art=[f'<rect x="200" y="70" width="400" height="470" rx="45" fill="{primary}"/><rect x="225" y="110" width="350" height="360" rx="20" fill="{surface}"/>',
             f'<path d="M260 390 330 280 390 340 450 200 540 240" fill="none" stroke="{accent}" stroke-width="22"/>',f'<circle cx="400" cy="505" r="15" fill="{surface}"/>']
    elif sector in ('sports','automotive'):
        art=[f'<path d="M0 480 800 120M0 560 800 200" stroke="{accent}" stroke-width="42"/>',
             f'<circle cx="300" cy="340" r="135" fill="{primary}"/><circle cx="520" cy="260" r="110" fill="{surface}"/>',
             f'<path d="M200 280 610 400" stroke="{accent}" stroke-width="18"/>']
    elif sector in ('fashion','photography','creative'):
        art=[f'<rect x="110" y="85" width="270" height="420" rx="8" fill="{primary}"/>',
             f'<path d="M450 100 650 170 710 500 410 500Z" fill="{accent}"/>',
             f'<circle cx="245" cy="240" r="95" fill="{surface}"/><path d="M160 480 245 300 335 480Z" fill="{bg}"/>']
    else:
        art=[f'<circle cx="580" cy="160" r="90" fill="{accent}"/>',f'<path d="M0 500 280 210 520 500Z" fill="{primary}"/>',f'<path d="M300 600 610 250 800 600Z" fill="{accent}"/>',f'<path d="M0 550 Q300 400 800 550V600H0Z" fill="{surface}"/>']
    transform='translate(800 0) scale(-1 1)' if index==2 else ('translate(40 30) scale(.9)' if index==3 else '')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="600" viewBox="0 0 800 600"><rect width="800" height="600" fill="{bg}"/><g transform="{transform}">'+''.join(art)+'</g></svg>'
