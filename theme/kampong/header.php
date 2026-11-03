<?php ?><!doctype html>
<html <?php language_attributes(); ?>>
<head>
<meta charset="<?php bloginfo('charset'); ?>">
<meta name="viewport" content="width=device-width, initial-scale=1">
<?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<a class="kf-skip" href="#kf-main">Skip to content</a>
<?php wp_body_open(); ?>
<header class="kf-header">
  <div class="kf-container kf-header-inner">
    <a class="kf-logo" href="<?php echo esc_url(home_url('/')); ?>"><?php bloginfo('name'); ?></a>
    <nav class="kf-nav-wrap" aria-label="Primary">
      <?php wp_nav_menu([
          'theme_location' => 'primary',
          'container' => false,
          'menu_class' => 'kf-nav',
          'fallback_cb' => false,
          'depth' => 1,
      ]); ?>
    </nav>
    <a class="kf-btn kf-btn-sm ghost" href="<?php echo esc_url(home_url('/contact/')); ?>">Contact Us</a>
  </div>
</header>
<main class="kf-main" id="kf-main">
