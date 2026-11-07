"""Opt-in WordPress recovery integration against an explicitly selected test site.

Changes the selected site's design/navigation temporarily, then restores its
original configuration. Run only against a disposable/test WordPress instance.
The normal unittest suite never imports or runs this script.
"""
import argparse,base64,json,sys,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'core'))
from kf_sections import wp
from kf_publication_wp import WordPressSnapshot
from kf_ai import AIError
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--site',required=True)
parser.add_argument('--allow-test-writes',action='store_true')
args=parser.parse_args()
if not args.allow_test_writes:parser.error('Use --allow-test-writes only for an authorized test site')
site=str(Path(args.site).resolve())
def evaluate(code):
 r=wp(site,'eval',code);assert r.returncode==0,r.stderr;return json.loads(r.stdout)
baseline_code="$m=new stdClass();$d=get_option('kf_design',$m);$k=get_option('kf_template_navigation_menus',$m);echo wp_json_encode(['locations'=>get_theme_mod('nav_menu_locations',[]),'has_locations'=>array_key_exists('nav_menu_locations',(array)get_theme_mods()),'design'=>$d===$m?null:$d,'has_design'=>$d!==$m,'managed'=>$k===$m?null:$k,'has_managed'=>$k!==$m]);"
original=evaluate(baseline_code)
owned=[]
owned_pages=[]
try:
 name='recovery-proof-'+uuid.uuid4().hex[:8]
 menu=evaluate("$m=wp_create_nav_menu('"+name+"');$a=wp_update_nav_menu_item($m,0,['menu-item-type'=>'custom','menu-item-title'=>\"Parent's link\",'menu-item-url'=>'https://example.test/parent','menu-item-status'=>'publish','menu-item-position'=>1]);wp_update_nav_menu_item($m,0,['menu-item-type'=>'custom','menu-item-title'=>'Child','menu-item-url'=>'https://example.test/child','menu-item-parent-id'=>$a,'menu-item-status'=>'publish','menu-item-position'=>2]);$l=get_theme_mod('nav_menu_locations',[]);$l['primary']=$m;$l['footer']=$m;set_theme_mod('nav_menu_locations',$l);update_option('kf_template_navigation_menus',[$m]);update_option('kf_design',['proof'=>'before']);echo wp_json_encode($m);")
 assert isinstance(menu,int);owned.append(menu)
 adapter=WordPressSnapshot(site,['home'],design=True,navigation=True);before=adapter.capture()
 assert len(before['navigation']['locations']['primary'])==2
 assert before['navigation']['locations']['primary'][1]['parent']==0
 evaluate("wp_delete_nav_menu("+str(menu)+");update_option('kf_design',['proof'=>'after']);$l=get_theme_mod('nav_menu_locations',[]);unset($l['primary'],$l['footer']);set_theme_mod('nav_menu_locations',$l);update_option('kf_template_navigation_menus',[]);echo 'true';")
 after=adapter.capture()
 try:adapter.restore(before,after,{})

 finally:owned+=evaluate("$l=get_theme_mod('nav_menu_locations',[]);echo wp_json_encode(array_values(array_intersect_key($l,array_flip(['primary','footer']))));")
 assert adapter.capture()==before
 # Exercise the actual deletion/recovery adapter on a page created only for this test.
 page_slug='delete-proof-'+uuid.uuid4().hex[:8]
 pid=evaluate("$id=wp_insert_post(['post_type'=>'page','post_status'=>'publish','post_name'=>'"+page_slug+"','post_title'=>'Deletion proof','post_content'=>'Test-only page']);echo wp_json_encode($id);")
 assert isinstance(pid,int) and pid>0;owned_pages.append(pid)
 evaluate("$l=get_theme_mod('nav_menu_locations',[]);$m=$l['primary'];$p=wp_update_nav_menu_item($m,0,['menu-item-type'=>'post_type','menu-item-object'=>'page','menu-item-object-id'=>"+str(pid)+",'menu-item-title'=>'Deletion proof','menu-item-status'=>'publish']);$p2=wp_update_nav_menu_item($m,0,['menu-item-type'=>'post_type','menu-item-object'=>'page','menu-item-object-id'=>"+str(pid)+",'menu-item-title'=>'Nested deletion proof','menu-item-parent-id'=>$p,'menu-item-status'=>'publish']);wp_update_nav_menu_item($m,0,['menu-item-type'=>'custom','menu-item-title'=>'Retained child','menu-item-url'=>'https://example.test/kept','menu-item-parent-id'=>$p2,'menu-item-status'=>'publish']);echo 'true';")
 deleting=WordPressSnapshot(site,[page_slug],navigation=True);delete_before=deleting.capture()
 assert delete_before['pages'][page_slug]['status']=='publish'
 deleting.remove_page(delete_before);delete_after=deleting.capture()
 assert delete_after['pages'][page_slug]['status']=='draft'
 rows=delete_after['navigation']['locations']['primary']
 assert not any(row['object_id']==pid for row in rows)
 assert next(row for row in rows if row['title']=='Retained child')['parent'] is None
 try:deleting.remove_page(delete_before)
 except AIError:pass
 else:raise AssertionError('Stale deletion snapshot was accepted')
 try:deleting.restore(delete_before,delete_after,{})
 finally:owned+=evaluate("$l=get_theme_mod('nav_menu_locations',[]);echo wp_json_encode(array_values(array_intersect_key($l,array_flip(['primary','footer']))));")
 assert deleting.capture()==delete_before
finally:
 payload=base64.b64encode(json.dumps(original).encode()).decode()
 evaluate("$s=json_decode(base64_decode('"+payload+"'),true);if($s['has_locations'])set_theme_mod('nav_menu_locations',$s['locations']);else remove_theme_mod('nav_menu_locations');if($s['has_design'])update_option('kf_design',$s['design']);else delete_option('kf_design');if($s['has_managed'])update_option('kf_template_navigation_menus',$s['managed']);else delete_option('kf_template_navigation_menus');echo 'true';")
 for ident in owned_pages:
  evaluate('wp_delete_post('+str(ident)+',true);echo "true";')
 for ident in set(owned):
  if isinstance(ident,int):evaluate('wp_delete_nav_menu('+str(ident)+');echo "true";')

assert evaluate(baseline_code)==original, 'Original test-site configuration was not fully restored'
print(json.dumps({'design_and_deleted_nested_navigation_restore':'passed','original_configuration_readback':'passed','page_delete_nested_navigation_and_recovery':'passed'}),flush=True)
