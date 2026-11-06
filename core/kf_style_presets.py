"""Original local style recipes informed by public Squarespace/Wix galleries.
No remote theme code, third-party images or hosted assets are required.
"""
import copy

CATALOG_VERSION = 1
INDUSTRIES = ('tech', 'restaurant', 'preschool', 'law', 'trading', 'littlegems')
ADVANCED = {
    'body_font': ('sans', 'sans', 'serif', 'rounded', 'mono'),
    'body_size': (16, 14, 22), 'heading_size': (64, 32, 96),
    'heading_weight': (700, 400, 900), 'line_height': (1.65, 1.3, 2),
    'content_width': (1120, 720, 1600), 'grid_gap': (24, 8, 64),
    'columns': (3, 1, 4), 'mobile_pad': (40, 24, 80),
    'hero': ('split', 'split', 'center', 'editorial', 'minimal'),
    'header': ('sticky', 'sticky', 'static'),
    'card_style': ('bordered', 'bordered', 'flat', 'elevated'),
    'image_ratio': ('4 / 3', '4 / 3', '1 / 1', '3 / 2', '16 / 9'),
}


def catalog():
    sq = 'https://www.squarespace.com/templates/browse/topic/all-templates/type/portfolio'
    wix = 'https://www.wix.com/website/templates/html/'
    recipes = [
        ('editorial-studio', 'Editorial Studio', 'Creative', 'tech', '#292521', '#f6f2eb', '#ffffff', '#282522', '#665e55', '#a05d36', 'serif', 2, 96,
         dict(hero='editorial', heading_size=88, heading_weight=400, columns=2, card_style='flat', image_ratio='3 / 2'), sq,
         'An editorial portfolio with generous margins, oversized serif headlines and restrained project grids.',
         ['hero','gallery','split','quotes','cta'], 'Lead with selected projects. Use short project captions and generous visual pauses. Keep one contact action; only include supplied work and verified testimonials.'),
        ('gallery-atelier', 'Gallery Atelier', 'Photography', 'tech', '#202020', '#ffffff', '#f6f6f6', '#171717', '#555555', '#7a533b', 'sans', 0, 80,
         dict(hero='minimal', heading_size=72, columns=3, card_style='flat', content_width=1360, grid_gap=12, image_ratio='1 / 1'), wix+'photography',
         'A monochrome photography gallery with square project tiles and discreet navigation.',
         ['hero','gallery','rich','cta'], 'Prioritize a curated image gallery. Use only owned or supplied images; missing images remain placeholders. Do not invent clients, awards or exhibitions.'),
        ('maison-dining', 'Maison Dining', 'Restaurant', 'restaurant', '#653a2a', '#fbf4e9', '#fffdf8', '#30241c', '#665449', '#a65a2e', 'serif', 4, 88,
         dict(hero='center', heading_weight=400, columns=2, content_width=1040, image_ratio='3 / 2'), wix+'restaurants-food/restaurant',
         'A classic brasserie layout with warm cream surfaces, centered invitations and readable menus.',
         ['hero','split','table','gallery','cta'], 'Show cuisine, a concise menu, opening hours and a reservation contact. Table reservations and ordering require configured integrations: never imply a working booking or checkout when none exists.'),
        ('verdant-wellness', 'Verdant Wellness', 'Wellness', 'tech', '#34594b', '#f3f5ed', '#ffffff', '#23342a', '#536056', '#8b6438', 'serif', 24, 96,
         dict(hero='editorial', heading_weight=400, content_width=1080, columns=2, image_ratio='4 / 3'), 'https://www.squarespace.com/templates/paloma-demo',
         'A calm editorial service website with natural tones, generous spacing and gentle rounded cards.',
         ['hero','cards','split','quotes','cta'], 'Explain services and practitioner background plainly. Use verified credentials only. Avoid unsupported health outcomes; provide a clear enquiry action.'),
        ('civic-advisory', 'Civic Advisory', 'Consulting', 'law', '#173d64', '#f5f7fa', '#ffffff', '#1d2d3e', '#526172', '#8d642b', 'sans', 8, 72,
         dict(hero='split', columns=3, heading_size=64, card_style='bordered'), wix+'business/consulting-coaching',
         'A structured professional-services website with a strong headline and clear service tiers.',
         ['hero','cards','split','list','cta'], 'Present expertise, approach and service boundaries. Use evidence supplied by the business for case studies. Do not fabricate statistics, endorsements or legal credentials.'),
        ('little-orbit', 'Little Orbit', 'Education', 'preschool', '#684070', '#fff7ec', '#ffffff', '#34283b', '#65596d', '#a94d32', 'rounded', 28, 72,
         dict(hero='split', heading_size=60, columns=3, card_style='elevated', image_ratio='4 / 3'), wix+'education',
         'A welcoming school website with rounded program cards and a clear parent journey.',
         ['hero','cards','split','gallery','list','cta'], 'Organize ages, programs, learning approach and visit enquiries. Protect children’s privacy; use authorized photos only. Do not invent fees, accreditations or available places.'),
        ('slate-architecture', 'Slate Architecture', 'Architecture', 'tech', '#343f3d', '#eaece7', '#f7f8f5', '#202825', '#505c54', '#805d3c', 'sans', 0, 112,
         dict(hero='minimal', heading_size=80, heading_weight=500, columns=2, content_width=1280, grid_gap=40, card_style='flat', image_ratio='16 / 9'), sq,
         'An architectural portfolio with a strict grid, wide project images and quiet typography.',
         ['hero','gallery','split','list','cta'], 'Use a project-led narrative, concise material/process notes and contact details. Do not invent project locations, clients or architectural certifications.'),
        ('launchpad-saas', 'Launchpad SaaS', 'Technology', 'tech', '#3047a1', '#f5f7ff', '#ffffff', '#202a44', '#53617b', '#7851a9', 'sans', 16, 80,
         dict(hero='center', heading_size=76, columns=3, card_style='elevated', content_width=1200), wix+'business/technology-apps',
         'A focused product landing page with a centered proposition and modular feature cards.',
         ['hero','cards','split','table','list','cta'], 'Describe the product, features and onboarding. Pricing must come from supplied facts; avoid invented user counts, logos or performance claims. Use one primary demo or signup action.'),
    ]
    output=[]
    for ident,name,category,industry,primary,bg,surface,ink,muted,accent,font,radius,pad,advanced,source,summary,sections,guidance in recipes:
        output.append(dict(id='local-'+ident,name=name,category=category,industry=industry,
            source_url=source,summary=summary,guidance=guidance,
            tags=[category.lower(),'local','classic'], blueprint=sections,
            tokens=dict(palette=dict(primary=primary,primaryDark=primary,deep=primary,bg=bg,surface=surface,ink=ink,muted=muted,accent=accent),
                        type=dict(heading=font),shape=dict(radius=str(radius)+'px',button=str(min(radius,24))+'px'),
                        layout=dict(pad=str(pad)+'px'),photos=dict(overlay='0.46'),advanced=advanced),
            enabled=True,version=1,updated=0,origin='local-catalog'))
    return copy.deepcopy(output)
