<?php
/** MVP is the sole browser and API authentication authority. No local login fallback. */
if (defined('WP_CLI') && WP_CLI) { return; }
function kf_mvp_config() { return get_option('kf_mvp_sso', []); }
function kf_mvp_url($path = '') {
    $c = kf_mvp_config();
    return rtrim($c['console_url'] ?? '', '/') . $path;
}
function kf_mvp_fail() {
    nocache_headers();
    wp_die('统一登录验证失败或已过期，请返回 MVP 重新进入。', 'MVP 统一登录', ['response'=>403]);
}
function kf_mvp_call($action, $fields) {
    $c = kf_mvp_config();
    if (empty($c['secret']) || empty($c['console_url']) || empty($c['slug'])) { return false; }
    $raw = wp_json_encode(array_merge($fields, ['action'=>$action, 'site'=>$c['slug']]));
    $time = (string) time(); $nonce = bin2hex(random_bytes(32));
    $signature = hash_hmac('sha256', $time . "\n" . $nonce . "\n" . $raw, $c['secret']);
    $response = wp_remote_post(kf_mvp_url('/api/wordpress/callback'), [
        'timeout'=>5, 'redirection'=>0, 'sslverify'=>true, 'limit_response_size'=>8192,
        'headers'=>['Content-Type'=>'application/json','X-MVP-Time'=>$time,'X-MVP-Nonce'=>$nonce,'X-MVP-Signature'=>$signature], 'body'=>$raw]);
    if (is_wp_error($response) || wp_remote_retrieve_response_code($response) !== 200) { return false; }
    $data = json_decode(wp_remote_retrieve_body($response), true);
    return is_array($data) && !empty($data['ok']) ? $data : false;
}

// Disable passwords, registration, XML-RPC, Application Passwords and old auth cookies.
add_filter('authenticate', function () { return new WP_Error('mvp_only', '请通过 MVP 统一登录。'); }, PHP_INT_MAX, 3);
add_filter('wp_is_application_passwords_available', '__return_false', PHP_INT_MAX);
add_filter('xmlrpc_enabled', '__return_false', PHP_INT_MAX);
add_filter('xmlrpc_methods', '__return_empty_array', PHP_INT_MAX);
add_filter('pre_option_users_can_register', '__return_zero', PHP_INT_MAX);
add_filter('allow_password_reset', '__return_false', PHP_INT_MAX);
add_filter('login_url', function () { return kf_mvp_url('/login'); }, PHP_INT_MAX);
add_filter('lostpassword_url', function () { return kf_mvp_url('/login'); }, PHP_INT_MAX);
add_filter('register_url', function () { return kf_mvp_url('/login'); }, PHP_INT_MAX);
add_filter('logout_url', function () { return kf_mvp_url('/logout'); }, PHP_INT_MAX);
add_action('login_init', function () { nocache_headers(); wp_redirect(kf_mvp_url('/login'), 303); exit; }, 0);
add_filter('determine_current_user', function ($id) {
    if (!$id) { return 0; }
    $cookie = wp_parse_auth_cookie('', 'logged_in');
    if (!$cookie || empty($cookie['token'])) { return 0; }
    $session = WP_Session_Tokens::get_instance($id)->get($cookie['token']);
    if (empty($session['kf_mvp_grant'])) { return 0; }
    $checked = kf_mvp_call('check', ['grant'=>$session['kf_mvp_grant']]);
    if (!$checked || get_user_meta($id, 'kf_mvp_identity', true) !== $checked['user']) { return 0; }
    $user = get_userdata($id);
    if (!$user || !in_array($checked['role'], $user->roles, true)) { return 0; }
    return $id;
}, PHP_INT_MAX);

add_action('init', function () {
    $action = isset($_GET['kf_mvp_sso']) ? sanitize_key($_GET['kf_mvp_sso']) : '';
    if (!$action) { return; }
    if (!is_ssl()) { kf_mvp_fail(); }
    nocache_headers(); header('Referrer-Policy: no-referrer');
    $c = kf_mvp_config();
    if ($action === 'begin' && $_SERVER['REQUEST_METHOD'] === 'GET') {
        $verifier = bin2hex(random_bytes(32));
        setcookie('__Host-kf_mvp_browser', $verifier, ['expires'=>time()+180,'path'=>'/','secure'=>true,'httponly'=>true,'samesite'=>'None']);
        $url = kf_mvp_url('/wordpress/authorize') . '?' . http_build_query(['site'=>$c['slug'],'challenge'=>hash('sha256',$verifier)]);
        wp_redirect($url, 303); exit;
    }
    if ($action !== 'finish' || $_SERVER['REQUEST_METHOD'] !== 'POST') { kf_mvp_fail(); }
    $ticket = isset($_POST['ticket']) && is_string($_POST['ticket']) ? $_POST['ticket'] : '';
    $verifier = isset($_COOKIE['__Host-kf_mvp_browser']) ? $_COOKIE['__Host-kf_mvp_browser'] : '';
    if (!preg_match('/^[a-f0-9]{64}$/D', $ticket) || !preg_match('/^[a-f0-9]{64}$/D', $verifier)) { kf_mvp_fail(); }
    $result = kf_mvp_call('consume', ['ticket'=>$ticket,'verifier'=>$verifier]);
    if (!$result || !in_array($result['role'], ['administrator','editor'],true)) { kf_mvp_fail(); }
    $login = 'mvp_' . substr(hash('sha256', $result['user']),0,32);
    $id = username_exists($login);
    if ($id && get_user_meta($id,'kf_mvp_identity',true) !== $result['user']) { kf_mvp_fail(); }
    if (!$id) {
        $id = wp_insert_user(['user_login'=>$login,'user_pass'=>wp_generate_password(64,true,true),
            'display_name'=>sanitize_text_field($result['name']),'role'=>$result['role']]);
        if (is_wp_error($id)) { kf_mvp_fail(); }
        update_user_meta($id, 'kf_mvp_identity', $result['user']);
    }
    $user = new WP_User($id); $user->set_role($result['role']);
    $expiration = min((int)$result['expires'],time()+12*3600);
    $manager = WP_Session_Tokens::get_instance($id);
    $token = $manager->create($expiration);
    $session = $manager->get($token); $session['kf_mvp_grant']=$result['grant']; $manager->update($token,$session);
    wp_set_current_user($id);
    wp_set_auth_cookie($id,false,true,$token);
    do_action('wp_login',$user->user_login,$user);
    setcookie('__Host-kf_mvp_browser','',['expires'=>time()-3600,'path'=>'/','secure'=>true,'httponly'=>true,'samesite'=>'None']);
    wp_redirect(rtrim($c['site_url'],'/').'/wp-admin/',303); exit;
}, 0);
add_action('auth_redirect', function () {
    if (!is_user_logged_in()) { nocache_headers(); wp_redirect(kf_mvp_url('/login'),303); exit; }
}, 0);
add_action('admin_init', function () {
    if (!is_user_logged_in() && !(defined('DOING_AJAX') && DOING_AJAX)) {
        nocache_headers(); wp_redirect(kf_mvp_url('/login'),303); exit;
    }
}, 0);
add_action('admin_bar_menu', function ($bar) {
    $bar->add_node(['id'=>'mvp-console','title'=>'返回 MVP 管理','href'=>kf_mvp_url('/')]);
}, 100);
