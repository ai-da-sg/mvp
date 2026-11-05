#!/usr/bin/env python3
"""Enroll an existing site without replacing its theme or sharing user passwords."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from kf_sso import SSOStore
from kf_ai import AIError


def install(base,slug,console_url,site_url):
    base=Path(base);site=base/'sites'/slug
    if not (site/'meta.json').is_file() or not (site/'wp.env').is_file(): raise AIError('站点不存在或尚未开通')
    cfg=SSOStore(base).configure(console_url,slug,site_url)
    payload={'slug':slug,'console_url':console_url.rstrip('/'),'site_url':site_url.rstrip('/'),'secret':cfg['secret']}
    # The secret travels on stdin, never in argv, logs, handover documents or web files.
    code="""$c=json_decode(stream_get_contents(STDIN),true);
if(!is_array($c)||empty($c['secret'])){throw new Exception('invalid config');}
$dir=WP_CONTENT_DIR.'/mu-plugins';
if(!is_dir($dir)&&!mkdir($dir,0755,true)){throw new Exception('mkdir failed');}
update_option('kf_mvp_sso',$c,false);
update_option('users_can_register',0);
if(!copy('/kf-sso/mvp-sso.php',$dir.'/kf-mvp-sso.php')){throw new Exception('install failed');}
foreach(get_users(['fields'=>'ID']) as $id){WP_Session_Tokens::get_instance($id)->destroy_all();}
echo 'MVP_SSO_INSTALLED';"""
    cmd=['docker','run','--rm','-i','--env-file',str(site/'wp.env'),'--network',f'kf-{slug}_default',
         '-v',f'{site.resolve()}/html:/var/www/html','-v',f'{base.resolve()}/theme/kampong:/kf-sso:ro',
         '--user','33:33','docker.m.daocloud.io/library/wordpress:cli-php8.3','wp','eval',code]
    result=subprocess.run(cmd,input=json.dumps(payload),capture_output=True,text=True,timeout=180)
    if result.returncode or 'MVP_SSO_INSTALLED' not in result.stdout: raise AIError('WordPress 统一登录插件安装失败；请检查容器和文件权限')
    # Remove obsolete local-password instructions from future handover exports.
    handover=site/'handover.md'
    if handover.exists():
        text=handover.read_text();lines=text.splitlines()
        lines=[line for line in lines if not (line.startswith('- 账号：') or line.startswith('- 密码：'))]
        text='\n'.join(lines)+'\n\n## 统一管理入口\n- '+console_url+'\n- 通过 MVP 站点列表进入 WordPress；独立密码登录已关闭。\n'
        handover.write_text(text)
    return {'slug':slug,'url':site_url,'console':console_url,'installed':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',required=True);parser.add_argument('--slug',required=True)
    parser.add_argument('--console-url',required=True);parser.add_argument('--site-url',required=True)
    args=parser.parse_args()
    try: print(json.dumps(install(args.base,args.slug,args.console_url,args.site_url)))
    except (AIError,subprocess.TimeoutExpired) as exc: raise SystemExit(str(exc))
