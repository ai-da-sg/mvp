<?php
/** Shared security policy, installed as a mandatory plugin for every managed site. */
if (!defined('ABSPATH')) { exit; }
if (!defined('DISALLOW_FILE_EDIT')) { define('DISALLOW_FILE_EDIT', true); }
add_filter('xmlrpc_enabled', '__return_false', PHP_INT_MAX);
add_filter('xmlrpc_methods', '__return_empty_array', PHP_INT_MAX);
add_filter('wp_headers', function ($headers) { unset($headers['X-Pingback']); return $headers; });
if (defined('XMLRPC_REQUEST') && XMLRPC_REQUEST) {
    status_header(403); header('Content-Type: text/plain; charset=utf-8'); exit('XML-RPC is disabled.');
}

// Unenrolled sites remain viewable, but have no independent browser/API login.
// WP-CLI is a host administrator operation, not a network authentication fallback.
if (!(defined('WP_CLI') && WP_CLI) && (!function_exists('kf_mvp_config') || empty(get_option('kf_mvp_sso', [])['secret']))) {
    add_filter('authenticate', function () { return new WP_Error('mvp_enrollment_required', '此站点尚未接入 MVP 统一登录。'); }, PHP_INT_MAX, 3);
    add_filter('determine_current_user', '__return_zero', PHP_INT_MAX);
    add_filter('wp_is_application_passwords_available', '__return_false', PHP_INT_MAX);
    add_filter('pre_option_users_can_register', '__return_zero', PHP_INT_MAX);
    add_filter('allow_password_reset', '__return_false', PHP_INT_MAX);
    add_action('login_init', function () {
        nocache_headers(); wp_die('请通过 MVP 管理此站点；正式 HTTPS 地址配置完成后方可启用统一登录。', 'MVP', ['response'=>403]);
    }, 0);
}

/** One database lock serializes the per-IP and site-wide budgets across PHP workers. */
function kf_security_contact_budget($ip, $now = null) {
    global $wpdb;
    $now = $now ?? time();
    $key = 'kf_contact_rate_v1';
    $lock = 'kf_contact_' . substr(hash('sha256', DB_NAME . ':' . $wpdb->options), 0, 40);
    if ((string)$wpdb->get_var($wpdb->prepare('SELECT GET_LOCK(%s, 1)', $lock)) !== '1') { return 503; }
    try {
        $raw = $wpdb->get_var($wpdb->prepare("SELECT option_value FROM {$wpdb->options} WHERE option_name=%s", $key));
        if ($wpdb->last_error) { return 503; }
        $state = json_decode((string)$raw, true);
        if (!is_array($state) || ($state['until'] ?? 0) <= $now) { $state = ['until'=>$now+60, 'count'=>0]; }
        // Keep per-IP rolling expiry independent of the site's minute boundary.
        $ips = json_decode((string)$wpdb->get_var($wpdb->prepare("SELECT option_value FROM {$wpdb->options} WHERE option_name=%s", $key.'_ips')), true);
        if ($wpdb->last_error) { return 503; }
        $ips = is_array($ips) ? array_filter($ips, function ($expiry) use ($now) { return is_int($expiry) && $expiry > $now; }) : [];
        $hash = hash_hmac('sha256', $ip, wp_salt('nonce'));
        if (isset($ips[$hash]) || $state['count'] >= 100) { return 429; }
        $state['count']++; $ips[$hash] = $now+60;
        // The lock is held until both records are committed. Failure denies the submission.
        foreach ([$key=>$state, $key.'_ips'=>$ips] as $name=>$value) {
            $sql = $wpdb->prepare("INSERT INTO {$wpdb->options} (option_name, option_value, autoload) VALUES (%s,%s,'off') ON DUPLICATE KEY UPDATE option_value=VALUES(option_value), autoload='off'", $name, wp_json_encode($value));
            if ($wpdb->query($sql) === false) { return 503; }
        }
        return 200;
    } finally { $wpdb->get_var($wpdb->prepare('SELECT RELEASE_LOCK(%s)', $lock)); }
}

add_filter('rest_pre_dispatch', function ($result, $server, $request) {
    if ($result !== null || $request->get_route() !== '/kf/v1/contact' || $request->get_method() !== 'POST') { return $result; }
    if (strlen($request->get_body()) > 16384) { return new WP_Error('kf_body_too_large', 'Request too large.', ['status'=>413]); }
    foreach (['name'=>120,'email'=>254,'phone'=>80,'message'=>4000,'website'=>512] as $field=>$limit) {
        $value = $request->get_param($field);
        if ($value !== null && (!is_string($value) || mb_strlen($value) > $limit)) { return new WP_Error('kf_invalid_field', 'Invalid field: '.$field, ['status'=>400]); }
    }
    if (trim((string)$request->get_param('website')) !== '') { return new WP_REST_Response(['ok'=>true],200); }
    if (trim(sanitize_text_field((string)$request->get_param('name'))) === '' || trim(sanitize_textarea_field((string)$request->get_param('message'))) === '' || !is_email((string)$request->get_param('email'))) {
        return new WP_Error('kf_invalid_contact', 'Name, email and message are required.', ['status'=>400]);
    }
    // REMOTE_ADDR is set by the trusted reverse proxy / Apache mod_remoteip, never raw user headers.
    $status = kf_security_contact_budget($_SERVER['REMOTE_ADDR'] ?? 'unknown');
    if ($status !== 200) { return new WP_Error('kf_contact_limited', 'Please try again later.', ['status'=>$status]); }
    return $result;
}, 5, 3);
