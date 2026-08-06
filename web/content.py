"""Category definitions and per-category homepage copy.

CATEGORIES is the fallback for store.categories -- the DB is authoritative at
runtime, this constant keeps the storefront serving when Postgres is
unreachable. CATEGORY_CONTENT is still Python: it is static marketing copy with
no admin screen behind it yet (store.categories.content is the column it lands
in when Sprint 6 adds one).
"""

# Frame categories that drive the theme switcher + poster filtering.
# Colors live in CSS (html[data-theme="<key>"]); this only owns label/tagline/order.
CATEGORIES = [
    {"key": "hotwheels", "label": "Hot Wheels", "tagline": "Die-cast icons, framed for the wall."},
    {"key": "cricket", "label": "Cricket", "tagline": "Legends of the pitch, in frame."},
    {"key": "anime", "label": "Anime", "tagline": "Frame your fandom."},
    {"key": "nature", "label": "Nature", "tagline": "The wild, on your wall."},
    {"key": "motivation", "label": "Motivation", "tagline": "Fuel for every single day."},
]

# Per-category homepage content. Each category is its own landing (/?cat=<key>):
# hero title/copy + "explore" collection cards + split-story, all category-specific.
# Images are pulled from that category's products at render time.
CATEGORY_CONTENT = {
    "all": {
        "eyebrow": "Every obsession, framed.",
        "title": ("Frame what you're", "obsessed", "with."),
        "subtitle": "Hot Wheels, cricket, anime, nature, motivation — pick a category up top to enter its world, then tune every frame before it reaches the wall.",
        "collections_eyebrow": "Find your line",
        "collections_title": "Explore by passion",
        "collections": [
            ("Hot Wheels", "Collector-grade die-cast."),
            ("Cricket & Anime", "Legends and heroes, framed."),
            ("Nature & Motivation", "Calm views and daily fuel."),
        ],
        "story": ("Any obsession.", "Made distinctly yours.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your piece", "Browse every collection in one place."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "hotwheels": {
        "eyebrow": "Die-cast icons, framed for the wall.",
        "title": ("Bring the", "starting grid", "to your walls."),
        "subtitle": "Collector-grade automotive art — racetracks, blueprints, and die-cast icons, framed with technical precision.",
        "collections_eyebrow": "Find your line",
        "collections_title": "Explore the garage",
        "collections": [
            ("Supercars", "Low, fast, and unmistakable."),
            ("Muscle", "Raw power in graphic form."),
            ("Track Icons", "Motorsport stories worth framing."),
        ],
        "story": ("One car.", "Made distinctly yours.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your icon", "Browse the Hot Wheels collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "cricket": {
        "eyebrow": "Legends of the pitch, in frame.",
        "title": ("Frame the", "pitch", "legends."),
        "subtitle": "Pitch geometry, seam detail, and match-day legends — framed with restrained, prestigious heritage.",
        "collections_eyebrow": "Find your side",
        "collections_title": "Explore the ground",
        "collections": [
            ("Batting Legends", "Icons at the crease."),
            ("Iconic Moments", "Match-day history, framed."),
            ("Team Colors", "Wear your side on the wall."),
        ],
        "story": ("One legend.", "Framed your way.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your legend", "Browse the Cricket collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "anime": {
        "eyebrow": "Frame your fandom.",
        "title": ("Frame your", "fandom", "in full energy."),
        "subtitle": "Manga panels, speed lines, and cinematic heroes — framed with expressive, immersive energy.",
        "collections_eyebrow": "Find your arc",
        "collections_title": "Explore the multiverse",
        "collections": [
            ("Shonen Heroes", "Protagonists in full power."),
            ("Villains & Arcs", "The dark side, framed."),
            ("Key Visuals", "Poster-grade cover art."),
        ],
        "story": ("One hero.", "Framed your way.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your hero", "Browse the Anime collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "nature": {
        "eyebrow": "The wild, on your wall.",
        "title": ("Frame the", "wild", "in calm."),
        "subtitle": "Topographic calm — landscapes, water, and light, framed as immersive, collectible art.",
        "collections_eyebrow": "Find your view",
        "collections_title": "Explore the wild",
        "collections": [
            ("Landscapes", "Mountains, water, and sky."),
            ("Seasons", "Color that shifts with time."),
            ("Stillness", "Calm you can hang."),
        ],
        "story": ("One landscape.", "Framed your way.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your view", "Browse the Nature collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
    "motivation": {
        "eyebrow": "Fuel for every single day.",
        "title": ("Frame your", "ambition", "with authority."),
        "subtitle": "Discipline, ambition, and progress — framed with generous space and monumental type.",
        "collections_eyebrow": "Find your drive",
        "collections_title": "Explore the mindset",
        "collections": [
            ("Discipline", "Show up. Every day."),
            ("Ambition", "Aim past the summit."),
            ("Focus", "Silence the noise."),
        ],
        "story": ("One mantra.", "Framed your way.",
                  "Choose a frame finish, select the scale, and tune the graphic treatment. The configurator keeps pricing transparent while you build."),
        "steps": [
            ("Pick your mantra", "Browse the Motivation collection."),
            ("Tune the presentation", "Combine four frames, four sizes, and finishes."),
            ("Preview your wall", "Upload a room photo and position the piece."),
        ],
    },
}

CATEGORY_KEYS = {c["key"] for c in CATEGORIES}

# Fallback hero/story art for the "all" view (a car blueprint reads as the flagship).
DEFAULT_HERO_IMAGE = "/static/img/posters/mclaren-p1-blueprint.png"
DEFAULT_STORY_IMAGE = "/static/img/posters/mclaren-w1.png"
