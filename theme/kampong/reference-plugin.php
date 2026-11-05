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
    }
}, 99);
