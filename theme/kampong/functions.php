<?php
/**
 * Kampong theme
 * 设计令牌（design tokens）→ CSS 变量 → 组件样式
 * 站点选项 kf_design 存一份 JSON，改它就能换整套视觉，不用动 CSS。
 */

function kampong_default_design(): array {
    return [
        'preset'  => 'default',
        'palette' => [
            'primary'     => '#0f5132',
            'primaryDark' => '#0a3a24',
            'accent'      => '#d4a04a',
            'bg'          => '#f7f9f7',
            'surface'     => '#ffffff',
            'ink'         => '#16211c',
            'muted'       => '#5d6b64',
            'deep'        => '#10231a',
        ],
        'shape'   => ['radius' => '16px', 'button' => '999px'],
        'type'    => ['heading' => 'sans', 'scale' => '1'],
        'layout'  => ['pad' => '76px', 'heroArt' => true],
        'photos'  => ['overlay' => '0.46'],
    ];
}

/** 允许的字体族，前端只传 key，避免注入 */
function kampong_font_stack(string $key): string {
    $stacks = [
        'sans'    => '-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Helvetica Neue",Arial,"PingFang SC","Microsoft YaHei",sans-serif',
        'serif'   => 'Georgia,"Times New Roman",Cambria,"Songti SC",serif',
        'rounded' => 'ui-rounded,"SF Pro Rounded","Hiragino Maru Gothic ProN",Quicksand,Arial,sans-serif',
        'mono'    => 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
    ];
    return $stacks[$key] ?? $stacks['sans'];
}

/** 颜色只接受 #rgb / #rrggbb，其余丢弃 */
function kampong_safe_color($v, string $fallback): string {
    return (is_string($v) && preg_match('/^#[0-9a-fA-F]{3,8}$/', $v)) ? $v : $fallback;
}

function kampong_safe_len($v, string $fallback): string {
    return (is_string($v) && preg_match('/^\d{1,3}(px|rem|em|%)$/', $v)) ? $v : $fallback;
}

function kampong_design(): array {
    $base = kampong_default_design();
    $raw  = get_option('kf_design');
    $d    = $raw ? json_decode($raw, true) : null;

    // 向后兼容：老站点只有 kf_palette
    if (!is_array($d)) {
        $legacy = json_decode((string) get_option('kf_palette'), true);
        if (is_array($legacy) && !empty($legacy)) {
            $base['palette'] = array_merge($base['palette'], $legacy);
            $base['palette']['deep'] = $base['palette']['primaryDark'];
        }
        return $base;
    }

    $d['palette'] = array_merge($base['palette'], is_array($d['palette'] ?? null) ? $d['palette'] : []);
    $d['shape']   = array_merge($base['shape'],   is_array($d['shape'] ?? null)   ? $d['shape']   : []);
    $d['type']    = array_merge($base['type'],    is_array($d['type'] ?? null)    ? $d['type']    : []);
    $d['layout']  = array_merge($base['layout'],  is_array($d['layout'] ?? null)  ? $d['layout']  : []);
    $d['photos']  = array_merge($base['photos'],  is_array($d['photos'] ?? null)  ? $d['photos']  : []);
    return $d;
}

/** 令牌 → CSS 变量 */
function kampong_css_vars(array $d): string {
    $p = $d['palette'];
    $s = $d['shape'];
    $vars = [
        'primary'      => kampong_safe_color($p['primary'] ?? '', '#0f5132'),
        'primary-dark' => kampong_safe_color($p['primaryDark'] ?? '', '#0a3a24'),
        'accent'       => kampong_safe_color($p['accent'] ?? '', '#d4a04a'),
        'bg'           => kampong_safe_color($p['bg'] ?? '', '#f7f9f7'),
        'surface'      => kampong_safe_color($p['surface'] ?? '', '#ffffff'),
        'ink'          => kampong_safe_color($p['ink'] ?? '', '#16211c'),
        'muted'        => kampong_safe_color($p['muted'] ?? '', '#5d6b64'),
        'deep'         => kampong_safe_color($p['deep'] ?? '', '#10231a'),
        'radius'       => kampong_safe_len($s['radius'] ?? '', '16px'),
        'btn-radius'   => kampong_safe_len($s['button'] ?? '', '999px'),
        'pad'          => kampong_safe_len($d['layout']['pad'] ?? '', '76px'),
    ];

    $ov = (string) ($d['photos']['overlay'] ?? '');
    $vars['overlay'] = preg_match('/^(0?\.\d+|1)$/', $ov) ? $ov : '0.46';

    $css = ':root{';
    foreach ($vars as $k => $v) {
        $css .= "--kf-{$k}:{$v};";
    }
    $css .= '--kf-font-head:' . kampong_font_stack((string) ($d['type']['heading'] ?? 'sans')) . ';';
    $css .= '--kf-font-body:' . kampong_font_stack('sans') . ';';
    $css .= '}';
    return $css;
}

add_action('after_setup_theme', function () {
    add_theme_support('title-tag');
    add_theme_support('post-thumbnails');
    add_theme_support('html5', ['search-form', 'comment-form', 'gallery', 'caption', 'style', 'script']);
    add_theme_support('responsive-embeds');
    register_nav_menus(['primary' => 'Primary Menu', 'footer' => 'Footer Menu']);
});

add_action('wp_enqueue_scripts', function () {
    $ver = @filemtime(get_stylesheet_directory() . '/style.css') ?: '1.0';
    wp_enqueue_style('kampong', get_stylesheet_uri(), [], $ver);
    wp_add_inline_style('kampong', kampong_css_vars(kampong_design()));
});

/** 站点基础 SEO / 社交卡片 / 结构化数据 */
add_action('wp_head', function () {
    $d    = kampong_design();
    $name = get_bloginfo('name');
    $desc = get_bloginfo('description');
    $prim = $d['palette']['primary'] ?? '#0f5132';
    $accent = $d['palette']['accent'] ?? '#d4a04a';

    // favicon：品牌三圆点，内联 SVG，无需请求
    $svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
         . '<circle cx="16" cy="32" r="12" fill="' . esc_attr($prim) . '"/>'
         . '<circle cx="32" cy="32" r="12" fill="' . esc_attr($accent) . '"/>'
         . '<circle cx="48" cy="32" r="12" fill="#29abe2"/></svg>';
    echo '<link rel="icon" href="data:image/svg+xml,' . rawurlencode($svg) . '">' . "\n";
    echo '<meta name="theme-color" content="' . esc_attr($prim) . '">' . "\n";

    if ($desc) {
        echo '<meta name="description" content="' . esc_attr($desc) . '">' . "\n";
    }
    echo '<meta property="og:type" content="website">' . "\n";
    echo '<meta property="og:title" content="' . esc_attr($name) . '">' . "\n";
    if ($desc) {
        echo '<meta property="og:description" content="' . esc_attr($desc) . '">' . "\n";
    }
    if (is_singular()) {
        $url = get_permalink();
        echo '<meta property="og:url" content="' . esc_url($url) . '">' . "\n";
        echo '<link rel="canonical" href="' . esc_url($url) . '">' . "\n";
    }

    // 结构化数据：本地商家
    $data = [
        '@context' => 'https://schema.org',
        '@type'    => get_option('kf_schema_type', 'LocalBusiness'),
        'name'     => $name,
        'description' => $desc,
        'telephone'   => get_option('kf_phone', ''),
        'email'       => get_option('kf_email', ''),
        'address'     => ['@type' => 'PostalAddress', 'streetAddress' => get_option('kf_address', '')],
    ];
    echo '<script type="application/ld+json">'
       . wp_json_encode(array_filter($data)) . '</script>' . "\n";
});

/** 线索：自定义文章类型 + 提交接口 */
add_action('init', function () {
    register_post_type('kf_lead', [
        'label' => 'Enquiries',
        'public' => false,
        'show_ui' => true,
        'show_in_menu' => true,
        'menu_icon' => 'dashicons-email-alt',
        'supports' => ['title', 'editor', 'custom-fields'],
        'capability_type' => 'post',
    ]);
});

add_action('rest_api_init', function () {
    register_rest_route('kf/v1', '/contact', [
        'methods' => 'POST',
        'permission_callback' => '__return_true',
        'callback' => 'kampong_contact_submit',
    ]);
});

function kampong_contact_submit(WP_REST_Request $req) {
    $name  = sanitize_text_field((string) $req->get_param('name'));
    $email = sanitize_email((string) $req->get_param('email'));
    $phone = sanitize_text_field((string) $req->get_param('phone'));
    $msg   = sanitize_textarea_field((string) $req->get_param('message'));

    // 蜜罐：机器人会填，真人看不见
    if (trim((string) $req->get_param('website')) !== '') {
        return new WP_REST_Response(['ok' => true], 200);
    }
    if ($name === '' || $msg === '' || !is_email($email)) {
        return new WP_REST_Response(['ok' => false, 'error' => 'Please fill in your name, a valid email and a message.'], 400);
    }
    if (mb_strlen($msg) > 4000) {
        return new WP_REST_Response(['ok' => false, 'error' => 'Message is too long.'], 400);
    }

    $ip = isset($_SERVER['REMOTE_ADDR']) ? $_SERVER['REMOTE_ADDR'] : 'unknown';
    $rl = 'kf_rl_' . md5($ip);
    if (get_transient($rl)) {
        return new WP_REST_Response(['ok' => false, 'error' => 'Too many submissions, please try again in a minute.'], 429);
    }
    set_transient($rl, 1, 60);

    $id = wp_insert_post([
        'post_type'    => 'kf_lead',
        'post_status'  => 'publish',
        'post_title'   => $name . ' — ' . $email,
        'post_content' => $msg,
    ], true);
    if (is_wp_error($id)) {
        return new WP_REST_Response(['ok' => false, 'error' => 'Could not save your message.'], 500);
    }
    update_post_meta($id, '_kf_email', $email);
    update_post_meta($id, '_kf_phone', $phone);
    update_post_meta($id, '_kf_ip', $ip);

    $sent = wp_mail(
        get_option('admin_email'),
        sprintf('[%s] New enquiry from %s', get_bloginfo('name'), $name),
        "Name: {$name}\nEmail: {$email}\nPhone: {$phone}\n\n{$msg}"
    );
    update_post_meta($id, '_kf_mail_sent', $sent ? '1' : '0');

    return new WP_REST_Response(['ok' => true, 'id' => $id], 200);
}

/** 前台表单提交脚本 */
add_action('wp_footer', function () {
    if (!is_page() && !is_front_page()) {
        return;
    }
    ?>
<script>
document.addEventListener('submit', function (e) {
  var f = e.target;
  if (!f.classList || !f.classList.contains('kf-form')) return;
  e.preventDefault();
  var btn = f.querySelector('button[type=submit]');
  var msg = f.querySelector('.kf-form-msg');
  var data = {};
  new FormData(f).forEach(function (v, k) { data[k] = v; });
  btn.disabled = true; btn.dataset.old = btn.textContent; btn.textContent = 'Sending…';
  fetch('/wp-json/kf/v1/contact', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(data)
  }).then(function (r) { return r.json().then(function (j) { return [r.ok, j]; }); })
    .then(function (p) {
      var ok = p[0] && p[1].ok;
      msg.textContent = ok ? 'Thank you — we will reply within one working day.'
                           : (p[1].error || 'Something went wrong.');
      msg.className = 'kf-form-msg ' + (ok ? 'ok' : 'bad');
      if (ok) { f.reset(); }
      btn.disabled = false; btn.textContent = btn.dataset.old;
    })
    .catch(function () {
      msg.textContent = 'Network error, please try again.';
      msg.className = 'kf-form-msg bad';
      btn.disabled = false; btn.textContent = btn.dataset.old;
    });
});
</script>
    <?php
});

/** 联系表单短码：内容里只放 [kf_contact_form]，避免编辑器过滤表单标签 */
add_shortcode('kf_contact_form', function ($atts) {
    $a = shortcode_atts(['submit' => 'Send message'], $atts);
    ob_start(); ?>
<form class="kf-form" novalidate>
  <div class="kf-form-row">
    <label>Your name<input name="name" required autocomplete="name"></label>
    <label>Email<input type="email" name="email" required autocomplete="email"></label>
  </div>
  <label>Phone<input name="phone" autocomplete="tel"></label>
  <label>How can we help?<textarea name="message" required></textarea></label>
  <input class="kf-hp" type="text" name="website" tabindex="-1" autocomplete="off" aria-hidden="true">
  <button type="submit"><?php echo esc_html($a['submit']); ?></button>
  <p class="kf-form-msg" role="status" aria-live="polite"></p>
</form>
    <?php
    return ob_get_clean();
});
