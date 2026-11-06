#!/usr/bin/env python3
"""Apply repeatable WordPress hardening with private, per-site rollback snapshots."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

ROOT_RULES = '''# BEGIN MVP SECURITY
<FilesMatch "(?i)^(xmlrpc\\.php|readme\\.html|wp-config\\.php(?:\\..*)?|debug\\.log|.*\\.(?:sql|bak|old|orig|swp))$">
Require all denied
</FilesMatch>
# END MVP SECURITY'''
UPLOAD_RULES = '''# BEGIN MVP SECURITY
Options -Indexes -ExecCGI
<FilesMatch "(?i)\\.(?:php[0-9]*|phtml|phar|phps|cgi|pl|py|sh)(?:[.;]|$)">
Require all denied
</FilesMatch>
# END MVP SECURITY'''
PHP = r'''
$p=json_decode(stream_get_contents(STDIN),true,512,JSON_THROW_ON_ERROR);
$root='/var/www/html';
$paths=['wp-config.php','.htaccess','wp-content/uploads/.htaccess','wp-content/mu-plugins/kf-security.php'];
foreach($paths as $rel){$f=$root.'/'.$rel;for($q=$f;$q!==$root;$q=dirname($q)){if(is_link($q)){throw new Exception('Refusing symlink');}}}
if($p['action']==='snapshot'){
 $out=[];foreach($paths as $rel){$f=$root.'/'.$rel;$out[$rel]=file_exists($f)?['data'=>base64_encode(file_get_contents($f)),'mode'=>fileperms($f)&0777,'uid'=>fileowner($f),'gid'=>filegroup($f)]:null;}
 echo json_encode($out);exit;
}
function put_file($f,$data,$mode,$uid=33,$gid=33){
 if(!is_dir(dirname($f))&&!mkdir(dirname($f),0755,true)){throw new Exception('mkdir failed');}
 $tmp=tempnam(dirname($f),'.kf-security-');
 if(file_put_contents($tmp,$data)===false||!chmod($tmp,$mode)||!chown($tmp,$uid)||!chgrp($tmp,$gid)||!rename($tmp,$f)){@unlink($tmp);throw new Exception('Atomic write failed');}
}
if($p['action']==='restore'){
 foreach($paths as $rel){$old=$p['snapshot'][$rel];$f=$root.'/'.$rel;if($old===null){if(file_exists($f)){unlink($f);}}else{put_file($f,base64_decode($old['data']),$old['mode'],$old['uid'],$old['gid']);}}
 echo 'RESTORED';exit;
}
function merge_rules($old,$new){return rtrim(preg_replace('/# BEGIN MVP SECURITY\R.*?# END MVP SECURITY\R?/s','',$old))."\n\n".$new."\n";}
$config=file_get_contents($root.'/wp-config.php');
$config=preg_replace('/\/\* BEGIN MVP SECURITY \*\/.*?\/\* END MVP SECURITY \*\/\s*/s','',$config);
// Put constants immediately after the PHP opening so default WordPress definitions cannot override them.
foreach(['DISALLOW_FILE_EDIT','WP_DEBUG_DISPLAY'] as $name){
 $config=preg_replace('/^[ \t]*define\s*\(\s*([\x27\x22])'. $name .'\1\s*,[^;]+;[ \t]*\R?/m','',$config);
}
$block="\n/* BEGIN MVP SECURITY */\ndefine('DISALLOW_FILE_EDIT', true);\ndefine('WP_DEBUG_DISPLAY', false);\n/* END MVP SECURITY */\n";
if(substr($config,0,5)!=='<?php'){throw new Exception('Unsupported wp-config format');}
$config=substr_replace($config,$block,5,0);
put_file($root.'/wp-config.php',$config,0600);
foreach(['.htaccess'=>'root_rules','wp-content/uploads/.htaccess'=>'upload_rules'] as $rel=>$key){$f=$root.'/'.$rel;put_file($f,merge_rules(file_exists($f)?file_get_contents($f):'',$p[$key]),0644);}
put_file($root.'/wp-content/mu-plugins/kf-security.php',$p['plugin'],0644);
echo 'HARDENED';
'''


def command(base, slug):
    container = f'kf-{slug}-web-1'
    state = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', container], text=True, capture_output=True, timeout=15)
    if state.returncode == 0 and state.stdout.strip() == 'true':
        return ['docker', 'exec', '-i', '--user', '0:0', container, 'php', '-r', PHP]
    return ['docker', 'run', '--rm', '-i', '--network', 'none', '--user', '0:0',
            '-v', str(base/'sites'/slug/'html')+':/var/www/html', '--entrypoint', 'php',
            'docker.m.daocloud.io/library/wordpress:php8.3-apache', '-r', PHP]


def apply(base, slug, restore=None):
    base = Path(base).resolve()
    if not re.fullmatch(r'[a-z][a-z0-9-]{1,19}', slug):
        raise ValueError('Invalid site slug')
    site = base / 'sites' / slug
    if not (site / 'html/wp-config.php').is_file():
        raise ValueError('WordPress is not initialized')
    cmd = command(base, slug)
    def call(payload):
        result = subprocess.run(cmd, input=json.dumps(payload), text=True, capture_output=True, timeout=45)
        if result.returncode:
            raise RuntimeError('WordPress hardening operation failed; inspect the installation (no secret output logged)')
        return result.stdout
    if restore is not None:
        saved = Path(restore).resolve()
        if not saved.is_relative_to((site/'.security-backups').resolve()):
            raise ValueError('Backup must belong to this site')
        snapshot = json.loads((saved/'files.json').read_text())
        if call({'action':'restore', 'snapshot':snapshot}) != 'RESTORED':
            raise RuntimeError('Restore failed')
        return {'site':slug, 'status':'restored'}
    # Snapshot contains wp-config, so keep it outside the web root, private even during creation.
    backup = site / '.security-backups' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    backup.mkdir(parents=True, mode=0o700)
    backup.parent.chmod(0o700)
    snapshot = json.loads(call({'action':'snapshot'}))
    with open(backup / 'files.json', 'x', opener=lambda p, f: os.open(p, f, 0o600)) as out:
        json.dump(snapshot, out)
    try:
        response = call({'action':'apply', 'root_rules':ROOT_RULES, 'upload_rules':UPLOAD_RULES,
                         'plugin':(base/'theme/kampong/wp-security.php').read_text()})
        if response != 'HARDENED':
            raise RuntimeError('Unexpected hardening result')
    except BaseException:
        call({'action':'restore', 'snapshot':snapshot})
        raise
    return {'site':slug, 'status':'hardened', 'backup':str(backup)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--slug', required=True)
    parser.add_argument('--restore', help='Restore a snapshot directory reported by a previous run')
    args = parser.parse_args()
    print(json.dumps(apply(args.base, args.slug, args.restore)))
