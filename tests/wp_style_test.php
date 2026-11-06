<?php
// Pure rendering checks: no WordPress state or network access.
function add_filter(...$args){}
function add_action(...$args){}
require __DIR__.'/../theme/kampong/reference-plugin.php';
function check_style($ok,$label){if(!$ok)throw new Exception($label);}
check_style(kf_reference_advanced_css([])==='', 'Legacy design stays unchanged');
$css=kf_reference_advanced_css(['advanced'=>['heading_size'=>84,'columns'=>2,'hero'=>'editorial','body_font'=>'serif']]);
check_style(str_contains($css,'--kf-heading-size:84px;'),'Heading size survives publication');
check_style(str_contains($css,'--kf-columns:2;'),'Grid columns survive publication');
check_style(str_contains($css,'--kf-hero-columns:1.4fr .6fr;'),'Editorial layout survives publication');
check_style(str_contains($css,'--kf-font-body:Georgia,'),'Body font survives publication');
foreach([['body_font'=>'</style><script>alert(1)</script>'],['columns'=>99],['body_size'=>true],['grid_gap'=>INF],['hero'=>'url(https://example.com)']] as $bad){
 check_style(kf_reference_advanced_css(['advanced'=>$bad])==='', 'Unsafe or unbounded CSS rejected');
}
echo "PASS WordPress advanced template rendering and injection boundaries\n";
