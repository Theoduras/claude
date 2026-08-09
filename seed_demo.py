"""Populate Heartlink with 20 demo profiles that are all live-searching.

Every seeded member is placed in the live-search pool as "waiting", so
when you hit Search yourself there is always a pool to be matched from.

    python seed_demo.py           # add the demo members (idempotent)
    python seed_demo.py --reset   # remove them first, then re-add

They all share the password below, so you can log in as any of them to
see the other side of a chat.
"""

import argparse
import sqlite3
import sys

from werkzeug.security import generate_password_hash

from app import (
    CITY_COORDS,
    DATABASE,
    GENDERS,
    RADIUS_MAX_KM,
    RELATIONSHIP_TYPES,
    SEEKING_OPTIONS,
    init_db,
)

DEMO_PASSWORD = "demo12345"

# username, name, age, gender, location, relationship_type, interests,
# hobbies, seeking, age_min, age_max, radius_km
DEMO_MEMBERS = [
    ("mia_b",      "Mia",     24, "Woman",      "Berlin",    "Long-term relationship",
     "music, travel, cooking", "salsa, yoga",          "Men",      21, 32, 50),
    ("liam_k",     "Liam",    27, "Man",        "Berlin",    "Long-term relationship",
     "music, cooking, films",  "guitar, running",      "Women",    22, 30, 30),
    ("noor_a",     "Noor",    22, "Woman",      "Hamburg",   "Casual dating",
     "art, photography",       "painting, cycling",    "Everyone", 18, 28, 100),
    ("theo_r",     "Theo",    31, "Man",        "Munich",    "Marriage",
     "hiking, cooking, wine",  "climbing, chess",      "Women",    25, 36, 75),
    ("ava_s",      "Ava",     29, "Woman",      "Munich",    "Marriage",
     "wine, travel, cooking",  "tennis, baking",       "Men",      27, 40, 60),
    ("jonas_w",    "Jonas",   25, "Man",        "Berlin",    "Short-term relationship",
     "techno, gaming",         "skateboarding",        "Women",    19, 28, 25),
    ("lena_h",     "Lena",    26, "Woman",      "Cologne",   "Friendship",
     "books, board games",     "knitting, hiking",     "Everyone", 20, 35, 150),
    ("sam_v",      "Sam",     28, "Non-binary", "Berlin",    "Casual dating",
     "music, poetry, films",   "djing, swimming",      "Everyone", 21, 34, 40),
    ("elias_m",    "Elias",   34, "Man",        "Frankfurt", "Long-term relationship",
     "cooking, travel, jazz",  "cycling, pottery",     "Women",    27, 38, 200),
    ("clara_p",    "Clara",   33, "Woman",      "Frankfurt", "Long-term relationship",
     "jazz, cooking, museums", "pottery, running",     "Men",      29, 42, 80),
    ("finn_d",     "Finn",    21, "Man",        "Leipzig",   "Casual dating",
     "gaming, football",       "fifa, gym",            "Women",    18, 25, 20),
    ("zoe_t",      "Zoe",     20, "Woman",      "Leipzig",   "Casual dating",
     "football, festivals",    "gym, dancing",         "Men",      18, 26, 35),
    ("omar_f",     "Omar",    30, "Man",        "Berlin",    "Long-term relationship",
     "travel, food, languages","surfing, cooking",     "Everyone", 24, 36, 500),
    ("hana_y",     "Hana",    27, "Woman",      "Berlin",    "Long-term relationship",
     "languages, food, travel","climbing, cooking",    "Men",      25, 35, 45),
    ("bruno_c",    "Bruno",   38, "Man",        "Stuttgart", "Not sure yet",
     "cars, cycling",          "motorsport, grilling", "Women",    30, 45, 500),
    ("ines_l",     "Ines",    41, "Woman",      "Stuttgart", "Not sure yet",
     "cycling, gardening",     "grilling, reading",    "Men",      35, 50, 45),
    ("kai_n",      "Kai",     23, "Man",        "Dresden",   "Friendship",
     "board games, anime",     "drawing, badminton",   "Everyone", 18, 30, 120),
    ("robin_e",    "Robin",   25, "Non-binary", "Dresden",   "Friendship",
     "anime, board games",     "drawing, hiking",      "Everyone", 20, 32, 90),
    ("stefan_g",   "Stefan",  36, "Man",        "Hamburg",   "Short-term relationship",
     "sailing, whisky",        "sailing, guitar",      "Women",    28, 42, 65),
    ("paula_o",    "Paula",   32, "Woman",      "Hamburg",   "Short-term relationship",
     "whisky, sailing, films", "guitar, yoga",         "Men",      28, 40, 55),
]

BIO = "{name} from {location}. Into {interests}. Here for {goal}."
WANTS = "Someone I can share {interests} with."
NEEDS = "Honesty, curiosity and a good sense of humour."


def validate():
    """Fail loudly if the demo data drifts from the app's allowed values."""
    for row in DEMO_MEMBERS:
        _, name, _, gender, location, rel, _, _, seeking, lo, hi, radius = row
        assert gender in GENDERS, f"{name}: bad gender {gender!r}"
        assert rel in RELATIONSHIP_TYPES, f"{name}: bad relationship {rel!r}"
        assert seeking in SEEKING_OPTIONS, f"{name}: bad seeking {seeking!r}"
        assert 18 <= lo <= hi <= 120, f"{name}: bad age range {lo}-{hi}"
        assert 1 <= radius <= RADIUS_MAX_KM, f"{name}: bad radius {radius}"
        assert location.lower() in CITY_COORDS, f"{name}: unmapped city {location!r}"


def reset(db):
    usernames = [m[0] for m in DEMO_MEMBERS]
    placeholders = ",".join("?" * len(usernames))
    ids = [
        r[0]
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
    added = refreshed = 0

    for (
        username, name, age, gender, location, relationship_type,
        interests, hobbies, seeking, age_min, age_max, radius_km,
    ) in DEMO_MEMBERS:
        row = db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()

        if row is None:
            cur = db.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )
            user_id = cur.lastrowid
            added += 1
        else:
            user_id = row[0]
            refreshed += 1

        db.execute(
            """
            INSERT INTO profiles
                (user_id, name, age, gender, seeking, location, bio, interests,
                 hobbies, wants, needs, relationship_type, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                name = excluded.name, age = excluded.age,
                gender = excluded.gender, seeking = excluded.seeking,
                location = excluded.location, bio = excluded.bio,
                interests = excluded.interests, hobbies = excluded.hobbies,
                wants = excluded.wants, needs = excluded.needs,
                relationship_type = excluded.relationship_type,
                updated_at = datetime('now')
            """,
            (
                user_id, name, age, gender, seeking, location,
                BIO.format(name=name, location=location, interests=interests,
                           goal=relationship_type.lower()),
                interests, hobbies,
                WANTS.format(interests=interests), NEEDS, relationship_type,
            ),
        )

        # Put them in the live-search pool, all waiting at the same time.
        db.execute(
            """
            INSERT INTO searches
                (user_id, seeking, age_min, age_max, relationship_type,
                 interests, location, radius_km, status, match_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'waiting', NULL, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                seeking = excluded.seeking, age_min = excluded.age_min,
                age_max = excluded.age_max,
                relationship_type = excluded.relationship_type,
                interests = excluded.interests,
                location = excluded.location, radius_km = excluded.radius_km,
                status = 'waiting', match_id = NULL,
                created_at = datetime('now')
            """,
            (
                user_id, seeking, age_min, age_max, relationship_type,
                interests, location, radius_km,
            ),
        )

    db.commit()
    return added, refreshed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reset", action="store_true",
        help="delete the demo members (and their matches) before seeding",
    )
    args = parser.parse_args()

    validate()
    init_db()  # make sure the schema exists

    db = sqlite3.connect(DATABASE)
    if args.reset:
        removed = reset(db)
        print(f"Removed {removed} existing demo member(s).")

    added, refreshed = seed(db)
    waiting = db.execute(
        "SELECT COUNT(*) FROM searches WHERE status = 'waiting'"
    ).fetchone()[0]
    db.close()

    print(f"Added {added} new member(s), refreshed {refreshed}.")
    print(f"{waiting} member(s) are now live-searching at the same time.")
    print(f"They all log in with the password: {DEMO_PASSWORD}")
    print("\nStart the app and hit \N{LEFT-POINTING MAGNIFYING GLASS} Live search "
          "to be paired instantly.")


if __name__ == "__main__":
    sys.exit(main())
