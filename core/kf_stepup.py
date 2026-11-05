"""Persistent TOTP throttling and single-use counters for action confirmations."""
import re
import time
from kf_ai import read_json,atomic_json
from kf_tool_runtime import ActionDenied
from kf_domain_vault import DomainVault

class StepUp(DomainVault):
    def verify(self,user,code,counter_for):
        with self.locked():
            path=self.root/'automation-auth.json';data=read_json(path,{})
            now=time.time();state=data.get(user,{'last_counter':-1,'failures':[],'blocked_until':0})
            if state['blocked_until']>now:raise ActionDenied('验证失败过多，请 5 分钟后再试')
            counter=counter_for(code) if isinstance(code,str) and re.fullmatch('[0-9]{6}',code) else None
            if counter is None or counter<=state['last_counter']:
                failures=[t for t in state['failures'] if t>now-300]+[now]
                state.update(failures=failures,blocked_until=now+300 if len(failures)>=5 else 0)
                data[user]=state;atomic_json(path,data);raise ActionDenied('TOTP 无效或已使用，请等待下一枚验证码；恢复码不可用于确认操作')
            state.update(last_counter=counter,failures=[],blocked_until=0);data[user]=state;atomic_json(path,data)
