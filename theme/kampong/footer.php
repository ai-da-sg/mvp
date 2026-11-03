</main>
<footer class="kf-footer">
  <div class="kf-container">
    <div class="kf-footer-inner">
      <div>
        <div class="kf-footmark"><span class="d1"></span><span class="d2"></span><span class="d3"></span></div>
        <h4><?php bloginfo('name'); ?></h4>
        <p><?php bloginfo('description'); ?></p>
      </div>
      <div>
        <h4>Contact</h4>
        <p><?php echo esc_html(get_option('kf_phone', '+65 6000 0000')); ?></p>
        <p><a href="mailto:<?php echo esc_attr(get_option('kf_email', 'hello@example.sg')); ?>"><?php echo esc_html(get_option('kf_email', 'hello@example.sg')); ?></a></p>
        <p><?php echo esc_html(get_option('kf_address', 'Singapore')); ?></p>
      </div>
      <div>
        <h4>Links</h4>
        <?php wp_nav_menu([
            'theme_location' => 'footer',
            'container' => false,
            'menu_class' => 'kf-footnav',
            'fallback_cb' => false,
            'depth' => 1,
        ]); ?>
      </div>
    </div>
    <div class="kf-bottom">
      <span>&copy; <?php echo esc_html(date('Y')); ?> <?php bloginfo('name'); ?>. All rights reserved.</span>
      <span>Built with KampongFlow</span>
    </div>
  </div>
</footer>
<?php
$cta_text = get_option('kf_cta_text');
$cta_url  = get_option('kf_cta_url', '/contact/');
$gh_text  = get_option('kf_cta_ghost_text');
$gh_url   = get_option('kf_cta_ghost_url');
if ($cta_text) :
?>
<div class="kf-sticky-cta">
  <?php if ($gh_text && $gh_url) : ?>
    <a class="ghost" href="<?php echo esc_url($gh_url); ?>"><?php echo esc_html($gh_text); ?></a>
  <?php endif; ?>
  <a class="primary" href="<?php echo esc_url($cta_url); ?>"><?php echo esc_html($cta_text); ?></a>
</div>
<script>document.body.classList.add('kf-has-cta');</script>
<?php endif; ?>
<?php wp_footer(); ?>
</body>
</html>
