"""Shared single-attempt sender. Accepted by provider does not imply delivered."""
import json
import re
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage
from email.utils import make_msgid,getaddresses,formataddr
from kf_ai import AIError,NoRedirect,text


def address(value):
    value=text(value,'邮件地址',254,True)
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}',value):raise AIError('请填写单个有效邮件地址，不含显示名称或换行')
    return value


def message(body):
    to=address(body.get('to',''));subject=text(body.get('subject',''),'邮件主题',200,True)
    if '\r' in subject or '\n' in subject:raise AIError('邮件主题不能换行')
    content=text(body.get('body',''),'邮件正文',30000,True)
    return {'to':to,'subject':subject,'body':content}


def sender_info(smtp):
    return {k:smtp.get(k) for k in ('provider','host','port','tls','from','user') if smtp.get(k) is not None}


def send(to,subject,body,smtp,request_id=''):
    msgdata=message({'to':to,'subject':subject,'body':body})
    source=text(smtp.get('from') or smtp.get('user') or '', '发件人',320,True)
    if '\r' in source or '\n' in source:raise AIError('发件人不能包含换行')
    senders=getaddresses([source])
    if len(senders)!=1:raise AIError('请配置单个发件人')
    display,mailbox=senders[0];mailbox=address(mailbox);frm=formataddr((display,mailbox)) if display else mailbox
    provider=smtp.get('provider','smtp');receipt={'state':'accepted','provider':provider,'delivered':None}
    if provider=='ses':
        from kf_cloud_api import aws_call
        data=aws_call(smtp,'sesv2','send_email',FromEmailAddress=frm,Destination={'ToAddresses':[msgdata['to']]},
            Content={'Simple':{'Subject':{'Data':msgdata['subject'],'Charset':'UTF-8'},'Body':{'Text':{'Data':msgdata['body'],'Charset':'UTF-8'}}}})
        if not data.get('MessageId'):raise AIError('SES 未返回消息编号，请核实发送状态')
        return {**receipt,'provider_id':data['MessageId']}
    if provider in ('postmark','brevo','mailgun'):
        from kf_cloud_api import request,quote
        import base64
        key=smtp.get('api_key','')
        if not key:raise AIError('邮件 API 未配置')
        if provider=='postmark':
            data=request('https://api.postmarkapp.com/email','POST',{'From':frm,'To':msgdata['to'],'Subject':msgdata['subject'],'TextBody':msgdata['body']},{'X-Postmark-Server-Token':key})
            if data.get('ErrorCode',0):raise AIError('Postmark 拒绝发送，请核对发件人和权限')
            ident=data.get('MessageID')
        elif provider=='brevo':
            data=request('https://api.brevo.com/v3/smtp/email','POST',{'sender':{'email':mailbox,**({'name':display} if display else {})},'to':[{'email':msgdata['to']}],'subject':msgdata['subject'],'textContent':msgdata['body']},{'api-key':key})
            ident=data.get('messageId')
        else:
            host='api.eu.mailgun.net' if smtp.get('region')=='eu' else 'api.mailgun.net'
            data=request('https://'+host+'/v3/'+quote(smtp['domain'])+'/messages','POST',{'from':frm,'to':msgdata['to'],'subject':msgdata['subject'],'text':msgdata['body']},{'Authorization':'Basic '+base64.b64encode(('api:'+key).encode()).decode()},form=True)
            ident=data.get('id')
        if not ident:raise AIError('邮件服务未返回消息编号，请核实发送状态')
        return {**receipt,'provider_id':str(ident)[:200]}
    if provider in ('resend','sendgrid'):
        key=smtp.get('api_key','')
        if not key:raise AIError('邮件 API 未配置')
        if provider=='resend':
            url='https://api.resend.com/emails';payload={'from':frm,'to':[msgdata['to']],'subject':msgdata['subject'],'text':msgdata['body']}
        else:
            url='https://api.sendgrid.com/v3/mail/send';payload={'personalizations':[{'to':[{'email':msgdata['to']}]}],'from':{'email':mailbox,**({'name':display} if display else {})},'subject':msgdata['subject'],'content':[{'type':'text/plain','value':msgdata['body']}]}
        req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'},method='POST')
        # Never retry POST automatically: a timeout can occur after acceptance.
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=25) as response:
            if not 200<=response.status<300:raise AIError('邮件服务未接受请求')
            raw=response.read(65537)
            if len(raw)>65536:raise AIError('邮件服务响应过大，请核实发送状态')
            if provider=='resend':
                data=json.loads(raw) if raw else {};receipt['provider_id']=str(data.get('id',''))[:200]
            else:receipt['provider_id']=str(response.headers.get('X-Message-Id',''))[:200]
        return receipt
    if provider!='smtp':raise AIError('邮件服务商不支持')
    host=smtp.get('host','');port=int(smtp.get('port') or 587)
    if not host:raise AIError('SMTP 未配置')
    if port not in (465,587) or not smtp.get('tls',True):raise AIError('SMTP 必须使用 TLS 465 或 STARTTLS 587')
    msg=EmailMessage();msg['From']=frm;msg['To']=msgdata['to'];msg['Subject']=msgdata['subject']
    msg['Message-ID']=make_msgid();msg.set_content(msgdata['body'])
    conn=smtplib.SMTP_SSL(host,port,timeout=20,context=ssl.create_default_context()) if port==465 else smtplib.SMTP(host,port,timeout=20)
    try:
        if port!=465 and smtp.get('tls',True):conn.starttls(context=ssl.create_default_context())
        if smtp.get('user'):conn.login(smtp['user'],smtp.get('pass',''))
        refused=conn.send_message(msg)
        if refused:raise AIError('邮件收件人被拒绝')
        return {**receipt,'message_id':msg['Message-ID']}
    finally:
        try:conn.quit()
        except Exception:conn.close()


def delivery_status(receipt,smtp,recipient):
    """Provider evidence only; SMTP acceptance is never reported as final delivery."""
    import urllib.parse
    import urllib.error
    provider=receipt.get('provider','smtp');ident=receipt.get('provider_id','')
    if provider=='smtp':return {'state':'unknown','delivered':None,'message':'SMTP 没有通用投递查询接口，请凭 Message-ID 在邮件服务商后台或退信记录中核实','message_id':receipt.get('message_id','')}
    if provider in ('ses','postmark','brevo','mailgun'):
        return {'state':'unknown','delivered':None,'provider':provider,'provider_id':ident,'message':'已保存发送回执；此适配器尚未接入投递事件，请凭消息编号在服务商后台核实，勿重复发送'}
    if not ident or not re.fullmatch(r'[A-Za-z0-9._+=/-]{1,200}',ident):raise AIError('发送记录缺少可查询的服务商消息编号')
    if smtp.get('provider')!=provider or not smtp.get('api_key'):raise AIError('原邮件服务商凭据不可用，请在原服务商后台核实')
    if provider=='resend':url='https://api.resend.com/emails/'+urllib.parse.quote(ident,safe='')
    elif provider=='sendgrid':
        query='msg_id LIKE '+json.dumps(ident.replace('_','\\_')+'%')+' AND to_email='+json.dumps(address(recipient))
        url='https://api.sendgrid.com/v3/messages?'+urllib.parse.urlencode({'limit':10,'query':query})
    else:raise AIError('服务商不支持投递查询')
    req=urllib.request.Request(url,headers={'Authorization':'Bearer '+smtp['api_key']})
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=20) as response:
            raw=response.read(262145)
            if len(raw)>262144:raise AIError('投递查询响应过大')
            data=json.loads(raw)
    except urllib.error.HTTPError as exc:
        if exc.code in (401,403):return {'state':'unknown','delivered':None,'message':'服务商未授权投递查询；SendGrid 需启用 Email Activity API，Resend 需具备邮件读取权限'}
        if exc.code==404:return {'state':'unknown','delivered':None,'message':'服务商尚未找到此消息，或记录已超出保留期限'}
        raise AIError('投递查询失败，请稍后重试查询；不要重复发送') from None
    if provider=='resend':
        if data.get('id')!=ident:raise AIError('服务商返回的邮件编号不匹配')
        state=str(data.get('last_event','unknown'))[:80]
    else:
        matches=[v for v in data.get('messages',[]) if isinstance(v,dict) and str(v.get('msg_id','')).startswith(ident) and v.get('to_email','').lower()==recipient.lower()]
        if len(matches)!=1:return {'state':'unknown','delivered':None,'message':'尚未找到唯一匹配的投递记录，请稍后查询或在服务商后台核实'}
        state=str(matches[0].get('status','unknown'))[:80]
    delivered=True if state in ('delivered','opened','clicked') else False if state in ('bounced','failed','not_delivered','suppressed') else None
    return {'state':state,'delivered':delivered,'provider':provider,'provider_id':ident,
            'message':'服务商报告已投递至收件服务器' if delivered else '服务商报告投递失败' if delivered is False else '最终投递状态尚未确认'}
