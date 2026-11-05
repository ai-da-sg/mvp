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
    <button class="kf-menu-toggle" type="button" aria-controls="kf-primary-nav" aria-expanded="false"><?php echo esc_html(kampong_label('Menu', '菜单')); ?><svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 6h16M4 12h16M4 18h16"/></svg></button>
    <nav id="kf-primary-nav" class="kf-nav-wrap" aria-label="<?php echo esc_attr(kampong_label('Primary', '主导航')); ?>">
      <?php wp_nav_menu([
          'theme_location' => 'primary',
          'container' => false,
          'menu_class' => 'kf-nav',
          'fallback_cb' => false,
          'depth' => 1,
      ]); ?>
    </nav>
    <a class="kf-btn kf-btn-sm ghost" href="<?php echo esc_url(home_url('/contact/')); ?>"><?php echo esc_html(kampong_label('Contact Us', '联系咨询')); ?></a>
  </div>
</header>
<script>
(()=>{const header=document.querySelector('.kf-header'),button=header.querySelector('.kf-menu-toggle');
header.dataset.navEnhanced='true';
const close=()=>{header.classList.remove('nav-open');button.setAttribute('aria-expanded','false');};
button.addEventListener('click',()=>{const open=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(open));header.classList.toggle('nav-open',open);});
header.addEventListener('keydown',e=>{if(e.key==='Escape'&&button.getAttribute('aria-expanded')==='true'){close();button.focus();}});
document.addEventListener('click',e=>{if(!header.contains(e.target))close();});
matchMedia('(min-width:901px)').addEventListener('change',close);
})();
</script>
<main class="kf-main" id="kf-main">
