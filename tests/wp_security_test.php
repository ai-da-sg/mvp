<?php
// Pure PHP policy tests; no network, database, email or production data.
define('ABSPATH', __DIR__); define('DB_NAME','fixture');
$hooks=[];
function add_filter($name,$callback,$priority=10,$argc=1){global $hooks;$hooks[$name][]=$callback;}
function add_action($name,$callback,$priority=10,$argc=1){add_filter($name,$callback,$priority,$argc);}
function get_option($key,$default=false){return $default;}
function wp_salt($scheme){return 'test-only';}
function wp_json_encode($v){return json_encode($v);}
function sanitize_text_field($v){return strip_tags($v);}
function sanitize_textarea_field($v){return strip_tags($v);}
function is_email($v){return filter_var($v,FILTER_VALIDATE_EMAIL);}
function __return_false(){return false;}
function __return_empty_array(){return [];}
function __return_zero(){return 0;}
class WP_Error {public $code,$data;function __construct($code,$message,$data=[]){$this->code=$code;$this->data=$data;}}
class WP_REST_Response {public $status;function __construct($body,$status){$this->status=$status;}}
class FakeDB {
 public $last_error='', $options='test_options',$data=[],$lock=true,$fail=false,$released=0;
 function prepare($sql,...$args){return [$sql,$args];}
 function get_var($query){[$sql,$args]=$query;if(str_contains($sql,'RELEASE_LOCK')){$this->released++;return 1;}if(str_contains($sql,'GET_LOCK')){return $this->lock?1:0;}return $this->data[$args[0]]??null;}
 function query($query){if($this->fail){return false;}[$sql,$args]=$query;$this->data[$args[0]]=$args[1];return 1;}
}
$wpdb=new FakeDB();
require __DIR__.'/../theme/kampong/wp-security.php';
function check($ok,$message){if(!$ok){throw new Exception($message);}}
check(DISALLOW_FILE_EDIT,'file editor disabled');
check(($hooks['xmlrpc_methods'][0])()===[],'all XML-RPC methods disabled');
check(($hooks['determine_current_user'][0])(12)===0,'unenrolled cookies refused');
check(($hooks['authenticate'][0])() instanceof WP_Error,'unenrolled passwords refused');
check(kf_security_contact_budget('192.0.2.1',100)===200,'first request');
check(kf_security_contact_budget('192.0.2.1',101)===429,'duplicate IP');
check(kf_security_contact_budget('192.0.2.2',159)===200,'second IP');
check(kf_security_contact_budget('192.0.2.2',160)===429,'IP cannot bypass at site window boundary');
check(kf_security_contact_budget('192.0.2.1',160)===200,'IP expiry');
$wpdb=new FakeDB();
for($i=0;$i<100;$i++){check(kf_security_contact_budget('ip-'.$i,100)===200,'site budget');}
check(kf_security_contact_budget('ip-new',101)===429,'site total limit');
$wpdb=new FakeDB();$wpdb->lock=false;check(kf_security_contact_budget('ip',100)===503,'lock failure closed');
$wpdb=new FakeDB();$wpdb->fail=true;check(kf_security_contact_budget('ip',100)===503,'write failure closed');check($wpdb->released===1,'lock released on error');
class Req {
 public $params=['name'=>'Example','email'=>'x@example.com','message'=>'Hello'], $body='{}';
 function get_route(){return '/kf/v1/contact';}function get_method(){return 'POST';}function get_body(){return $this->body;}function get_param($key){return $this->params[$key]??null;}
}
$filter=$hooks['rest_pre_dispatch'][0];$r=new Req();$wpdb=new FakeDB();
$r->params['phone']=[];check($filter(null,null,$r)->data['status']===400,'array input');
$r=new Req();$r->body=str_repeat('x',16385);check($filter(null,null,$r)->data['status']===413,'body limit');
$r=new Req();$r->params['name']=str_repeat('x',121);check($filter(null,null,$r)->data['status']===400,'field size');
$r=new Req();$r->params['website']='bot';check($filter(null,null,$r)->status===200,'honeypot');check($wpdb->data===[],'honeypot no writes');
$r=new Req();check($filter(null,null,$r)===null,'valid submission allowed');check($filter(null,null,$r)->data['status']===429,'repeated submission rejected');
echo "PASS WordPress authentication, XML-RPC, contact validation, budget expiry and failure handling\n";
