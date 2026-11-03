<?php get_header(); ?>
<?php if (have_posts()) : ?>
  <?php while (have_posts()) : the_post(); ?>
    <?php if (!is_front_page()) : ?>
      <div class="kf-pagehead"><div class="kf-container"><h1><?php the_title(); ?></h1></div></div>
    <?php endif; ?>
    <div class="kf-content"><?php the_content(); ?></div>
  <?php endwhile; ?>
<?php else : ?>
  <div class="kf-pagehead"><div class="kf-container"><h1>Nothing found</h1></div></div>
<?php endif; ?>
<?php get_footer(); ?>
