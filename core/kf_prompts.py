"""Versioned prompt library. Business facts stay separate from reusable design guidance."""
import copy
import fcntl
import json
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from kf_ai import AIError, atomic_json, read_json, text

VARIABLES = {'audience': '目标客户', 'services': '主营服务/产品', 'goal': '主要转化目标',
             'tone': '品牌语气', 'facts': '已核实信息与联系方式'}
CATEGORIES = {'goal': '目标与转化', 'structure': '页面结构', 'style': '视觉方向',
              'copy': '内容表达', 'quality': '质量约束'}
SOURCES = [
    {'name': 'Vercel v0：产品界面、使用场景、约束与偏好', 'url': 'https://vercel.com/blog/how-to-prompt-v0'},
    {'name': 'Lovable：先规划、按组件组织、使用真实内容', 'url': 'https://docs.lovable.dev/prompting/prompting-one'},
    {'name': 'Anthropic：定义成功标准并验证效果', 'url': 'https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/overview'},
]
PLACEHOLDER = re.compile(r'\{\{\s*([a-z_]+)\s*\}\}')
_LOCK = threading.RLock()


class PromptConflict(AIError):
    pass


def defaults():
    modules = [
        ('conversion', '单一主要行动', 'goal', '围绕 {{goal}} 组织页面，每页只突出一个主要行动。首屏说明为 {{audience}} 解决什么问题、提供什么价值，CTA 描述实际下一步，不使用空泛“立即开始”。'),
        ('services', '服务介绍与流程', 'structure', '将 {{services}} 拆成便于扫描的服务卡片，使用真实服务名称。按了解服务、合作步骤、常见顾虑、联系行动组织内容；不添加未提供的服务。'),
        ('product', '产品价值与使用场景', 'structure', '围绕 {{services}} 展示用户问题、产品价值、关键场景及使用步骤。区分现有能力与规划，不编造集成、可用性承诺或付费方案。'),
        ('portfolio', '作品与案例叙事', 'structure', '优先展示 {{facts}} 中已有案例的背景、工作内容和可验证成果。没有真实案例时用服务方法替代，不捏造客户、项目名称或效果数据。'),
        ('booking', '预约咨询流程', 'goal', '主要行动为 {{goal}}。清楚说明咨询前需准备的信息和后续沟通步骤。只有在 {{facts}} 提供时才展示地址、营业时间、价格或可预约时段；表单只用于咨询，不声称已完成预约。'),
        ('catalog', '产品目录与询价', 'structure', '按 {{services}} 组织产品类别和差异，描述适用场景与选型依据。引导到咨询表单或真实联系方式；当前站点不是商城，不输出购物车、付款或库存承诺。'),
        ('minimal', '简洁可信', 'style', '内容短而明确，标题层级清晰，每区块表达一个重点，减少营销形容词。视觉方向保持简洁、留白和可扫描性；尊重既有站点主题，不要求模型输出 CSS 或任意 HTML。'),
        ('warm', '温暖亲和', 'style', '以 {{tone}} 的语气面向 {{audience}}，先回应顾虑再说明流程。避免夸大承诺、焦虑营销与未经证实的效果保证。视觉方向温暖、易读，沿用现有主题。'),
        ('copy', '真实且具体的文案', 'copy', '语气：{{tone}}。以 {{services}} 和已核实资料为依据写具体文案。标题表达收益，段落简短；不要编造价格、评价、资质、联系方式、统计或限时优惠。'),
        ('quality', '发布前内容检查', 'quality', '检查所有页面围绕 {{goal}} 服务 {{audience}}；区块之间不重复堆砌，按钮去向使用已存在页面；不把内部要求、占位符或“待补充”直接写入公开文案。资料不足时省略相关事实。仅生成平台支持的内容区块，遵守固定 JSON 输出约束。'),
        ('local', '本地服务信任', 'copy', '只有 {{facts}} 明确提供时才使用服务区域、地址和联系方式。通过服务边界和咨询步骤建立信任，不伪造地理覆盖、评分、执照或本地客户评价。'),
        ('education', '课程与学习路径', 'structure', '为 {{audience}} 解释 {{services}} 的适合人群、学习内容和咨询流程。只展示已提供的课程信息；不承诺成绩、升学、资格认证或学习效果。'),
        ('reference', '参考站结构与平台适配', 'structure', '只根据已提供的参考站观察整理信息层级、核心页面和行动路径；URL 本身不代表你已经浏览。提取结构规律，重新撰写文案，不逐字复制原站。使用已有页面 slug 和平台支持区块，不虚构二级菜单、视频轮播、支付或预约能力；照片、品牌色与字体作为后续媒体和视觉配置事项，不输出 HTML、CSS 或远程图片地址。'),
        ('demo-truth', '演示站事实与发布检查', 'quality', '依据 {{facts}} 区分真实业务与演示资料。未提供真实品牌资料时明确标注演示，不编造地址、电话、邮箱、费用、校区、团队、客户案例、资质和评价；测试表单不声称完成真实预约。删除行业模板遗留的示例事实。普通标题与文本字段不写 HTML 标签；表单成功只确认收到，不承诺未提供的回复时限。页面正文不得出现内部检查清单；发布前人工核对链接、图片、表单及移动端。'),
        ('robotics', '机器人方案与工程流程', 'structure', '围绕 {{services}} 面向 {{audience}} 说明应用场景、输入条件、方案范围、需求澄清、原型验证和交付流程。只描述已经核实的能力，不编造精度、吞吐量、节省比例、认证或客户名称。突出 {{goal}}，引导提供非机密的项目概况，不索要凭据或生产敏感数据。'),
        ('clinic-scope', '中医诊所信息与咨询边界', 'quality', '只根据 {{facts}} 介绍机构和 {{services}}，以清楚的服务说明和 {{goal}} 为主。没有真实机构资料时标明演示品牌；不编造医师身份、执业资格、地址、诊疗费用、患者评价、疗效或治愈率。不提供诊断、处方、剂量或治疗建议，不将普通留言表单描述为已确认医疗预约；演示咨询不索要真实症状、病历或证件。'),
        ('ui-principles', 'UI 基本原则与可访问性', 'quality', '围绕 {{audience}} 和 {{goal}} 建立清楚的信息层级：每页一个主标题，标题顺序合理，一个主要行动，按钮说明下一步；导航名称和位置跨页一致。正文简短、可扫描，不能把操作说明混入营销正文。实施检查标准：正文对比度至少 4.5:1，关键控件至少 44px，键盘可操作且焦点可见，表单有可见标签、错误和真实提交反馈；375/768/1024/1440px 无横向溢出，尊重减少动态效果偏好。这里只输出支持的 JSON 内容；字体、尺寸、对比度和交互由视觉预设与主题实现，生成文案本身不能证明已经通过 UI 检查。'),
        ('ui-aesthetics', 'UI 美学标准与视觉一致性', 'style', '为 {{services}} 选择一种统一的视觉方向。先安排首屏价值主张、核心服务、工作方式、行动入口，再考虑装饰。标题短而有辨识度，说明具体，不使用无依据的数字墙或评价填充版面。实施标准：限制主色和强调色，用语义色统一文字、背景、卡片与按钮；最多两类字体，以 8px 间距节奏、统一容器和有限圆角建立秩序；正文 16px 起、行高 1.5–1.8，短标题自然换行；图标风格统一，留白有层次，不堆叠渐变、玻璃效果、漂浮卡片或无意义动画。样式交给视觉预设，禁止在普通标题字段写 HTML/CSS。'),
        ('ui-nursery', '幼儿园视觉：温暖与探索', 'style', '面向家长，采用温暖、亲切、清楚的表达；以课程体验、教育理念和家长下一步为主线。视觉实施选择 nursery（童趣教育）：奶油底色、暖陶主色、低饱和辅助色，柔和圆角、原创学习主题插画和轻松留白；避免把成人阅读界面做成儿童游戏或用过多卡通装饰遮挡信息。'),
        ('ui-robotics', '机器人视觉：精密与秩序', 'style', '面向企业决策者，以任务、方案范围和工程流程组织内容。视觉实施选择 robotics（精密科技）：冷白与深海军蓝、清晰栅格、少量高对比强调色、几何设备插画和克制边框；避免泛化 AI 光效、没有依据的技术指标及装饰性数据。'),
        ('ui-wellness', '中医视觉：草木与静雅', 'style', '以清晰、平静、有分寸的文案介绍服务与咨询。视觉实施选择 wellness（草木静雅）：米白与深草木绿、少量赭色、标题衬线与清晰正文、草本插画和充足留白；避免刺眼营销、疗效暗示、虚构专家背书或用传统意象替代真实机构资料。'),
    ]
    rows = [{'id': mid, 'name': name, 'category': cat, 'description': name+'，可跨场景复用',
             'body': body, 'enabled': True, 'version': 1, 'updated_at': 0, 'history': []}
            for mid, name, cat, body in modules]
    templates = [
        ('company', '企业服务官网', '企业服务', '展示服务能力，引导客户咨询', ['conversion','services','minimal','copy','quality'], '需要专业服务的企业客户', '提交项目咨询', '专业、清晰、可信'),
        ('saas', 'SaaS 产品介绍', '数字产品', '说明产品价值与使用场景，获取演示咨询', ['conversion','product','minimal','copy','quality'], '评估数字产品的团队', '预约产品演示', '简洁、理性、易懂'),
        ('local-service', '本地服务预约', '本地生活', '服务介绍与预约咨询，不模拟预约系统', ['booking','services','local','warm','quality'], '本地有服务需求的客户', '提交预约咨询', '亲切、直接、可靠'),
        ('studio', '设计工作室与作品集', '创意设计', '突出方法、真实案例与合作方式', ['conversion','portfolio','minimal','copy','quality'], '寻找设计合作方的客户', '发起项目沟通', '克制、有辨识度、具体'),
        ('education', '教育与课程介绍', '教育培训', '解释课程与适合人群，引导课程咨询', ['conversion','education','warm','copy','quality'], '了解课程的学员与家长', '提交课程咨询', '耐心、清楚、温暖'),
        ('catalog', '产品目录与 B2B 询价', '产品展示', '清晰分类、产品对比与询价入口', ['conversion','catalog','minimal','copy','quality'], '筛选产品与供应商的采购方', '提交产品询价', '准确、务实、专业'),
        ('campaign', '活动推广落地页', '营销活动', '围绕一个行动组织活动介绍', ['conversion','services','warm','copy','quality'], '对活动主题感兴趣的访客', '提交活动咨询', '有活力、简洁、不夸大'),
        ('consulting', '专业咨询品牌', '专业咨询', '解释服务方法与合作流程，建立可信预期', ['booking','services','minimal','copy','quality'], '希望解决具体问题的客户', '预约初步沟通', '严谨、易懂、有分寸'),
        ('preschool-showcase', '幼儿园展示与参考站改编', '教育培训', '参考页面结构，呈现课程、理念与家长咨询', ['conversion','reference','education','warm','copy','demo-truth','quality'], '了解幼儿园理念与课程的家长', '了解课程并发起参观咨询', '温暖、具体、尊重儿童'),
        ('robotics-showcase', '机器人科技展示', '数字产品', '呈现应用场景、方案边界与工程合作流程', ['conversion','robotics','minimal','copy','demo-truth','quality'], '评估机器人与自动化方案的企业团队', '提交非机密项目概况', '理性、精确、清晰'),
        ('tcm-showcase', '中医诊所展示', '健康服务', '清晰介绍机构、服务范围与咨询流程', ['booking','services','minimal','copy','clinic-scope','demo-truth','quality'], '了解机构与咨询流程的访客', '了解服务并发起一般咨询', '沉稳、清楚、审慎'),
    ]
    ui_styles = {'preschool-showcase': 'ui-nursery', 'robotics-showcase': 'ui-robotics', 'tcm-showcase': 'ui-wellness'}
    ts = [{'id': tid, 'name': name, 'category': cat, 'description': desc,
           'body': '为此场景组织完整站点内容：'+desc+'。以客户真实资料为依据，服从现有页面与支持区块的限制。',
           'module_ids': mids + ['ui-principles', 'ui-aesthetics'] + ([ui_styles[tid]] if tid in ui_styles else []),
           'defaults': {'audience': audience, 'goal': goal, 'tone': tone},
           'enabled': True, 'version': 1, 'updated_at': 0, 'history': []}
          for tid,name,cat,desc,mids,audience,goal,tone in templates]
    return {'schema_version': 1, 'revision': 1, 'modules': rows, 'templates': ts}


def checked_ids(value, label):
    if not isinstance(value, list) or len(value)>12 or any(not isinstance(v,str) for v in value) or len(value)!=len(set(value)):
        raise AIError(label+' 必须是不重复、最多 12 项的列表')
    return value


def validate_body(body):
    value = text(body, '提示词内容', 2400, True)
    if set(PLACEHOLDER.findall(value))-set(VARIABLES):
        raise AIError('存在不支持的变量；可用变量：'+', '.join(VARIABLES))
    rest = PLACEHOLDER.sub('', value)
    if '{{' in rest or '}}' in rest:
        raise AIError('变量格式应为 {{services}} 等已支持的名称')
    return value


class PromptStore:
    def __init__(self, base):
        self.root = Path(base)/'console'
        self.path = self.root/'ai-prompts.json'

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True,exist_ok=True)
        with _LOCK, (self.root/'ai-prompts.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            yield

    def read(self):
        with self.locked():
            return read_json(self.path,defaults())

    def public(self, admin=False):
        data=self.read()
        data.update(variables=VARIABLES,categories=CATEGORIES,sources=SOURCES,can_manage=admin)
        if not admin:
            for kind in ('modules','templates'):
                data[kind]=[{k:v for k,v in item.items() if k!='history'} for item in data[kind] if item['enabled']]
        return data

    def writing_request(self, body):
        """Resolve the editable prompt's selected modules at a known library revision."""
        request = copy.deepcopy(body)
        meta, context = request.get('prompt'), request.get('context', {})
        if not isinstance(meta, dict) or not isinstance(context, dict):
            raise AIError('Invalid prompt writing context')
        kind = meta.get('kind')
        if kind not in ('modules', 'templates'):
            raise AIError('请选择模板或模块')
        library = self.read()
        if type(meta.get('revision')) is not int or meta['revision'] != library['revision']:
            raise PromptConflict('提示词库已更新，请刷新后重试；本次修改未写入')
        ids = checked_ids(meta.get('module_ids', []), '模块')
        if kind == 'modules' and ids:
            raise AIError('可复用模块不能包含其他模块')
        modules = {m['id']: m for m in library['modules']}
        if any(mid not in modules for mid in ids):
            raise AIError('模板引用了不存在的模块')
        try:
            values = json.loads(context.get('defaults', '{}'))
        except (ValueError, TypeError):
            raise AIError('默认变量必须是合法 JSON 对象')
        if not isinstance(values, dict) or set(values) - set(VARIABLES):
            raise AIError('默认变量不合法')
        values = {k: text(v, VARIABLES[k], 1500) for k, v in values.items()}
        context.update(prompt_kind=kind, defaults=json.dumps(values, ensure_ascii=False),
                       variables=json.dumps(VARIABLES, ensure_ascii=False),
                       modules=json.dumps([{k: modules[mid][k] for k in
                           ('id', 'name', 'category', 'body', 'version', 'enabled')} for mid in ids], ensure_ascii=False))
        request['context'] = context
        return request

    def change(self, body):
        with self.locked():
            data=read_json(self.path,defaults())
            if type(body.get('revision')) is not int or body['revision']!=data['revision']:
                raise PromptConflict('提示词库已更新，请刷新后重试；本次修改未写入')
            kind=body.get('kind')
            if kind not in ('modules','templates'):raise AIError('请选择模板或模块')
            item_id=text(body.get('id',''),'ID',40,True)
            if not re.fullmatch('[a-z][a-z0-9_-]{1,39}',item_id):raise AIError('ID 为 2–40 位小写字母、数字、短横线或下划线，字母开头')
            old=next((x for x in data[kind] if x['id']==item_id),None)
            action=body.get('action','save')
            if action=='delete':
                if not old:raise AIError('条目不存在')
                if kind=='modules':
                    refs=[t['name'] for t in data['templates'] if item_id in t['module_ids']]
                    if refs:raise AIError('模块仍被模板引用，请先调整或删除模板：'+'、'.join(refs))
                data[kind].remove(old)
                data['revision']+=1
                atomic_json(self.path,data)
                return {'id':item_id,'version':old['version'],'deleted':True}
            if action=='restore':
                if not old:raise AIError('条目不存在')
                prior=next((x for x in old['history'] if x['version']==body.get('version')),None)
                if not prior:raise AIError('历史版本不存在')
                item=copy.deepcopy(prior)
            elif action=='toggle':
                if not old:raise AIError('条目不存在')
                item=copy.deepcopy(old);item['enabled']=not item['enabled']
            elif action=='save':
                item={'id':item_id,'name':text(body.get('name',''),'名称',80,True),
                      'category':text(body.get('category',''),'分类',40,True),
                      'description':text(body.get('description',''),'用途说明',300),
                      'body':validate_body(body.get('body','')), 'enabled':body.get('enabled',True) is True}
                if kind=='templates':
                    item['module_ids']=checked_ids(body.get('module_ids',[]),'模块')
                    if item['enabled'] and not item['module_ids']:raise AIError('启用模板至少需要一个模块')
                    values=body.get('defaults',{})
                    if not isinstance(values,dict) or set(values)-set(VARIABLES):raise AIError('默认变量不合法')
                    item['defaults']={k:text(v,VARIABLES[k],1500) for k,v in values.items()}
                elif item['category'] not in CATEGORIES:raise AIError('模块分类不支持')
            else:raise AIError('不支持的管理操作')
            if kind=='templates':
                modules={m['id']:m for m in data['modules']}
                if any(mid not in modules or (item['enabled'] and not modules[mid]['enabled']) for mid in item['module_ids']):
                    raise AIError('模板引用了不存在或已停用的模块，请先调整组合')
            elif not item['enabled']:
                refs=[t['name'] for t in data['templates'] if t['enabled'] and item_id in t['module_ids']]
                if refs:raise AIError('模块被启用模板引用，请先调整或停用模板：'+'、'.join(refs))
            item.update(version=(old['version']+1 if old else 1),updated_at=int(time.time()))
            history=old.get('history',[]) if old else []
            item['history']=(history+[{k:v for k,v in old.items() if k!='history'}])[-10:] if old else []
            if old:data[kind][data[kind].index(old)]=item
            else:
                if len(data[kind])>=100:raise AIError('每类最多 100 条，请编辑或复用已有条目')
                data[kind].append(item)
            data['revision']+=1
            atomic_json(self.path,data)
            return item

    def compose(self, selection, brief=''):
        if not isinstance(selection,dict):raise AIError('提示词选择必须是对象')
        brief=text(brief,'补充要求',6000)
        data=self.read()
        if type(selection.get('revision')) is not int or selection['revision']!=data['revision']:
            raise PromptConflict('提示词库已更新，请重新选择或预览后生成')
        template=next((t for t in data['templates'] if t['id']==selection.get('template_id') and t['enabled']),None)
        if not template:raise AIError('模板不存在或已停用')
        mids=checked_ids(selection.get('module_ids',template['module_ids']),'模块组合')
        if not mids:raise AIError('至少选择一个模块')
        by_id={m['id']:m for m in data['modules'] if m['enabled']}
        if any(mid not in by_id for mid in mids):raise AIError('所选模块不存在或已停用')
        supplied=selection.get('variables',{})
        if not isinstance(supplied,dict) or set(supplied)-set(VARIABLES):raise AIError('业务变量不合法')
        values=dict(template['defaults'])
        values.update({k:text(v,VARIABLES[k],1500) for k,v in supplied.items()})
        for key in ('audience','services','goal'):
            if not values.get(key):raise AIError('请填写'+VARIABLES[key])
        values['tone']=values.get('tone') or '清晰、具体、可信'
        if not values.get('facts'):values['facts']='未提供；不得编造'
        parts=[template]+[by_id[mid] for mid in mids]
        def render(item):
            needed=set(PLACEHOLDER.findall(item['body']))
            if any(not values.get(k) for k in needed):raise AIError('请填写模块需要的变量')
            return PLACEHOLDER.sub(lambda m:values[m.group(1)],item['body'])
        instructions='\n\n'.join('【'+item['name']+'】\n'+render(item) for item in parts)
        if len(instructions)>20000:raise AIError('组合后的提示词过长，请减少模块或业务资料')
        context='\n'.join(VARIABLES[k]+'：'+v for k,v in values.items())
        if brief:context+='\n补充要求：'+text(brief,'补充要求',6000)
        return {'revision':data['revision'],'template':{'id':template['id'],'name':template['name'],'version':template['version']},
                'modules':[{'id':mid,'name':by_id[mid]['name'],'version':by_id[mid]['version']} for mid in mids],
                'variables':values,'instructions':instructions,'brief':context,
                'preview':instructions+'\n\n【业务资料】\n'+context}
