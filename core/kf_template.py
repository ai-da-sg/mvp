#!/usr/bin/env python3
"""kf-template.py — 按行业把站点内容灌进 WordPress。

用法:
  kf-template.py --site /mnt/data1/kampongflow/sites/<slug> --industry preschool --company "X"

做法: 生成 site.json + kf_setup.php，用 wp-cli 容器执行 eval-file。
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kf_sections as KS

THEME_SRC = Path("/mnt/data1/kampongflow/theme/kampong")
REG = "docker.m.daocloud.io/library/wordpress:cli-php8.3"


def esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------- 区块构造
def hx(level, text, cls=""):
    attr = {"level": level}
    if cls:
        attr["className"] = cls
    c = f' class="wp-block-heading {cls}"'.replace("  ", " ") if cls else ' class="wp-block-heading"'
    return (f'<!-- wp:heading {json.dumps(attr)} -->\n'
            f'<h{level}{c}>{text}</h{level}>\n'
            f'<!-- /wp:heading -->\n')


def pp(text, cls=""):
    attr = json.dumps({"className": cls}) if cls else "{}"
    c = f' class="{cls}"' if cls else ""
    return f'<!-- wp:paragraph {attr} -->\n<p{c}>{text}</p>\n<!-- /wp:paragraph -->\n'


def grp(cls, inner):
    return (f'<!-- wp:group {json.dumps({"className": cls})} -->\n'
            f'<div class="wp-block-group {cls}">\n{inner}</div>\n'
            f'<!-- /wp:group -->\n')


def btn(label, url):
    return ('<!-- wp:buttons -->\n<div class="wp-block-buttons">'
            '<!-- wp:button -->\n<div class="wp-block-button">'
            f'<a class="wp-block-button__link wp-element-button" href="{url}">{label}</a>'
            '</div>\n<!-- /wp:button --></div>\n<!-- /wp:buttons -->\n')


def rawhtml(h):
    return f'<!-- wp:html -->\n{h}\n<!-- /wp:html -->\n'


def ul(items):
    lis = "".join(f"<li>{i}</li>" for i in items)
    return f'<!-- wp:list {json.dumps({"className": "kf-list"})} -->\n<ul class="wp-block-list kf-list">{lis}</ul>\n<!-- /wp:list -->\n'


def table(headers, rows):
    th = "".join(f"<th>{h}</th>" for h in headers)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<!-- wp:html -->\n<table class="kf-table"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>\n<!-- /wp:html -->\n'


def gallery(items):
    box = "".join(
        f'<div class="kf-shot"><img src="{src}" alt="{t}" loading="lazy"><span>{t}</span></div>'
        for c, t, src in items)
    return f'<!-- wp:html -->\n<div class="kf-gallery">{box}</div>\n<!-- /wp:html -->\n'


def band(src, cap, alt="My Little Gems"):
    return f'<!-- wp:html -->\n<div class="kf-band"><img src="{src}" alt="{alt}"><div class="kf-band-cap">{cap}</div></div>\n<!-- /wp:html -->\n'


def cards(items, cls="kf-card"):
    inner = ""
    for i, (t, d) in enumerate(items, 1):
        inner += grp(cls, f'<p class="kf-num">{i}</p>\n' + hx(3, t) + pp(d))
    return f'<!-- wp:group {json.dumps({"className": "kf-grid"})} -->\n<div class="wp-block-group kf-grid">{inner}</div>\n<!-- /wp:group -->\n'


def section(cls, inner):
    return grp(f"kf-section {cls}".strip(), grp("kf-container", inner))


def hero(art):
    body = (pp(art["kicker"], "kf-kicker") + hx(1, art["hero_title"]) +
            pp(art["hero_sub"]) + btn(art["hero_cta"], "/contact/"))
    if art.get("note"):
        body += pp(art["note"], "kf-hero-note")
    return grp("kf-hero", grp("kf-container", body))


def stats(items):
    cells = "".join(grp("kf-stat", f'<p><b>{n}</b></p>' + pp(l)) for n, l in items)
    return grp("kf-stats", cells)


def cta(art):
    return section("tight", grp("kf-cta",
        hx(2, art["cta_title"]) + pp(art["cta_text"]) + btn(art["cta_btn"], "/contact/")))


def split_block(title, text, items):
    left = hx(2, title) + pp(text)
    right = grp("kf-panel", ul(items))
    return grp("kf-split", left + right)


# ---------------------------------------------------------------- 行业数据
IND = {}

IND["preschool"] = {
    "palette": {"primary": "#f26522", "primary-dark": "#c94f16", "accent": "#ffc02e",
                "bg": "#fffaf3", "surface": "#ffffff", "ink": "#2b2118", "muted": "#7a6a5c"},
    "kicker": "Singapore Preschool · Ages 18 months – 6 years",
    "hero_title": "Where Little Learners Bloom",
    "hero_sub": "A play-based, bilingual preschool where curiosity comes first — and every child is known by name.",
    "hero_cta": "Book a School Tour",
    "note": "Now enrolling for 2027 · Bukit Timah & Woodlands",
    "tagline": "Play-based bilingual preschool in Singapore",
    "services_slug": "programmes",
    "services_title": "Our Programmes",
    "features": [
        ("Playgroup", "A gentle first step for 18 months to 2 years, built around sensory play, routines and secure attachment."),
        ("Nursery & Kindergarten", "N1 to K2, where early literacy and numeracy grow out of projects children choose themselves."),
        ("Bilingual Immersion", "English and Mandarin woven through the day by native-speaking educators — not taught as separate subjects."),
    ],
    "about_title": "A school small enough to know every child",
    "about_text": "We opened our first campus in 2013 with twelve children and one belief: that children learn best when they feel safe enough to be curious. Today we run two campuses, still cap every class at a 1:8 ratio, and still write a personal note home for every child each term.",
    "list_title": "What parents tell us matters",
    "list_items": ["1:8 teacher-to-child ratio in every class",
                   "Native-speaking English and Mandarin educators",
                   "Daily photo and note updates to parents",
                   "Nut-free, freshly prepared meals on site",
                   "Outdoor play every day, rain or shine"],
    "stats": [("18m–6y", "Age range"), ("1:8", "Teacher ratio"), ("2", "Campuses"), ("12", "Years")],
    "cta_title": "Come see a morning in progress",
    "cta_text": "Tours run every Tuesday and Thursday at 9:30am. Bring your child — they usually enjoy it more than the adults do.",
    "cta_btn": "Book a Tour",
    "services_intro": "Five programmes, one continuous journey from first separation to Primary 1.",
    "services_items": ["Playgroup · 18 months – 2 years",
                       "Nursery 1 · 2 – 3 years",
                       "Nursery 2 · 3 – 4 years",
                       "Kindergarten 1 · 4 – 5 years",
                       "Kindergarten 2 · 5 – 6 years"],
    "about_body": "Our days follow a rhythm rather than a timetable: arrival and free play, circle time, outdoor exploration, lunch, rest, then project work in the afternoon. Mandarin is spoken in the morning, English in the afternoon, and both are used naturally rather than drilled.",
    "contact_note": "Visits are by appointment so we can keep the classrooms calm.",
}

IND["restaurant"] = {
    "palette": {"primary": "#7a1f2b", "primary-dark": "#5a1620", "accent": "#d9a441",
                "bg": "#fbf7f2", "surface": "#ffffff", "ink": "#2a1f1c", "muted": "#7b6a63"},
    "kicker": "Modern Asian Kitchen · Singapore",
    "hero_title": "Honest Food, Slow Evenings",
    "hero_sub": "A neighbourhood kitchen serving seasonal plates, natural wine and a room that feels like someone's home.",
    "hero_cta": "Reserve a Table",
    "note": "Tuesday to Sunday · 6pm till late · 12 Club Street",
    "tagline": "Modern Asian kitchen in Singapore",
    "services_slug": "menu",
    "services_title": "The Menu",
    "features": [
        ("Small Plates", "Designed to be shared — six to eight plates between two people is about right."),
        ("Seasonal Cooking", "The menu changes every six weeks with what the market gives us that week."),
        ("Private Dining", "The back room seats fourteen, with its own menu and its own pace."),
    ],
    "about_title": "Cooked by people who eat here too",
    "about_text": "We opened in 2014 with a single wood-fired oven and a short menu. A decade later the oven is still there, the menu is still short, and most of the team has been with us for more than four years.",
    "list_title": "Good to know",
    "list_items": ["Walk-ins welcome at the bar", "Vegetarian menu available",
                   "Corkage $35 per bottle", "Private room for up to 14",
                   "Last seating at 10pm"],
    "stats": [("2014", "Opened"), ("40", "Seats"), ("6", "Weeks per menu"), ("4.8", "Guest rating")],
    "cta_title": "Book your table",
    "cta_text": "Reservations open 30 days ahead. For groups over eight, drop us a note and we'll sort something out.",
    "cta_btn": "Reserve",
    "services_intro": "Everything is cooked to order. Ask the team what came in this morning.",
    "services_items": ["Raw & cured — market fish, citrus, herbs",
                       "Wood-fired vegetables — charred, dressed, shared",
                       "Slow-cooked meats — for two or four",
                       "Rice & noodles — the heart of the table",
                       "Desserts — three, always the same three"],
    "about_body": "Our kitchen buys whole animals and whole crates of vegetables, then writes the menu around what arrives. That means a dish you loved last month may be gone — we think that's the point.",
    "contact_note": "For same-day bookings, calling is faster than email.",
}

IND["law"] = {
    "palette": {"primary": "#14284b", "primary-dark": "#0d1b34", "accent": "#b08d57",
                "bg": "#f7f8fa", "surface": "#ffffff", "ink": "#14202e", "muted": "#5f6b7a"},
    "kicker": "Corporate & Family Law · Singapore",
    "hero_title": "Clear Advice. Quiet Confidence.",
    "hero_sub": "We advise founders, families and boards on the decisions that are hard to undo.",
    "hero_cta": "Request a Consultation",
    "note": "Offices in Raffles Place · Called to the Singapore Bar",
    "tagline": "Corporate and family law practice in Singapore",
    "services_slug": "practice-areas",
    "services_title": "Practice Areas",
    "features": [
        ("Corporate & Commercial", "Incorporation, shareholder agreements, funding rounds and the contracts that hold them together."),
        ("Family & Matrimonial", "Separation, divorce and custody handled with discretion and a clear plan."),
        ("Dispute Resolution", "Negotiation first, litigation when it is the only route left."),
    ],
    "about_title": "Small firm, senior attention",
    "about_text": "Every matter is handled by a partner from the first meeting to the last. We take on fewer cases than larger firms so that the person you meet is the person who does the work.",
    "list_title": "How we work",
    "list_items": ["Fixed fees quoted before we start",
                   "A named partner on every matter",
                   "Plain-language advice, written down",
                   "Response within one business day",
                   "Confidentiality agreements by default"],
    "stats": [("18", "Years"), ("600+", "Matters"), ("1", "Day response"), ("2", "Languages")],
    "cta_title": "Start with a conversation",
    "cta_text": "A 30-minute introductory call, no charge, to work out whether we are the right firm for the matter.",
    "cta_btn": "Request a Consultation",
    "services_intro": "We cover the areas where a wrong document costs more than a right lawyer.",
    "services_items": ["Company incorporation and restructuring",
                       "Shareholder and joint-venture agreements",
                       "Employment and director duties",
                       "Divorce, custody and ancillary matters",
                       "Commercial and shareholder disputes"],
    "about_body": "We are a four-lawyer practice by choice. That size lets us keep the whole file in one head, answer the phone ourselves, and give advice that fits the client's actual situation rather than a template.",
    "contact_note": "Initial consultations are confidential and without obligation.",
}

IND["trading"] = {
    "palette": {"primary": "#0f4c5c", "primary-dark": "#0a3540", "accent": "#f4a261",
                "bg": "#f5f7f6", "surface": "#ffffff", "ink": "#132a30", "muted": "#5c6f74"},
    "kicker": "Import · Export · Distribution",
    "hero_title": "From Port to Shelf, Without Surprises",
    "hero_sub": "We source, consolidate and deliver across Southeast Asia — with paperwork that clears the first time.",
    "hero_cta": "Request a Quote",
    "note": "Singapore HQ · Warehousing in Jurong · Coverage across ASEAN",
    "tagline": "Trading and distribution across Southeast Asia",
    "services_slug": "products",
    "services_title": "What We Handle",
    "features": [
        ("Sourcing", "Direct relationships with manufacturers in China, Vietnam and Indonesia, vetted in person."),
        ("Logistics", "Consolidation, customs clearance and last-mile delivery under one invoice."),
        ("Compliance", "HS classification, permits and labelling checked before the container ships."),
    ],
    "about_title": "Ten years of containers, no surprises",
    "about_text": "We started as a two-person sourcing desk for a single retailer. Today we move about 400 containers a year for 30 regular clients, and we still quote every shipment by hand.",
    "list_title": "Why clients stay",
    "list_items": ["Quotes within 24 hours", "One account manager per client",
                   "Customs clearance handled in-house", "Bonded warehousing available",
                   "Consolidation from multiple suppliers"],
    "stats": [("400+", "Containers a year"), ("30", "Regular clients"), ("3", "Source countries"), ("24h", "Quote turnaround")],
    "cta_title": "Send us your shipment",
    "cta_text": "Tell us what you are moving, from where and to where. We will come back with a landed cost, not a guess.",
    "cta_btn": "Request a Quote",
    "services_intro": "We work with a fixed set of categories where we know the rules cold.",
    "services_items": ["FMCG and household goods",
                       "Building materials and hardware",
                       "Electronics and components",
                       "Packaging and printed materials",
                       "Cold-chain and temperature-controlled goods"],
    "about_body": "Our team sits in Singapore and visits suppliers quarterly. We do not take on a product line we have not seen made, because the cost of a bad batch is always higher than the cost of a flight.",
    "contact_note": "Include product photos and target quantity for a faster quote.",
}

IND["tech"] = {
    "palette": {"primary": "#3b2fd4", "primary-dark": "#2a2099", "accent": "#00c2a8",
                "bg": "#f6f7fb", "surface": "#ffffff", "ink": "#191a2e", "muted": "#5f6279"},
    "kicker": "Software & Data · Singapore",
    "hero_title": "Software That Keeps Up With You",
    "hero_sub": "We build and run the internal tools, data pipelines and customer products that growing companies depend on.",
    "hero_cta": "Talk to an Engineer",
    "note": "Product engineering · Data & AI · Cloud reliability",
    "tagline": "Software engineering and data consultancy",
    "services_slug": "solutions",
    "services_title": "What We Build",
    "features": [
        ("Product Engineering", "From first prototype to a product your team can maintain without us."),
        ("Data & AI", "Pipelines, reporting and models that answer questions people actually ask."),
        ("Cloud & Reliability", "Migration, cost reduction and on-call that does not page you at 3am."),
    ],
    "about_title": "Engineers who have run what they build",
    "about_text": "Our team has operated the systems we now design — on-call rotations, incident reviews, the lot. That changes the advice we give, mostly toward simpler.",
    "list_title": "How we engage",
    "list_items": ["Two-week discovery before any estimate",
                   "Fixed-scope or monthly retainer",
                   "Code and infrastructure in your accounts",
                   "Handover documentation as a deliverable",
                   "No lock-in on day one of year two"],
    "stats": [("40+", "Projects"), ("6", "Engineers"), ("2wk", "Discovery"), ("100%", "Code handed over")],
    "cta_title": "Tell us what is slowing you down",
    "cta_text": "A 30-minute call with an engineer, not a salesperson. We will tell you if we are the wrong fit.",
    "cta_btn": "Talk to an Engineer",
    "services_intro": "We take on work where the problem is understood and the team wants to move.",
    "services_items": ["Internal tools and operations dashboards",
                       "Customer-facing web applications",
                       "Data warehousing and reporting",
                       "Cloud migration and cost review",
                       "Reliability and incident response setup"],
    "about_body": "We work in small teams, embed with the client, and write down what we learn. Most engagements end with your engineers owning the system — that is the success condition.",
    "contact_note": "Include your stack and timeline for a faster reply.",
}



IND["littlegems"] = {
    "palette": {"primary": "#7a2e8e", "primary-dark": "#5a1f6b", "accent": "#ff4f9a",
                "bg": "#fdf7fb", "surface": "#ffffff", "ink": "#2a1b2e", "muted": "#6e5c74"},
    "tagline": "Preschool in Jalan Eunos · Little Gems, Shining Minds",
}

LG_MENU = ["home", "about", "programme", "curriculum", "timetable", "fees", "contact"]

QUOTES = [
    ("When my elder brother tried to hit me, I did not retaliate, but instead I focused on my breathing exercise.", "Ryan Choo, K2"),
    ("After practicing the breathing exercise, I can sleep very well.", "K1 student"),
    ("I told my mommy I love her and I hugged her.", "N2 student"),
    ("The morning fights were greatly reduced within the first week... He is now happy to go to school. Dedicated, caring and infinitely patient, the teachers are the true gems.", "Mother of Eldrick Yip (4)"),
    ("My Little Gems offers a unique environment where children are free to play in the classroom when they arrive early. It provides the most conducive platform for children to build their confidence.", "Mother of Everett Chua (3)"),
]


def q(text, by, initial=""):
    av = rawhtml(f'<div class="kf-avatar">{initial}</div>') if initial else ""
    return grp("kf-quote", av + pp(f"\u201c{text}\u201d") + pp(f"\u2014 {by}", "kf-by"))


def build_littlegems(company, domain):
    home = (
        grp("kf-hero", grp("kf-container", grp("kf-hero-grid",
            grp("kf-hero-copy",
                pp("Jalan Eunos \u00b7 Preschool \u00b7 18 months \u2013 6 years", "kf-kicker") +
                hx(1, "Little Gems, Shining Minds") +
                pp("Every child here is a gem: precious, and ready to shine. We grow Character, Concentration "
                   "and Competency so children leave us confident, focused and independent.") +
                btn("Book a Visit", "/contact/") +
                rawhtml('<div class="kf-badges"><span class="kf-badge">Full day 7am\u20137pm</span>'
                        '<span class="kf-badge">Half day 7am\u20131pm</span>'
                        '<span class="kf-badge">38 Jalan Eunos</span></div>')) +
            rawhtml('<div class="kf-art"><div class="blob b1"></div><div class="blob b2"></div>'
                    '<div class="ring"></div><div class="gem g1"></div><div class="gem g2"></div><div class="gem g3"></div></div>'))))
        + section("alt", grp("kf-center", pp("Our approach", "kf-eyebrow") + hx(2, "Three gems in every child") +
                  pp("The name says it: Character, Concentration, Competency.", "kf-lead")) +
                  cards([("Character", "Grounded in solid character \u2014 built through questioning, observing, role play, stories and songs."),
                         ("Concentration", "Enhanced concentration \u2014 child-appropriate techniques that help children settle, focus and stay with a task."),
                         ("Competency", "Multiple competency \u2014 a broad core curriculum plus enrichment, with a strong focus on Chinese.")], "kf-card gem"))
        + section("tight", band("/wp-content/uploads/kampong/lg-reading.jpg",
                                "A morning at My Little Gems", "Teacher reading with children"))
        + section("", split_block("A school that welcomes parents",
                  "Parents are partners here. We tell you what your child learned each week so it can be reinforced at home.",
                  ["Parent\u2013teacher partnership encouraged",
                   "Experienced educators as facilitators and co-researchers",
                   "Home-like, child-centred environment",
                   "Experiential, participatory learning",
                   "Strong Chinese focus for English-speaking families"]))
        + section("alt tight", grp("kf-cta", hx(2, "Our vision") +
                  pp("Inspiring little minds to achieve their full potential.") +
                  btn("Book a Visit", "/contact/")))
    )

    about = (
        section("alt", pp("About us", "kf-eyebrow") + hx(2, "Our vision and mission") +
                pp("Inspiring little minds to achieve their full potential.", "kf-lead") +
                grp("kf-panel", hx(3, "The GEMs in every child") +
                    ul(["G \u2014 Grounded in solid Character",
                        "E \u2014 Enhanced Concentration",
                        "M \u2014 Multiple Competency",
                        "S \u2014 Socially Responsible"])))
        + section("", hx(2, "Our logo") +
                  pp("Three smiley faces \u2014 the triple gems in every child: Character, Concentration and "
                     "Competency. Fully developed, they allow a child to realise their highest potential."))
        + section("tight", band("/wp-content/uploads/kampong/lg-desk.jpg",
                                "Children at work", "Children writing at a table"))
        + section("alt", hx(2, "Our environment") +
                  pp("A welcoming, friendly and child-centred environment, with the same nurturing qualities as a "
                     "home. Every child feels comforted and confident to begin their first independent experience "
                     "away from home."))
        + section("", pp('See our <a href="/environment/">campus</a>, or read <a href="/testimonials/">what parents say</a>.'))
        + cta({"cta_title": "Come and see the school",
               "cta_text": "Visits are by appointment. Call, or send us a WhatsApp message and we will arrange a time.",
               "cta_btn": "Book a Visit"})
    )

    programme = (
        section("alt", pp("Programme", "kf-eyebrow") + hx(2, "A broad-based core curriculum") +
                pp("We develop Character, Concentration and Competency through experiential and active "
                   "participatory learning. Students investigate topics of interest, gather information and "
                   "present their findings \u2014 becoming skilled learners who can seek out and process "
                   "information and create new ideas themselves.", "kf-lead") +
                hx(3, "Programme highlights") +
                ul(["Experiential learning where students plan, develop and assess their own work",
                    "Character building through questioning, observing, role play, stories and songs",
                    "Concentration enhancement through fun activities",
                    "Competency acquisition through a strong core curriculum and enrichment",
                    "Strong focus on Chinese for children from English-speaking families"]))
        + section("", hx(2, "Classes") +
                  grp("kf-split",
                      grp("kf-panel", hx(3, "Full Day") + pp("Monday to Friday") + pp("7am \u2013 7pm")) +
                      grp("kf-panel", hx(3, "Half Day") + pp("Monday to Friday") + pp("7am \u2013 1pm"))) +
                  pp("Our preschool programme caters to children aged 18 months to 6 years."))
        + section("alt", hx(2, "Enrichment") +
                  pp("Supplementary enrichment programmes run alongside the core curriculum, building competency "
                     "and giving children room to explore what they enjoy."))
        + cta({"cta_title": "Ask about a place",
               "cta_text": "Tell us your child's age and we will let you know what is available.",
               "cta_btn": "Contact Us"})
    )

    curriculum = (
        section("alt", pp("Curriculum", "kf-eyebrow") + hx(2, "Character, Concentration, Competency") +
                pp("Three strands, taught together rather than in separate slots.", "kf-lead") +
                cards([("Character", "Built through questioning, observing, role play, stories and songs, and through "
                                     "the everyday habits of a calm, caring classroom."),
                       ("Concentration", "Practised daily with child-appropriate techniques, so children learn to "
                                         "settle, focus and stay with a task."),
                       ("Competency", "A strong core curriculum plus enrichment, with a deliberate focus on Chinese "
                                      "for children from English-speaking homes.")]))
        + section("", hx(2, "What a day looks like") +
                  pp("Children move between teacher-led sessions, project work, outdoor play and rest. Older "
                     "children present their findings to the class, which is how confidence and spoken language grow."))
        + cta({"cta_title": "See it for yourself",
               "cta_text": "A morning visit shows more than any page can.",
               "cta_btn": "Book a Visit"})
    )

    testi = (section("alt", pp("Testimonials", "kf-eyebrow") + hx(2, "In their own words") +
                     pp("What children and parents say about My Little Gems.", "kf-lead") +
                     grp("kf-quote-grid", q(QUOTES[0][0], QUOTES[0][1], "R") + q(QUOTES[1][0], QUOTES[1][1], "K1") + q(QUOTES[2][0], QUOTES[2][1], "N2")))
             + section("", hx(2, "From parents") + q(QUOTES[3][0], QUOTES[3][1], "EY") + q(QUOTES[4][0], QUOTES[4][1], "EC"))
             + cta({"cta_title": "Book a visit",
                    "cta_text": "Meet the teachers and see a morning in progress.",
                    "cta_btn": "Book a Visit"}))

    contact = section("alt", pp("Contact", "kf-eyebrow") + hx(2, "Visit us in Jalan Eunos") +
                      pp("38 Jalan Eunos, Singapore 419500", "kf-lead") +
                      grp("kf-split",
                          grp("kf-panel", hx(3, "Get in touch") +
                              pp('Phone: <a href="tel:+6567487483">+65 6748 7483</a>') +
                              pp('WhatsApp: <a href="https://wa.me/6590609660">+65 9060 9660</a>') +
                              pp('Email: <a href="mailto:info@my-littlegems.com">info@my-littlegems.com</a>')) +
                          grp("kf-panel", hx(3, "Opening hours") +
                              pp("Monday to Friday") + pp("7:00am \u2013 7:00pm") +
                              pp("Visits by appointment."))))


    environment = (
        section("alt", pp("Our campus", "kf-eyebrow") + hx(2, "A home away from home") +
                pp("Warm, child-centred spaces at 38 Jalan Eunos \u2014 low shelves, soft corners and room to move.",
                   "kf-lead") +
                cards([("Classrooms", "Bright rooms with low shelving so children can reach what they need and put it back themselves."),
                       ("Outdoor play", "Daily outdoor time, rain or shine, because gross motor play settles the body for focused work."),
                       ("Rest & meals", "A quiet nap room and freshly prepared meals eaten together at the table.")], "kf-card gem"))
        + section("", hx(2, "A look around") +
                  gallery([("s1", "Classroom", "/wp-content/uploads/kampong/lg-classroom.jpg"),
                           ("s2", "Outdoor play", "/wp-content/uploads/kampong/lg-outdoor.jpg"),
                           ("s3", "Art & making", "/wp-content/uploads/kampong/lg-art.jpg")]) +
                  pp("Placeholder photographs from a free stock library \u2014 to be replaced with photos of our Jalan Eunos campus.", "kf-note"))
        + cta({"cta_title": "See the space yourself",
               "cta_text": "Tours run on weekday mornings, when the classrooms are in full swing.",
               "cta_btn": "Book a Visit"})
    )

    timetable = (
        section("alt", pp("A day with us", "kf-eyebrow") + hx(2, "Sample daily schedule") +
                pp("Children follow the same rhythm each day \u2014 predictability is what makes them feel safe "
                   "enough to explore.", "kf-lead") +
                table(["Time", "Activity"], [
                    ("7:00 \u2013 9:00", "Arrival and free play"),
                    ("9:00 \u2013 9:30", "Circle time, songs and news"),
                    ("9:30 \u2013 10:15", "Chinese language session"),
                    ("10:15 \u2013 10:45", "Snack"),
                    ("10:45 \u2013 11:30", "Project work and discovery"),
                    ("11:30 \u2013 12:15", "Outdoor play"),
                    ("12:15 \u2013 13:00", "Lunch"),
                    ("13:00", "Half day dismissal"),
                    ("13:30 \u2013 15:00", "Rest and quiet time"),
                    ("15:00 \u2013 15:30", "Snack"),
                    ("15:30 \u2013 16:30", "Enrichment and creative play"),
                    ("16:30 \u2013 19:00", "Free play and pick-up"),
                ]) +
                pp("Times are indicative and adjust with the age group.", "kf-note"))
        + section("", hx(2, "Half day or full day") +
                  grp("kf-split",
                      grp("kf-panel", hx(3, "Half Day") + pp("7am \u2013 1pm") +
                         pp("Morning programme, lunch and dismissal before rest time.")) +
                      grp("kf-panel", hx(3, "Full Day") + pp("7am \u2013 7pm") +
                         pp("The full rhythm, including rest, afternoon enrichment and pick-up any time before 7pm."))))
        + cta({"cta_title": "Ask about a place",
               "cta_text": "Tell us your child's age and preferred schedule.",
               "cta_btn": "Contact Us"})
    )

    fees = (
        section("alt", pp("Fees", "kf-eyebrow") + hx(2, "Fee schedule") +
                pp("Indicative figures so you can see the structure. Final fees are confirmed on enquiry.", "kf-lead") +
                table(["Item", "Amount", "Notes"], [
                    ("Registration (one-time)", "S$100*", "Payable on enrolment"),
                    ("Full Day \u00b7 monthly", "S$1,200*", "7am \u2013 7pm, meals included"),
                    ("Half Day \u00b7 monthly", "S$850*", "7am \u2013 1pm, lunch included"),
                    ("Enrichment \u00b7 per term", "S$300*", "Optional"),
                ]) +
                pp("* Sample figures for layout only \u2014 to be replaced with the school's actual fee schedule.", "kf-note"))
        + section("", hx(2, "What is included") +
                  ul(["All meals and snacks prepared on site",
                      "Learning materials and art supplies",
                      "Termly progress updates and parent-teacher meetings",
                      "Chinese language sessions as part of the core day"]))
        + cta({"cta_title": "Get the current fee schedule",
               "cta_text": "Fees vary by programme and age group. Call or WhatsApp us for the current schedule.",
               "cta_btn": "Contact Us"})
    )

    return [
        {"slug": "home", "title": "Home", "content": home},
        {"slug": "about", "title": "About Us", "content": about},
        {"slug": "environment", "title": "Our Campus", "content": environment},
        {"slug": "programme", "title": "Our Programme", "content": programme},
        {"slug": "curriculum", "title": "Our Curriculum", "content": curriculum},
        {"slug": "timetable", "title": "Daily Schedule", "content": timetable},
        {"slug": "testimonials", "title": "Testimonials", "content": testi},
        {"slug": "fees", "title": "Fees", "content": fees},
        {"slug": "contact", "title": "Contact Us", "content": contact},
    ]



# ---------------------------------------------------------------- 设计令牌
DESIGN_SHAPE = {
    "restaurant": {"radius": "12px", "button": "999px", "heading": "serif",  "pad": "80px"},
    "law":        {"radius": "6px",  "button": "4px",   "heading": "serif",  "pad": "84px"},
    "trading":    {"radius": "10px", "button": "6px",   "heading": "sans",   "pad": "76px"},
    "tech":       {"radius": "14px", "button": "10px",  "heading": "sans",   "pad": "76px"},
    "preschool":  {"radius": "22px", "button": "999px", "heading": "rounded","pad": "84px"},
    "littlegems": {"radius": "18px", "button": "999px", "heading": "rounded","pad": "78px"},
}


def build_design(key, art):
    """行业预设 → 设计令牌（palette/shape/type/layout/photos）"""
    pal = art["palette"]
    shape = DESIGN_SHAPE.get(key, DESIGN_SHAPE["tech"])
    return {
        "preset": key,
        "palette": {
            "primary": pal.get("primary"),
            "primaryDark": pal.get("primary-dark") or pal.get("primary"),
            "accent": pal.get("accent"),
            "bg": pal.get("bg"),
            "surface": pal.get("surface", "#ffffff"),
            "ink": pal.get("ink"),
            "muted": pal.get("muted"),
            "deep": pal.get("deep") or pal.get("primaryDark") or pal.get("primary-dark"),
        },
        "shape": {"radius": shape["radius"], "button": shape["button"]},
        "type": {"heading": shape["heading"]},
        "layout": {"pad": shape["pad"]},
        "photos": {"overlay": "0.46"},
    }




# ---------------------------------------------------------------- 页面 spec（区块列表）
def spec_littlegems(company, domain):
    P = "/wp-content/uploads/kampong"
    gems = [("Character", "Grounded in solid character \u2014 built through questioning, observing, role play, stories and songs."),
            ("Concentration", "Enhanced concentration \u2014 child-appropriate techniques that help children settle, focus and stay with a task."),
            ("Competency", "Multiple competency \u2014 a broad core curriculum plus enrichment, with a strong focus on Chinese.")]

    home = [
        {"type": "hero", "art": True,
         "kicker": "Jalan Eunos \u00b7 Preschool \u00b7 18 months \u2013 6 years",
         "title": "Little Gems, Shining Minds",
         "text": "Every child here is a gem: precious, and ready to shine. We grow Character, Concentration and "
                 "Competency so children leave us confident, focused and independent.",
         "cta": {"label": "Book a Visit", "href": "/contact/"},
         "badges": ["Full day 7am\u20137pm", "Half day 7am\u20131pm", "38 Jalan Eunos"]},
        {"type": "cards", "bg": "alt", "center": True, "accent": True,
         "eyebrow": "Our approach", "title": "Three gems in every child",
         "lead": "The name says it: Character, Concentration, Competency.",
         "items": [{"title": t, "text": d} for t, d in gems]},
        {"type": "band", "src": f"{P}/lg-reading.jpg", "alt": "Teacher reading with children",
         "caption": "A morning at My Little Gems"},
        {"type": "split", "title": "A school that welcomes parents",
         "text": "Parents are partners here. We tell you what your child learned each week so it can be "
                 "reinforced at home.",
         "items": ["Parent\u2013teacher partnership encouraged",
                   "Experienced educators as facilitators and co-researchers",
                   "Home-like, child-centred environment",
                   "Experiential, participatory learning",
                   "Strong Chinese focus for English-speaking families"]},
        {"type": "cta", "title": "Our vision",
         "text": "Inspiring little minds to achieve their full potential.", "button": "Book a Visit"},
    ]

    about = [
        {"type": "split", "bg": "alt", "eyebrow": "About us", "title": "Our vision and mission",
         "text": "Inspiring little minds to achieve their full potential.",
         "items": ["G \u2014 Grounded in solid Character", "E \u2014 Enhanced Concentration",
                   "M \u2014 Multiple Competency", "S \u2014 Socially Responsible"]},
        {"type": "rich", "bg": "", "html": "<h2>Our logo</h2><p>Three smiley faces \u2014 the triple gems in every "
                                           "child: Character, Concentration and Competency.</p>"},
        {"type": "band", "src": f"{P}/lg-desk.jpg", "alt": "Children writing at a table",
         "caption": "Children at work"},
        {"type": "list", "bg": "alt", "title": "Our environment",
         "lead": "A welcoming, child-centred environment with the same nurturing qualities as a home.",
         "items": ["Every child feels comforted and confident away from home",
                   "Small groups and consistent routines",
                   "Space to move, make and rest"]},
        {"type": "cta", "title": "Come and see the school",
         "text": "Visits are by appointment. Call, or send us a WhatsApp message.", "button": "Book a Visit"},
    ]

    environment = [
        {"type": "cards", "bg": "alt", "accent": True, "eyebrow": "Our campus",
         "title": "A home away from home",
         "lead": "Warm, child-centred spaces at 38 Jalan Eunos \u2014 low shelves, soft corners and room to move.",
         "items": [{"title": "Classrooms", "text": "Bright rooms with low shelving so children can reach what they need."},
                   {"title": "Outdoor play", "text": "Daily outdoor time, rain or shine."},
                   {"title": "Rest & meals", "text": "A quiet nap room and meals eaten together at the table."}]},
        {"type": "gallery", "bg": "", "title": "A look around",
         "items": [{"label": "Classroom", "src": f"{P}/lg-classroom.jpg"},
                   {"label": "Outdoor play", "src": f"{P}/lg-outdoor.jpg"},
                   {"label": "Art & making", "src": f"{P}/lg-art.jpg"}],
         "note": "Placeholder photographs from a free stock library \u2014 to be replaced with our campus photos."},
        {"type": "cta", "title": "See the space yourself",
         "text": "Tours run on weekday mornings, when the classrooms are in full swing.", "button": "Book a Visit"},
    ]

    programme = [
        {"type": "list", "bg": "alt", "eyebrow": "Programme", "title": "A broad-based core curriculum",
         "lead": "We develop Character, Concentration and Competency through experiential and active "
                 "participatory learning.",
         "items": ["Experiential learning where students plan, develop and assess their own work",
                   "Character building through questioning, observing, role play, stories and songs",
                   "Concentration enhancement through fun activities",
                   "Competency acquisition through a strong core curriculum and enrichment",
                   "Strong focus on Chinese for children from English-speaking families"]},
        {"type": "table", "bg": "", "title": "Classes",
         "headers": ["Programme", "Days", "Hours"],
         "rows": [["Full Day", "Monday \u2013 Friday", "7:00am \u2013 7:00pm"],
                  ["Half Day", "Monday \u2013 Friday", "7:00am \u2013 1:00pm"],
                  ["Age range", "18 months \u2013 6 years", ""]],
         "note": "Contact us for availability in your child's age group."},
        {"type": "cta", "title": "Ask about a place",
         "text": "Tell us your child's age and we will let you know what is available.", "button": "Contact Us"},
    ]

    curriculum = [
        {"type": "cards", "bg": "alt", "accent": True, "eyebrow": "Curriculum",
         "title": "Character, Concentration, Competency",
         "lead": "Three strands, taught together rather than in separate slots.",
         "items": [{"title": "Character", "text": "Built through questioning, observing, role play, stories and songs, and through the everyday habits of a calm, caring classroom."},
                   {"title": "Concentration", "text": "Practised daily with child-appropriate techniques, so children learn to settle and stay with a task."},
                   {"title": "Competency", "text": "A strong core curriculum plus enrichment, with a deliberate focus on Chinese."}]},
        {"type": "rich", "bg": "", "html": "<h2>What a day looks like</h2><p>Children move between teacher-led "
                                           "sessions, project work, outdoor play and rest. Older children present "
                                           "their findings to the class \u2014 that is how confidence and spoken "
                                           "language grow.</p>"},
        {"type": "cta", "title": "See it for yourself", "text": "A morning visit shows more than any page can.",
         "button": "Book a Visit"},
    ]

    testimonials = [
        {"type": "quotes", "bg": "alt", "grid": True, "eyebrow": "Testimonials",
         "title": "In their own words", "lead": "What children and parents say about My Little Gems.",
         "items": [{"text": "When my elder brother tried to hit me, I did not retaliate, but instead I focused on my breathing exercise.", "by": "Ryan Choo, K2", "initial": "R"},
                   {"text": "After practicing the breathing exercise, I can sleep very well.", "by": "K1 student", "initial": "K1"},
                   {"text": "I told my mommy I love her and I hugged her.", "by": "N2 student", "initial": "N2"}]},
        {"type": "quotes", "bg": "", "grid": False, "title": "From parents",
         "items": [{"text": "The morning fights were greatly reduced within the first week... He is now happy to go to school. Dedicated, caring and infinitely patient, the teachers are the true gems.", "by": "Mother of Eldrick Yip (4)", "initial": "EY"},
                   {"text": "My Little Gems offers a unique environment where children are free to play in the classroom when they arrive early. It provides the most conducive platform for children to build their confidence.", "by": "Mother of Everett Chua (3)", "initial": "EC"}]},
        {"type": "cta", "title": "Book a visit", "text": "Meet the teachers and see a morning in progress.",
         "button": "Book a Visit"},
    ]

    timetable = [
        {"type": "table", "bg": "alt", "eyebrow": "A day with us", "title": "Sample daily schedule",
         "lead": "Children follow the same rhythm each day \u2014 predictability is what makes them feel safe enough to explore.",
         "headers": ["Time", "Activity"],
         "rows": [["7:00 \u2013 9:00", "Arrival and free play"], ["9:00 \u2013 9:30", "Circle time, songs and news"],
                  ["9:30 \u2013 10:15", "Chinese language session"], ["10:15 \u2013 10:45", "Snack"],
                  ["10:45 \u2013 11:30", "Project work and discovery"], ["11:30 \u2013 12:15", "Outdoor play"],
                  ["12:15 \u2013 13:00", "Lunch"], ["13:00", "Half day dismissal"],
                  ["13:30 \u2013 15:00", "Rest and quiet time"], ["15:00 \u2013 15:30", "Snack"],
                  ["15:30 \u2013 16:30", "Enrichment and creative play"], ["16:30 \u2013 19:00", "Free play and pick-up"]],
         "note": "Times are indicative and adjust with the age group."},
        {"type": "split", "bg": "", "title": "Half day or full day",
         "text": "Both follow the same rhythm; the full day adds rest, afternoon enrichment and a later pick-up.",
         "items": ["Half Day: 7:00am \u2013 1:00pm", "Full Day: 7:00am \u2013 7:00pm"]},
        {"type": "cta", "title": "Ask about a place", "text": "Tell us your child's age and preferred schedule.",
         "button": "Contact Us"},
    ]

    fees = [
        {"type": "table", "bg": "alt", "eyebrow": "Fees", "title": "Fee schedule",
         "lead": "Indicative figures so you can see the structure. Final fees are confirmed on enquiry.",
         "headers": ["Item", "Amount", "Notes"],
         "rows": [["Registration (one-time)", "S$100*", "Payable on enrolment"],
                  ["Full Day \u00b7 monthly", "S$1,200*", "7am \u2013 7pm, meals included"],
                  ["Half Day \u00b7 monthly", "S$850*", "7am \u2013 1pm, lunch included"],
                  ["Enrichment \u00b7 per term", "S$300*", "Optional"]],
         "note": "* Sample figures for layout only \u2014 to be replaced with the school's actual fee schedule."},
        {"type": "list", "bg": "", "title": "What is included",
         "items": ["All meals and snacks prepared on site", "Learning materials and art supplies",
                   "Termly progress updates and parent-teacher meetings",
                   "Chinese language sessions as part of the core day"]},
        {"type": "cta", "title": "Get the current fee schedule",
         "text": "Fees vary by programme and age group. Call or WhatsApp us.", "button": "Contact Us"},
    ]

    contact = [
        {"type": "split", "bg": "alt", "eyebrow": "Contact", "title": "Visit us in Jalan Eunos",
         "text": "38 Jalan Eunos, Singapore 419500",
         "items": ["Phone: +65 6748 7483", "WhatsApp: +65 9060 9660",
                   "Email: info@my-littlegems.com", "Monday to Friday, 7:00am \u2013 7:00pm"]},
        {"type": "form", "bg": "", "eyebrow": "Enquiry", "title": "Book a visit or ask a question",
         "lead": "Leave your details and we will reply within one working day.",
         "submit": "Send message"},
    ]

    return [
        {"slug": "home", "title": "Home", "sections": home},
        {"slug": "about", "title": "About Us", "sections": about},
        {"slug": "environment", "title": "Our Campus", "sections": environment},
        {"slug": "programme", "title": "Our Programme", "sections": programme},
        {"slug": "curriculum", "title": "Our Curriculum", "sections": curriculum},
        {"slug": "timetable", "title": "Daily Schedule", "sections": timetable},
        {"slug": "testimonials", "title": "Testimonials", "sections": testimonials},
        {"slug": "fees", "title": "Fees", "sections": fees},
        {"slug": "contact", "title": "Contact Us", "sections": contact},
    ]


def spec_generic(art):
    home = [
        {"type": "hero", "kicker": art["kicker"], "title": art["hero_title"],
         "text": art["hero_sub"], "cta": {"label": art["hero_cta"], "href": "/contact/"},
         "badges": [b for b in [art.get("note")] if b]},
        {"type": "cards", "bg": "alt", "eyebrow": art["kicker"], "title": "Built around how you actually work",
         "lead": art.get("services_intro", ""),
         "items": [{"title": t, "text": d} for t, d in art["features"]]},
        {"type": "split", "title": art["about_title"], "text": art["about_text"], "items": art["list_items"]},
        {"type": "stats", "bg": "alt", "items": [{"value": v, "label": l} for v, l in art["stats"]]},
        {"type": "cta", "title": art["cta_title"], "text": art["cta_text"], "button": art["cta_btn"]},
    ]
    services = [
        {"type": "list", "bg": "alt", "eyebrow": "Overview", "title": art["services_title"],
         "lead": art.get("services_intro", ""), "items": art["services_items"]},
        {"type": "cta", "title": "Ready when you are", "text": art.get("contact_note", ""),
         "button": art["hero_cta"]},
    ]
    about = [
        {"type": "split", "bg": "alt", "eyebrow": "About", "title": art["about_title"],
         "text": art["about_body"], "items": art["list_items"]},
        {"type": "cta", "title": art["cta_title"], "text": art["cta_text"], "button": art["cta_btn"]},
    ]
    contact = [
        {"type": "split", "bg": "alt", "eyebrow": "Contact", "title": "Get in touch",
         "text": art.get("contact_note", ""),
         "items": ["Phone: +65 6000 0000", "Email: hello@example.sg", "Address: Singapore",
                   "Opening hours: Mon\u2013Fri, 9am\u20136pm"]},
        {"type": "form", "bg": "", "eyebrow": "Enquiry", "title": "Send us a message",
         "lead": "We reply within one working day.", "submit": "Send message"},
    ]
    return [
        {"slug": "home", "title": "Home", "sections": home},
        {"slug": art["services_slug"], "title": art["services_title"], "sections": services},
        {"slug": "about", "title": "About Us", "sections": about},
        {"slug": "contact", "title": "Contact", "sections": contact},
    ]


SCHEMA_TYPES = {
    "littlegems": "Preschool", "preschool": "Preschool", "restaurant": "Restaurant",
    "law": "LegalService", "trading": "Organization", "tech": "Organization",
}


def build_options(key, company, domain):
    base = {
        "kf_schema_type": SCHEMA_TYPES.get(key, "LocalBusiness"),
        "kf_phone": "+65 6000 0000",
        "kf_email": "hello@" + domain,
        "kf_address": "Singapore",
        "kf_cta_text": "",
    }
    if key == "littlegems":
        base.update({
            "kf_phone": "+65 6748 7483",
            "kf_email": "info@my-littlegems.com",
            "kf_address": "38 Jalan Eunos, Singapore 419500",
            "kf_cta_text": "Book a Visit",
            "kf_cta_url": "/contact/",
            "kf_cta_ghost_text": "WhatsApp",
            "kf_cta_ghost_url": "https://wa.me/6590609660",
        })
    return base


def build_spec(key, company, domain):
    if key == "littlegems":
        return spec_littlegems(company, domain)
    return spec_generic(IND[key])


# ---------------------------------------------------------------- 页面构造
def build_pages(key, company, domain):
    if key == "littlegems":
        return build_littlegems(company, domain)
    a = IND[key]
    home = (hero(a) +
            section("alt", pp(a["kicker"], "kf-eyebrow") + hx(2, "Built around how you actually work") +
                    pp(a.get("services_intro", ""), "kf-lead") + cards(a["features"])) +
            section("", split_block(a["about_title"], a["about_text"], a["list_items"])) +
            section("alt tight", stats(a["stats"])) +
            cta(a))

    services = (section("alt", pp("Overview", "kf-eyebrow") + hx(2, a["services_title"]) +
                        pp(a.get("services_intro", ""), "kf-lead") + ul(a["services_items"])) +
                section("", hx(2, "Ready when you are") + pp(a.get("contact_note", "")) + btn(a["hero_cta"], "/contact/")))

    about = (section("alt", pp("About", "kf-eyebrow") + hx(2, a["about_title"]) + pp(a["about_body"])) +
             section("", hx(2, "What you can expect") + ul(a["list_items"])) +
             cta(a))

    contact = (section("alt", pp("Contact", "kf-eyebrow") + hx(2, "Get in touch") +
                       pp(a.get("contact_note", "")) +
                       grp("kf-split", grp("kf-panel",
                           hx(3, "Reach us") +
                           pp(f'Phone: <strong>{company} · +65 6000 0000</strong>') +
                           pp(f'Email: <a href="mailto:hello@{domain}">hello@{domain}</a>') +
                           pp("Address: Singapore") +
                           pp("Opening hours: Mon–Fri, 9am–6pm")) +
                           grp("kf-panel", hx(3, "Prefer a form?") +
                               pp("A contact form and map will appear here once you connect them in the editor.")))))

    return [
        {"slug": "home", "title": "Home", "content": home},
        {"slug": a["services_slug"], "title": a["services_title"], "content": services},
        {"slug": "about", "title": "About Us", "content": about},
        {"slug": "contact", "title": "Contact", "content": contact},
    ]


PHP = r"""<?php
$d = json_decode(file_get_contents('/kfsite/site.json'), true);
if (!$d) { echo "bad site.json\n"; return; }

foreach (get_posts(['post_type' => 'post', 'numberposts' => -1, 'post_status' => 'any']) as $p) {
    wp_delete_post($p->ID, true);
}
foreach (get_posts(['post_type' => 'page', 'numberposts' => -1, 'post_status' => 'any']) as $p) {
    wp_delete_post($p->ID, true);
}

$ids = [];
foreach ($d['pages'] as $pg) {
    $id = wp_insert_post([
        'post_title'   => $pg['title'],
        'post_name'    => $pg['slug'],
        'post_content' => $pg['content'],
        'post_status'  => 'publish',
        'post_type'    => 'page',
    ], true);
    if (is_wp_error($id)) { echo "ERR page {$pg['slug']}: " . $id->get_error_message() . "\n"; continue; }
    $ids[$pg['slug']] = $id;
}

update_option('show_on_front', 'page');
update_option('page_on_front', $ids['home'] ?? 0);
update_option('blogname', $d['company']);
update_option('blogdescription', $d['tagline']);
update_option('kf_palette', json_encode($d['palette']));
if (!empty($d['design'])) { update_option('kf_design', json_encode($d['design'])); }
update_option('permalink_structure', '/%postname%/');

foreach (wp_get_nav_menus() as $m) { wp_delete_nav_menu($m->term_id); }
set_theme_mod('nav_menu_locations', []);
foreach (['primary' => 'Main Menu', 'footer' => 'Footer Menu'] as $loc => $name) {
    $menu_id = wp_create_nav_menu($name . ' ' . $loc);
    if (is_wp_error($menu_id)) { continue; }
    $order = !empty($d['menu']) ? $d['menu'] : array_keys($ids);
    foreach ($order as $slug) {
        if (empty($ids[$slug])) { continue; }
        $pid = $ids[$slug];
        if (is_wp_error(wp_update_nav_menu_item($menu_id, 0, [
            'menu-item-object-id' => $pid,
            'menu-item-object'    => 'page',
            'menu-item-type'      => 'post_type',
            'menu-item-status'    => 'publish',
            'menu-item-title'     => get_the_title($pid),
        ]))) { echo "ERR nav {$slug}\n"; }
    }
    $locations = get_theme_mod('nav_menu_locations', []);
    $locations[$loc] = $menu_id;
    set_theme_mod('nav_menu_locations', $locations);
}

update_option('kf_phone', $d['phone']);
update_option('kf_email', 'hello@' . $d['domain']);
update_option('kf_address', 'Singapore');
if (!empty($d['options'])) {
    foreach ($d['options'] as $ok => $ov) {
        update_option($ok, $ov);
    }
}

flush_rewrite_rules(true);
echo "OK pages=" . count($ids) . "\n";
"""


def main():
    if "--dump-presets" in sys.argv:
        out = {k: build_design(k, a) for k, a in IND.items()}
        (Path(__file__).parent / "design-presets.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=1))
        print("presets:", ", ".join(sorted(out)))
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", required=True)
    ap.add_argument("--industry", required=True, choices=sorted(IND))
    ap.add_argument("--company", required=True)
    ap.add_argument("--domain", default="example.sg")
    args = ap.parse_args()

    site = Path(args.site).resolve()
    if not (site / "html").exists():
        sys.exit(f"站点目录不存在: {site}")

    art = IND[args.industry]
    spec_pages = build_spec(args.industry, args.company, args.domain)
    pages = [{"slug": p["slug"], "title": p["title"],
              "content": KS.render_sections(p["sections"], site=str(site))} for p in spec_pages]

    # 主题：html 目录属于容器用户 33，需以 root 容器复制并改回属主
    rc = subprocess.run(["docker", "run", "--rm", "-u", "0",
                         "-v", f"{THEME_SRC}:/src:ro",
                         "-v", f"{site}/html:/var/www/html",
                         REG, "sh", "-c",
                         "rm -rf /var/www/html/wp-content/themes/kampong && "
                         "cp -a /src /var/www/html/wp-content/themes/kampong && "
                         "chown -R 33:33 /var/www/html/wp-content/themes/kampong && "
                         "chmod -R a+rX /var/www/html/wp-content/themes/kampong"],
                        capture_output=True, text=True)
    if rc.returncode != 0:
        print("主题复制失败:", rc.stderr[-300:], file=sys.stderr)

    payload = {
        "company": args.company,
        "domain": args.domain,
        "tagline": art["tagline"],
        "palette": art["palette"],
        "phone": "+65 6000 0000",
        "pages": pages,
        "design": build_design(args.industry, art),
        "options": build_options(args.industry, args.company, args.domain),
        "menu": LG_MENU if args.industry == "littlegems" else None,
    }
    (site / "site-spec.json").write_text(json.dumps({"pages": spec_pages}, ensure_ascii=False, indent=1))
    (site / "site.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    if payload.get("design"):
        (site / "design.json").write_text(json.dumps(payload["design"], ensure_ascii=False, indent=1))
    (site / "kf_setup.php").write_text(PHP)
    # site.json / kf_setup.php 决定 WordPress 的 option 与初始化脚本，
    # 被改写即可植入恶意配置，必须只有属主可读写。
    for f in ("site-spec.json", "site.json", "design.json", "kf_setup.php"):
        try:
            (site / f).chmod(0o600)
        except OSError:
            pass

    slug = site.name
    cmd = ["docker", "run", "--rm",
           "--env-file", str(site / "wp.env"),
           "--network", f"kf-{slug}_default",
           "-v", f"{site}/html:/var/www/html",
           "-v", f"{site}:/kfsite:ro",
           "--user", "33:33",
           REG, "wp", "eval-file", "/kfsite/kf_setup.php"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0 or "ERR" in r.stdout:
        print(r.stderr[-800:], file=sys.stderr)

    # 激活主题
    cmd2 = ["docker", "run", "--rm",
            "--env-file", str(site / "wp.env"),
            "--network", f"kf-{slug}_default",
            "-v", f"{site}/html:/var/www/html",
            "--user", "33:33", REG, "wp", "theme", "activate", "kampong"]
    r2 = subprocess.run(cmd2, capture_output=True, text=True)
    print(r2.stdout.strip() or r2.stderr.strip()[:200])


if __name__ == "__main__":
    main()
