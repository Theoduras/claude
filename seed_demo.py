"""Populate Velvet with 20 demo profiles that are all live-searching.

Every seeded member is placed in the live-search pool as "waiting", so
when you hit Search yourself there is always a pool to be matched from.

    python seed_demo.py           # add the demo members (idempotent)
    python seed_demo.py --reset   # remove them first, then re-add

They all share the password below, so you can log in as any of them to
see the other side of a chat.
"""

import argparse
import hashlib
import struct
import sys
import zlib

from werkzeug.security import generate_password_hash

from app import (
    BODY_TYPES,
    CITY_COORDS,
    EYE_COLORS,
    FITNESS_LEVELS,
    GENDERS,
    HAIR_COLORS,
    HEIGHT_MAX_CM,
    HEIGHT_MIN_CM,
    PHOTO_ALLOWED_MIMES,
    PHOTO_MAX_BYTES,
    PHOTO_MAX_PER_USER,
    POOL,
    RADIUS_MAX_KM,
    RELATIONSHIP_TYPES,
    SEEKING_OPTIONS,
    TATTOO_LEVELS,
    Db,
    sniff_image_mime,
    startup,
)

DEMO_PASSWORD = "demo12345"

# username, name, age, gender, location, relationship_type, interests,
# hobbies, seeking, age_min, age_max, radius_km
#
# Everyone is based in Maastricht, so the distance filter never removes a
# member and the demo works for a local audience. The radius values are kept
# as-is: they stay meaningful the moment a member is moved to another city.
#
# The first twelve are deliberate "anchors": for every relationship type
# there is one woman and one man who are open to everyone and any age. That
# guarantees a searcher of any gender can find someone for whatever
# connection they pick. The remaining eight have narrow age/gender filters.
DEMO_MEMBERS = [
    # --- anchors: seeking Everyone, ages 18-99, radius anywhere ---------
    ("mia_b",      "Mia",     26, "Woman",      "Maastricht","Long-term relationship",
     "music, travel, cooking", "salsa, yoga",          "Everyone", 18, 99, 500),
    ("liam_k",     "Liam",    28, "Man",        "Maastricht","Long-term relationship",
     "music, cooking, films",  "guitar, running",      "Everyone", 18, 99, 500),
    ("paula_o",    "Paula",   30, "Woman",      "Maastricht","Short-term relationship",
     "whisky, sailing, films", "guitar, yoga",         "Everyone", 18, 99, 500),
    ("stefan_g",   "Stefan",  32, "Man",        "Maastricht","Short-term relationship",
     "sailing, whisky",        "sailing, guitar",      "Everyone", 18, 99, 500),
    ("noor_a",     "Noor",    24, "Woman",      "Maastricht","Short-term relationship",
     "art, photography",       "painting, cycling",    "Everyone", 18, 99, 500),
    ("jonas_w",    "Jonas",   25, "Man",        "Maastricht","Short-term relationship",
     "techno, gaming",         "skateboarding",        "Everyone", 18, 99, 500),
    ("lena_h",     "Lena",    27, "Woman",      "Maastricht","Friendship",
     "books, board games",     "knitting, hiking",     "Everyone", 18, 99, 500),
    ("kai_n",      "Kai",     23, "Man",        "Maastricht","Friendship",
     "board games, anime",     "drawing, badminton",   "Everyone", 18, 99, 500),
    ("ava_s",      "Ava",     31, "Woman",      "Maastricht","Long-term relationship",
     "wine, travel, cooking",  "tennis, baking",       "Everyone", 18, 99, 500),
    ("theo_r",     "Theo",    33, "Man",        "Maastricht","Long-term relationship",
     "hiking, cooking, wine",  "climbing, chess",      "Everyone", 18, 99, 500),
    ("ines_l",     "Ines",    29, "Woman",      "Maastricht","Not sure yet",
     "cycling, gardening",     "grilling, reading",    "Everyone", 18, 99, 500),
    ("bruno_c",    "Bruno",   35, "Man",        "Maastricht","Not sure yet",
     "cars, cycling",          "motorsport, grilling", "Everyone", 18, 99, 500),

    # --- picky ones: narrow ages, one gender, tight radius --------------
    ("clara_p",    "Clara",   33, "Woman",      "Maastricht","Long-term relationship",
     "jazz, cooking, museums", "pottery, running",     "Men",      29, 42, 80),
    ("elias_m",    "Elias",   34, "Man",        "Maastricht","Long-term relationship",
     "cooking, travel, jazz",  "cycling, pottery",     "Women",    27, 38, 60),
    ("hana_y",     "Hana",    27, "Woman",      "Maastricht","Long-term relationship",
     "languages, food, travel","climbing, cooking",    "Men",      25, 35, 45),
    ("omar_f",     "Omar",    30, "Man",        "Maastricht","Long-term relationship",
     "travel, food, languages","surfing, cooking",     "Everyone", 24, 36, 120),
    ("zoe_t",      "Zoe",     20, "Woman",      "Maastricht","Short-term relationship",
     "football, festivals",    "gym, dancing",         "Men",      18, 26, 35),
    ("finn_d",     "Finn",    21, "Man",        "Maastricht","Short-term relationship",
     "gaming, football",       "fifa, gym",            "Women",    18, 25, 20),
    ("sam_v",      "Sam",     28, "Non-binary", "Maastricht","Not sure yet",
     "music, poetry, films",   "djing, swimming",      "Everyone", 21, 34, 40),
    ("robin_e",    "Robin",   25, "Non-binary", "Maastricht","Friendship",
     "anime, board games",     "drawing, hiking",      "Everyone", 20, 32, 90),

    # --- second wave: 20 more Maastricht members -------------------------
    ("emma_v",     "Emma",    26, "Woman",      "Maastricht","Long-term relationship",
     "reading, travel, wine",  "yoga, painting",       "Men",      24, 36, 60),
    ("daan_p",     "Daan",    29, "Man",        "Maastricht","Long-term relationship",
     "cycling, cooking",       "running, chess",       "Women",    23, 34, 70),
    ("sofie_k",    "Sofie",   24, "Woman",      "Maastricht","Short-term relationship",
     "festivals, dancing",     "gym, clubbing",        "Men",      20, 30, 40),
    ("milan_j",    "Milan",   27, "Man",        "Maastricht","Short-term relationship",
     "gaming, football",       "fifa, gym",            "Women",    20, 30, 30),
    ("julia_r",    "Julia",   31, "Woman",      "Maastricht","Friendship",
     "hiking, photography",    "climbing, drawing",    "Everyone", 22, 40, 90),
    ("tim_h",      "Tim",     33, "Man",        "Maastricht","Friendship",
     "board games, films",     "chess, cinema",        "Everyone", 22, 45, 100),
    ("nina_d",     "Nina",    28, "Woman",      "Maastricht","Not sure yet",
     "art, museums",           "painting, pottery",    "Everyone", 21, 38, 50),
    ("bram_s",     "Bram",    30, "Man",        "Maastricht","Not sure yet",
     "cars, motorsport",       "cycling, grilling",    "Everyone", 22, 40, 60),
    ("lotte_m",    "Lotte",   23, "Woman",      "Maastricht","Long-term relationship",
     "music, concerts",        "guitar, running",      "Men",      21, 30, 45),
    ("thijs_w",    "Thijs",   34, "Man",        "Maastricht","Long-term relationship",
     "travel, cooking, wine",  "climbing, cooking",    "Women",    26, 38, 80),
    ("fenna_b",    "Fenna",   25, "Woman",      "Maastricht","Short-term relationship",
     "yoga, brunch",           "pilates, baking",      "Men",      22, 32, 35),
    ("sven_l",     "Sven",    22, "Man",        "Maastricht","Short-term relationship",
     "gym, football",          "gym, gaming",          "Women",    18, 27, 25),
    ("iris_t",     "Iris",    29, "Woman",      "Maastricht","Friendship",
     "books, tea, cats",       "reading, knitting",    "Everyone", 21, 40, 80),
    ("wouter_f",   "Wouter",  36, "Man",        "Maastricht","Friendship",
     "chess, history",         "chess, cycling",       "Everyone", 24, 45, 100),
    ("anouk_g",    "Anouk",   27, "Woman",      "Maastricht","Not sure yet",
     "travel, languages",      "surfing, cooking",     "Everyone", 22, 36, 70),
    ("ruben_c",    "Ruben",   31, "Man",        "Maastricht","Not sure yet",
     "photography, hiking",    "climbing, drawing",    "Everyone", 23, 40, 65),
    ("saar_n",     "Saar",    24, "Non-binary", "Maastricht","Friendship",
     "poetry, music",          "djing, writing",       "Everyone", 20, 33, 50),
    ("jesse_o",    "Jesse",   26, "Non-binary", "Maastricht","Not sure yet",
     "gaming, anime",          "drawing, gaming",      "Everyone", 20, 34, 55),
    ("marit_e",    "Marit",   32, "Woman",      "Maastricht","Long-term relationship",
     "cooking, gardening",     "baking, gardening",    "Men",      28, 42, 55),
    ("koen_z",     "Koen",    35, "Man",        "Maastricht","Long-term relationship",
     "wine, cooking, jazz",    "cooking, chess",       "Women",    27, 40, 70),
]

BIO = "{name} from {location}. Into {interests}. Here for {goal}."
WANTS = "Someone I can share {interests} with."
NEEDS = "Honesty, curiosity and a good sense of humour."

# Physical attributes are derived from the username rather than listed, so the
# aligned tuples above stay readable. sha256 (not the built-in hash(), which is
# salted per process) keeps a given member's body identical across runs.
#
# Heights are drawn from a gendered band so the numbers look plausible; every
# other attribute is spread evenly across its list.
HEIGHT_BANDS = {
    "Woman": (158, 178),
    "Man": (170, 193),
    "Non-binary": (163, 185),
}


def derive_physical(username, age, gender):
    """Deterministically pick a member's physical attributes."""
    digest = hashlib.sha256(username.encode()).digest()

    low, high = HEIGHT_BANDS[gender]
    height = low + digest[0] % (high - low + 1)
    assert HEIGHT_MIN_CM <= height <= HEIGHT_MAX_CM

    # Older members skew a little less "Athlete"; purely so the seeded pool
    # isn't uniformly gym-obsessed.
    fitness_pool = FITNESS_LEVELS[:-1] if age >= 33 else FITNESS_LEVELS

    return {
        "height_cm": height,
        "body_type": BODY_TYPES[digest[1] % len(BODY_TYPES)],
        "fitness_level": fitness_pool[digest[2] % len(fitness_pool)],
        "hair_color": HAIR_COLORS[digest[3] % len(HAIR_COLORS)],
        "eye_color": EYE_COLORS[digest[4] % len(EYE_COLORS)],
        "tattoos": TATTOO_LEVELS[digest[5] % len(TATTOO_LEVELS)],
    }


# Hand-picked physical preferences for four of the "picky" anchors. Everyone
# else leaves these blank, which the scorer skips rather than penalises.
#
# These are tuned against the attributes derive_physical() actually produces for
# these usernames, to make the harmonic mean's effect visible in /matches:
#
#   clara_p <-> elias_m  each fits what the other asked for -> scores near 100
#   hana_y  --> omar_f   omar fits hana's type, but hana is nothing like what
#                        omar asked for, so the pair is dragged far below the
#                        mutual one despite one side being a perfect fit
#
# Both pairs are gender-compatible and share a relationship type, so both really
# do show up in each other's rankings.
PHYSICAL_PREFS = {
    # Wants elias_m: 187 cm, Muscular, Red hair, Hazel eyes, a few tattoos.
    "clara_p": {
        "pref_height_min": 180, "pref_height_max": 195,
        "pref_body_types": "Athletic,Muscular",
        "pref_hair_color": "Red",
        "pref_eye_color": "Hazel",
        "pref_tattoos": "A few",
    },
    # Wants clara_p: 166 cm, Plus-size, Other hair, Blue eyes, no tattoos.
    "elias_m": {
        "pref_height_min": 160, "pref_height_max": 175,
        "pref_body_types": "Curvy,Plus-size",
        "pref_hair_color": "Other",
        "pref_eye_color": "Blue",
        "pref_tattoos": "None",
    },
    # Wants a very tall, slim, blonde athlete — which omar_f is not.
    "hana_y": {
        "pref_height_min": 192, "pref_height_max": 200,
        "pref_body_types": "Slim",
        "pref_fitness_level": "Athlete",
        "pref_hair_color": "Blonde",
        "pref_eye_color": "Green",
    },
    # Wants hana_y almost exactly: 159 cm, Plus-size, Active, Brown, Hazel, Many.
    "omar_f": {
        "pref_height_min": 155, "pref_height_max": 165,
        "pref_body_types": "Plus-size",
        "pref_fitness_level": "Active",
        "pref_hair_color": "Brown",
        "pref_eye_color": "Hazel",
        "pref_tattoos": "Many",
    },
}

# Every physical column written by the seeder, with the blank/NULL default used
# for members that have no hand-picked preference.
PREF_DEFAULTS = {
    "pref_height_min": None,
    "pref_height_max": None,
    "pref_body_types": "",
    "pref_fitness_level": "",
    "pref_hair_color": "",
    "pref_eye_color": "",
    "pref_tattoos": "",
}


# --- demo profile photos --------------------------------------------------
# Not real (or fabricated-to-look-real) photos of a person: hand-built
# gradient PNGs in the app's own palette. No Pillow dependency (see
# app.py's photo-upload notes), so this is a minimal from-scratch PNG
# encoder rather than a real image library. First entry in each list
# becomes the primary photo, same convention edit_profile() uses.
DEMO_PHOTOS = {
    "theo_r": [
        ((58, 20, 90), (18, 128, 127)),    # violet -> teal
        ((138, 43, 226), (11, 7, 19)),     # violet -> ink
        ((232, 211, 169), (59, 11, 102)),  # champagne -> violet-deep
    ],
}

# Second-wave members share one look: a plum/orange/pink gradient sampled
# from an abstract swirl illustration (not a photo of anyone), so their
# cards read as a matched set distinct from the first wave above.
_SWIRL_GRADIENT = [((176, 58, 122), (230, 145, 60))]  # plum -> orange
for _username, *_ in DEMO_MEMBERS[20:]:
    DEMO_PHOTOS[_username] = _SWIRL_GRADIENT


def make_gradient_png(w, h, top_rgb, bottom_rgb):
    """A flat vertical-gradient PNG: raw scanlines, zlib-compressed by hand."""
    def lerp(a, b, t):
        return int(a + (b - a) * t)

    rows = bytearray()
    for y in range(h):
        t = y / (h - 1)
        r = lerp(top_rgb[0], bottom_rgb[0], t)
        g = lerp(top_rgb[1], bottom_rgb[1], t)
        bl = lerp(top_rgb[2], bottom_rgb[2], t)
        rows.append(0)  # filter type: none
        rows.extend([r, g, bl] * w)

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data)))

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    idat = chunk(b"IDAT", zlib.compress(bytes(rows), 9))
    iend = chunk(b"IEND", b"")
    return sig + ihdr + idat + iend


def seed_photos(db, username, user_id):
    """Add DEMO_PHOTOS[username], but only if that member has none yet —
    reset() cascades photos away with the user row, so a plain re-run stays
    idempotent without needing its own delete-then-reinsert here."""
    gradients = DEMO_PHOTOS.get(username)
    if not gradients:
        return 0
    existing = db.execute(
        "SELECT COUNT(*) AS n FROM photos WHERE user_id = ?", (user_id,)
    ).fetchone()["n"]
    if existing:
        return 0

    gradients = gradients[:PHOTO_MAX_PER_USER]
    added = 0
    for i, (top, bottom) in enumerate(gradients):
        data = make_gradient_png(600, 600, top, bottom)
        assert len(data) <= PHOTO_MAX_BYTES
        mime = sniff_image_mime(data)
        assert mime in PHOTO_ALLOWED_MIMES, mime
        db.execute(
            "INSERT INTO photos (user_id, data, mime, is_primary) VALUES (?, ?, ?, ?)",
            (user_id, data, mime, i == 0),
        )
        added += 1
    return added


def validate():
    """Fail loudly if the demo data drifts from the app's allowed values."""
    usernames = set()
    for row in DEMO_MEMBERS:
        username, name, age, gender, location, rel, _, _, seeking, lo, hi, radius = row
        assert gender in GENDERS, f"{name}: bad gender {gender!r}"
        assert rel in RELATIONSHIP_TYPES, f"{name}: bad relationship {rel!r}"
        assert seeking in SEEKING_OPTIONS, f"{name}: bad seeking {seeking!r}"
        assert 18 <= lo <= hi <= 120, f"{name}: bad age range {lo}-{hi}"
        assert 1 <= radius <= RADIUS_MAX_KM, f"{name}: bad radius {radius}"
        assert location.lower() in CITY_COORDS, f"{name}: unmapped city {location!r}"
        usernames.add(username)

        # The derived attributes must be values the app would accept, since a
        # member could open the profile editor and re-save them unchanged.
        phys = derive_physical(username, age, gender)
        assert HEIGHT_MIN_CM <= phys["height_cm"] <= HEIGHT_MAX_CM, (
            f"{name}: height {phys['height_cm']} out of range"
        )
        for field, options in (
            ("body_type", BODY_TYPES),
            ("fitness_level", FITNESS_LEVELS),
            ("hair_color", HAIR_COLORS),
            ("eye_color", EYE_COLORS),
            ("tattoos", TATTOO_LEVELS),
        ):
            assert phys[field] in options, f"{name}: bad {field} {phys[field]!r}"

    for username, prefs in PHYSICAL_PREFS.items():
        assert username in usernames, f"PHYSICAL_PREFS: unknown member {username!r}"
        assert set(prefs) <= set(PREF_DEFAULTS), (
            f"{username}: unknown preference key in {sorted(prefs)}"
        )
        lo, hi = prefs.get("pref_height_min"), prefs.get("pref_height_max")
        if lo is not None or hi is not None:
            assert lo is not None and hi is not None, (
                f"{username}: height preference needs both bounds"
            )
            assert HEIGHT_MIN_CM <= lo <= hi <= HEIGHT_MAX_CM, (
                f"{username}: bad height preference {lo}-{hi}"
            )
        for bt in (prefs.get("pref_body_types") or "").split(","):
            assert not bt or bt in BODY_TYPES, f"{username}: bad body type {bt!r}"
        for field, options in (
            ("pref_fitness_level", FITNESS_LEVELS),
            ("pref_hair_color", HAIR_COLORS),
            ("pref_eye_color", EYE_COLORS),
            ("pref_tattoos", TATTOO_LEVELS),
        ):
            val = prefs.get(field)
            assert not val or val in options, f"{username}: bad {field} {val!r}"


def reset(db):
    usernames = [m[0] for m in DEMO_MEMBERS]
    placeholders = ",".join("?" * len(usernames))
    ids = [
        r["id"]
        for r in db.execute(
            f"SELECT id FROM users WHERE username IN ({placeholders})", usernames
        )
    ]
    if not ids:
        return 0
    id_ph = ",".join("?" * len(ids))
    db.execute(
        f"""DELETE FROM messages WHERE match_id IN
            (SELECT id FROM matches WHERE user_a IN ({id_ph}) OR user_b IN ({id_ph}))""",
        ids + ids,
    )
    db.execute(
        f"DELETE FROM matches WHERE user_a IN ({id_ph}) OR user_b IN ({id_ph})",
        ids + ids,
    )
    db.execute(f"DELETE FROM searches WHERE user_id IN ({id_ph})", ids)
    db.execute(f"DELETE FROM profiles WHERE user_id IN ({id_ph})", ids)
    db.execute(f"DELETE FROM users WHERE id IN ({id_ph})", ids)
    db.commit()
    return len(ids)


def seed(db):
    password_hash = generate_password_hash(DEMO_PASSWORD)
    added = refreshed = photos_added = 0

    for (
        username, name, age, gender, location, relationship_type,
        interests, hobbies, seeking, age_min, age_max, radius_km,
    ) in DEMO_MEMBERS:
        row = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()

        if row is None:
            # is_bot marks these as demo members that auto-reply in chat
            # (see maybe_bot_reply() in app.py) and auto-continue past the
            # decision phase, so a live-search lifecycle can be exercised
            # solo against any of them.
            user_id = db.insert_returning_id(
                "INSERT INTO users (username, password_hash, is_bot) VALUES (?, ?, TRUE)",
                (username, password_hash),
            )
            added += 1
        else:
            user_id = row["id"]
            db.execute("UPDATE users SET is_bot = TRUE WHERE id = ?", (user_id,))
            refreshed += 1

        photos_added += seed_photos(db, username, user_id)

        phys = derive_physical(username, age, gender)
        prefs = {**PREF_DEFAULTS, **PHYSICAL_PREFS.get(username, {})}

        db.execute(
            """
            INSERT INTO profiles
                (user_id, name, age, gender, seeking, location, bio, interests,
                 hobbies, wants, needs, relationship_type,
                 height_cm, body_type, fitness_level, hair_color, eye_color,
                 tattoos, pref_height_min, pref_height_max, pref_body_types,
                 pref_fitness_level, pref_hair_color, pref_eye_color,
                 pref_tattoos, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, NOW())
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name, age = excluded.age,
                gender = excluded.gender, seeking = excluded.seeking,
                location = excluded.location, bio = excluded.bio,
                interests = excluded.interests, hobbies = excluded.hobbies,
                wants = excluded.wants, needs = excluded.needs,
                relationship_type = excluded.relationship_type,
                height_cm = excluded.height_cm,
                body_type = excluded.body_type,
                fitness_level = excluded.fitness_level,
                hair_color = excluded.hair_color,
                eye_color = excluded.eye_color,
                tattoos = excluded.tattoos,
                pref_height_min = excluded.pref_height_min,
                pref_height_max = excluded.pref_height_max,
                pref_body_types = excluded.pref_body_types,
                pref_fitness_level = excluded.pref_fitness_level,
                pref_hair_color = excluded.pref_hair_color,
                pref_eye_color = excluded.pref_eye_color,
                pref_tattoos = excluded.pref_tattoos,
                updated_at = NOW()
            """,
            (
                user_id, name, age, gender, seeking, location,
                BIO.format(name=name, location=location, interests=interests,
                           goal=relationship_type.lower()),
                interests, hobbies,
                WANTS.format(interests=interests), NEEDS, relationship_type,
                phys["height_cm"], phys["body_type"], phys["fitness_level"],
                phys["hair_color"], phys["eye_color"], phys["tattoos"],
                prefs["pref_height_min"], prefs["pref_height_max"],
                prefs["pref_body_types"], prefs["pref_fitness_level"],
                prefs["pref_hair_color"], prefs["pref_eye_color"],
                prefs["pref_tattoos"],
            ),
        )

        # Put them in the live-search pool, all waiting at the same time.
        db.execute(
            """
            INSERT INTO searches
                (user_id, seeking, age_min, age_max, relationship_type,
                 interests, location, radius_km, status, match_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', NULL, NOW())
            ON CONFLICT(user_id) DO UPDATE SET
                seeking = excluded.seeking, age_min = excluded.age_min,
                age_max = excluded.age_max,
                relationship_type = excluded.relationship_type,
                interests = excluded.interests,
                location = excluded.location, radius_km = excluded.radius_km,
                status = 'waiting', match_id = NULL,
                created_at = NOW()
            """,
            (
                user_id, seeking, age_min, age_max, relationship_type,
                interests, location, radius_km,
            ),
        )

    db.commit()
    return added, refreshed, photos_added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true",
        help="delete the demo members (and their matches) before seeding",
    )
    args = parser.parse_args()

    validate()
    startup()  # open the pool and make sure the schema exists

    with POOL.connection() as conn:
        db = Db(conn)
        if args.reset:
            removed = reset(db)
            print(f"Removed {removed} existing demo member(s).")

        added, refreshed, photos_added = seed(db)
        waiting = db.execute(
            "SELECT COUNT(*) AS n FROM searches WHERE status = 'waiting'"
        ).fetchone()["n"]

    print(f"Added {added} new member(s), refreshed {refreshed}.")
    if photos_added:
        print(f"Added {photos_added} profile photo(s).")
    print(f"{waiting} member(s) are now live-searching at the same time.")
    print(f"They all log in with the password: {DEMO_PASSWORD}")
    print("\nStart the app and hit \N{LEFT-POINTING MAGNIFYING GLASS} Live search "
          "to be paired instantly.")


if __name__ == "__main__":
    sys.exit(main())
