"""Scoped WordPress snapshots; no database-wide rollback or credential capture."""
import base64
import json
import re
import subprocess

from kf_ai import AIError


PHP_CAPTURE = r'''
function kf_pub_capture($scope) {
    $state=['pages'=>[]];
    foreach($scope['pages'] as $slug) {
        $post=get_page_by_path($slug,OBJECT,['page']);
        $state['pages'][$slug]=$post ? ['id'=>(int)$post->ID,'slug'=>$post->post_name,
            'title'=>$post->post_title,'content'=>$post->post_content,'status'=>$post->post_status] : null;
    }
    if($scope['design']) {
        $missing=new stdClass();$value=get_option('kf_design',$missing);
        $state['design']=['exists'=>$value!==$missing,'value'=>$value===$missing?null:$value];
    }
    if($scope['navigation']) {
        $locations=get_theme_mod('nav_menu_locations',[]);
        $missing=new stdClass();$saved=get_option('kf_template_navigation_menus',$missing);
        $managed=$saved===$missing?[]:array_map('intval',(array)$saved);
        $state['navigation']=['managed'=>[],'locations'=>[], 'managed_exists'=>$saved!==$missing,
            'locations_present'=>array_key_exists('nav_menu_locations',(array)get_theme_mods()),
            'shared_menu'=>!empty($locations['primary']) && (int)$locations['primary']===(int)($locations['footer']??0)];
        foreach(['primary','footer'] as $location) {
            $id=(int)($locations[$location]??0);
            if(!$id) {$state['navigation']['locations'][$location]=null;continue;}
            if(!wp_get_nav_menu_object($id)) throw new Exception('Navigation menu is missing');
            if(in_array($id,$managed,true)) $state['navigation']['managed'][]=$location;
            $items=wp_get_nav_menu_items($id,['post_status'=>'any']);
            if($items===false) throw new Exception('Cannot read navigation');
            $indexes=[];foreach($items as $index=>$item) $indexes[(int)$item->ID]=$index;
            $rows=[];
            foreach($items as $item) {
                $parent=(int)$item->menu_item_parent;
                if($parent && !array_key_exists($parent,$indexes)) throw new Exception('Navigation parent is missing');
                $rows[]=['parent'=>$parent?$indexes[$parent]:null,'object_id'=>$item->type==='custom'?0:(int)$item->object_id,
                    'object'=>$item->object,'type'=>$item->type,'title'=>$item->title,
                    'url'=>$item->type==='custom'?$item->url:'','target'=>$item->target,
                    'attr_title'=>$item->attr_title,'description'=>$item->description,
                    'classes'=>array_values((array)$item->classes),'xfn'=>$item->xfn,'status'=>$item->post_status];
            }
            // WordPress allocates new IDs when recreating deleted generated menus.
            // Compare semantic navigation, not temporary menu IDs or names.
            $state['navigation']['locations'][$location]=$rows;
        }
    }
    return $state;
}
'''


PHP_RESTORE = r'''
$current=kf_pub_capture($scope);
if($current!=$payload['expected']) throw new Exception('Site changed before recovery');
$before=$payload['before'];
// Validate all page ownership before the first write. New pages may only be
// deleted when the publishing renderer explicitly returned their created IDs.
foreach($scope['pages'] as $slug) {
    $old=$before['pages'][$slug];$now=$current['pages'][$slug];
    if($old && (!$now || $old['id']!==$now['id'])) throw new Exception('Original page identity changed');
    if(!$old && $now && (int)($payload['created_ids'][$slug]??0)!==$now['id'])
        throw new Exception('Cannot establish ownership of a new page');
}
foreach($scope['pages'] as $slug) {
    $old=$before['pages'][$slug];$now=$current['pages'][$slug];
    if(!$old) {
        if($now && !wp_delete_post($now['id'],true)) throw new Exception('Cannot remove generated page');
        continue;
    }
    $updated=wp_update_post(wp_slash(['ID'=>$old['id'],'post_title'=>$old['title'],
        'post_content'=>$old['content'],'post_status'=>$old['status']]),true);
    if(is_wp_error($updated) || !$updated) throw new Exception('Cannot restore page');
}
if($scope['design']) {
    if($before['design']['exists']) update_option('kf_design',$before['design']['value']);
    else delete_option('kf_design');
}
if($scope['navigation']) {
    $locations=get_theme_mod('nav_menu_locations',[]);$managed=[];$created=[];
    $previous_locations=$locations;$missing=new stdClass();
    $previous_managed=get_option('kf_template_navigation_menus',$missing);
    try {
        foreach(['primary','footer'] as $location) {
            $rows=$before['navigation']['locations'][$location];
            if($rows===null) {unset($locations[$location]);continue;}
            if($location==='footer' && $before['navigation']['shared_menu']) {
                $locations['footer']=$locations['primary'];
                if(in_array($location,$before['navigation']['managed'],true)) $managed[]=$locations['footer'];
                continue;
            }
            $menu=wp_create_nav_menu('Recovered '.$location.' '.wp_generate_uuid4());
            if(is_wp_error($menu)) throw new Exception('Cannot create recovery navigation');
            $created[]=$menu;$ids=[];
            foreach($rows as $index=>$row) {
                $data=['menu-item-object-id'=>$row['object_id'],'menu-item-object'=>$row['object'],
                    'menu-item-type'=>$row['type'],'menu-item-title'=>$row['title'],
                    'menu-item-url'=>$row['url'],'menu-item-target'=>$row['target'],
                    'menu-item-attr-title'=>$row['attr_title'],'menu-item-description'=>$row['description'],
                    'menu-item-classes'=>implode(' ',$row['classes']),'menu-item-xfn'=>$row['xfn'],
                    'menu-item-position'=>$index+1,'menu-item-status'=>$row['status']];
                $id=wp_update_nav_menu_item($menu,0,wp_slash($data));
                if(is_wp_error($id) || !$id) throw new Exception('Cannot restore navigation item');
                $ids[]=$id;
            }
            foreach($rows as $index=>$row) {
                if($row['parent']!==null) {
                    if(!isset($ids[$row['parent']])) throw new Exception('Invalid navigation hierarchy');
                    update_post_meta($ids[$index],'_menu_item_menu_item_parent',$ids[$row['parent']]);
                }
            }
            $locations[$location]=$menu;
            if(in_array($location,$before['navigation']['managed'],true)) $managed[]=$menu;
        }
        if($before['navigation']['locations_present'] || $locations) set_theme_mod('nav_menu_locations',$locations);
        else remove_theme_mod('nav_menu_locations');
        if($before['navigation']['managed_exists']) update_option('kf_template_navigation_menus',array_values(array_unique($managed)));
        else delete_option('kf_template_navigation_menus');
    } catch(Throwable $e) {
        set_theme_mod('nav_menu_locations',$previous_locations);
        if($previous_managed===$missing) delete_option('kf_template_navigation_menus');
        else update_option('kf_template_navigation_menus',$previous_managed);
        foreach($created as $menu) wp_delete_nav_menu($menu);
        throw $e;
    }
}
$restored=kf_pub_capture($scope);
if($restored!=$before) throw new Exception('Recovery verification failed');
echo wp_json_encode($restored);
'''


class WordPressSnapshot:
    def __init__(self, site, pages, *, design=False, navigation=False, runner=None):
        if (not isinstance(pages, list) or not pages or len(pages) > 100
                or any(not isinstance(s, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', s) for s in pages)
                or len(set(pages)) != len(pages)):
            raise AIError('发布页面列表无效')
        self.site = str(site)
        self.scope = {'pages': list(pages), 'design': bool(design), 'navigation': bool(navigation)}
        if runner is None:
            from kf_sections import wp
            runner = wp
        self.runner = runner

    def _run(self, body, payload=None):
        data = base64.b64encode(json.dumps({'scope': self.scope, 'payload': payload},
                                         ensure_ascii=False, allow_nan=False).encode()).decode()
        code = ('<?php\n' + PHP_CAPTURE + '\n$input=json_decode(base64_decode("' + data
                + '"),true,512,JSON_THROW_ON_ERROR);$scope=$input["scope"];$payload=$input["payload"];\n'
                + 'try {\n' + body + '\n} catch(Throwable $e) {WP_CLI::error($e->getMessage());}\n')
        try:
            result = self.runner(self.site, 'eval-file', '-', stdin=code)
            if result.returncode != 0:
                raise AIError('WordPress 快照或恢复失败，请检查站点后重试')
            state = json.loads(result.stdout.strip())
        except AIError:
            raise
        except (ValueError, OSError, TimeoutError, subprocess.TimeoutExpired):
            raise AIError('无法读取 WordPress 快照，请检查站点连接') from None
        if not isinstance(state, dict) or set(state.get('pages', {})) != set(self.scope['pages']):
            raise AIError('WordPress 快照格式无效')
        return state

    def capture(self):
        return self._run('echo wp_json_encode(kf_pub_capture($scope));')

    def restore(self, before, expected, created_ids):
        return self._run(PHP_RESTORE, {'before': before, 'expected': expected, 'created_ids': created_ids})

    def remove_page(self, expected):
        """Unpublish one managed page, retaining its identity for snapshot recovery."""
        if len(self.scope['pages']) != 1 or not self.scope['navigation']:
            raise AIError('Page deletion requires a single page and navigation snapshot')
        return self._run(r'''
$current=kf_pub_capture($scope);
if($current!=$payload['expected']) throw new Exception('Site changed before deletion');
$slug=$scope['pages'][0];$post=get_page_by_path($slug,OBJECT,['page']);
if(!$post) throw new Exception('Page no longer exists');
$id=(int)$post->ID;
if($id===(int)get_option('page_on_front') || $id===(int)get_option('page_for_posts'))
    throw new Exception('The front page and posts page are protected');
if(get_posts(['post_type'=>'page','post_parent'=>$id,'post_status'=>'any','numberposts'=>1]))
    throw new Exception('Page has child pages');
$locations=get_theme_mod('nav_menu_locations',[]);
$managed=array_unique(array_filter([(int)($locations['primary']??0),(int)($locations['footer']??0)]));
$url=wp_parse_url(get_permalink($id));$remove=[];
foreach(wp_get_nav_menus() as $menu) {
    $items=wp_get_nav_menu_items($menu->term_id,['post_status'=>'any']);
    foreach((array)$items as $item) {
        $link=wp_parse_url($item->url);
        $same_url=untrailingslashit(rawurldecode($link['path']??''))===untrailingslashit(rawurldecode($url['path']??''))
            && (empty($link['host']) || strtolower($link['host'])===strtolower($url['host']??''));
        $matches=($item->type==='post_type' && $item->object==='page' && (int)$item->object_id===$id)
            || ($item->type==='custom' && $same_url);
        if(!$matches) continue;
        if(!in_array((int)$menu->term_id,$managed,true)) throw new Exception('Page is linked from an unmanaged menu');
        $remove[]=$item;
    }
}
$updated=wp_update_post(['ID'=>$id,'post_status'=>'draft'],true);
if(is_wp_error($updated)||!$updated) throw new Exception('Could not unpublish page');
$parents=[];foreach($remove as $item) $parents[(int)$item->ID]=(int)$item->menu_item_parent;
foreach($managed as $menu) foreach((array)wp_get_nav_menu_items($menu,['post_status'=>'any']) as $child) {
    $parent=(int)$child->menu_item_parent;$seen=[];
    while(isset($parents[$parent])) {
        if(isset($seen[$parent])) throw new Exception('Navigation contains a cycle');
        $seen[$parent]=true;$parent=$parents[$parent];
    }
    if($parent!==(int)$child->menu_item_parent) update_post_meta($child->ID,'_menu_item_menu_item_parent',$parent);
}
foreach($remove as $item) if(!wp_delete_post($item->ID,true)) throw new Exception('Could not remove navigation link');
$after=kf_pub_capture($scope);
if(($after['pages'][$slug]['status']??'')!=='draft') throw new Exception('Deletion verification failed');
echo wp_json_encode($after);
''', {'expected': expected})
