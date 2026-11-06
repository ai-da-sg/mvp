<?php
/** Scoped reference design support for existing Kampong theme installations. */
function kf_reference_active() {
    $design = get_option('kf_design', []);
    if (is_string($design)) { $design = json_decode($design, true); }
    return is_array($design) && ($design['preset'] ?? '') === 'reference';
}
add_filter('body_class', function ($classes) {
    if (kf_reference_active()) { $classes[] = 'kf-style-reference'; }
    return $classes;
});
add_action('wp_enqueue_scripts', function () {
    if (kf_reference_active()) {
        $file = __DIR__ . '/kf-reference-style.css';
        if (is_readable($file)) { wp_add_inline_style('kampong', file_get_contents($file)); }
        $design=get_option('kf_design',[]);if(is_string($design))$design=json_decode($design,true);
        wp_add_inline_style('kampong',kf_reference_advanced_css($design));
    }
}, 99);

function kf_reference_advanced_css($design) {
    if (!is_array($design) || !isset($design['advanced']) || !is_array($design['advanced'])) return '';
    $schema=json_decode('{"body_font": ["sans", "sans", "serif", "rounded", "mono"], "body_size": [16, 14, 22], "heading_size": [64, 32, 96], "heading_weight": [700, 400, 900], "line_height": [1.65, 1.3, 2], "content_width": [1120, 720, 1600], "grid_gap": [24, 8, 64], "columns": [3, 1, 4], "mobile_pad": [40, 24, 80], "hero": ["split", "split", "center", "editorial", "minimal"], "header": ["sticky", "sticky", "static"], "card_style": ["bordered", "bordered", "flat", "elevated"], "image_ratio": ["4 / 3", "4 / 3", "1 / 1", "3 / 2", "16 / 9"]}',true);$numbers=json_decode('{"body_size": ["body-size", "px"], "heading_size": ["heading-size", "px"], "heading_weight": ["heading-weight", ""], "line_height": ["line-height", ""], "content_width": ["max", "px"], "grid_gap": ["grid-gap", "px"], "columns": ["columns", ""], "mobile_pad": ["mobile-pad", "px"]}',true);$enums=json_decode('{"hero": {"split": {"hero-columns": "1.1fr .9fr", "hero-align": "left", "hero-art": "block", "hero-margin": "0"}, "editorial": {"hero-columns": "1.4fr .6fr", "hero-align": "left", "hero-art": "block", "hero-margin": "0"}, "center": {"hero-columns": "1fr", "hero-align": "center", "hero-art": "none", "hero-margin": "auto"}, "minimal": {"hero-columns": "1fr", "hero-align": "left", "hero-art": "none", "hero-margin": "0"}}, "header": {"sticky": {"header-position": "sticky"}, "static": {"header-position": "static"}}, "card_style": {"bordered": {"card-border": "1px solid currentColor", "card-shadow": "none", "card-bg": "var(--kf-surface)"}, "flat": {"card-border": "0", "card-shadow": "none", "card-bg": "transparent"}, "elevated": {"card-border": "0", "card-shadow": "0 8px 32px #00000012", "card-bg": "var(--kf-surface)"}}}',true);$fonts=json_decode('{"sans": "-apple-system,BlinkMacSystemFont,\\"Segoe UI\\",Arial,sans-serif", "serif": "Georgia,\\"Times New Roman\\",serif", "rounded": "ui-rounded,\\"SF Pro Rounded\\",Arial,sans-serif", "mono": "ui-monospace,Menlo,monospace"}',true);
    $a=[];
    foreach($schema as $key=>$spec){
        $value=$design['advanced'][$key]??$spec[0];
        if(is_string($spec[0])){if(!is_string($value)||!in_array($value,array_slice($spec,1),true))return '';}
        else{if(!is_int($value)&&!is_float($value))return '';if(!is_finite((float)$value)||$value<$spec[1]||$value>$spec[2])return '';if($key!=='line_height'&&floor($value)!=$value)return '';}
        $a[$key]=$value;
    }
    $vars=['font-body'=>$fonts[$a['body_font']],'image-ratio'=>$a['image_ratio']];
    foreach($numbers as $key=>$pair){$vars[$pair[0]]=(string)$a[$key].$pair[1];}
    foreach($enums as $key=>$choices){$vars=array_merge($vars,$choices[$a[$key]]);}
    $css=':root{';foreach($vars as $key=>$value){$css.='--kf-'.$key.':'.$value.';';}return $css.'}';
}
