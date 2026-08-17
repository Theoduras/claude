"""User-facing copy, in every language the app speaks.

Deliberately a plain dict rather than gettext/Babel: the app has one module of
routes and no build step, and adding an extraction toolchain plus .po/.mo
compilation would be more machinery than 1,300 words of copy justifies. The
trade-off is that nothing warns you about a key you forgot -- so translate()
falls back rather than raising, and tools/check_translations.py reports gaps.

Adding a language
-----------------
1. Append it to LANGUAGES. The switcher, the /lang/<code> route and the
   validation all read that list, so nothing else needs touching to make the
   option appear.
2. Copy the "en" block below, translate the values, leave the keys alone.
3. Optionally add an OPTION_LABELS entry to translate the profile dropdowns.
   Skip it and they stay English while the rest of the page translates.
4. Run tools/check_translations.py to list anything still missing.

A partial language is safe to ship: any key it lacks falls through to English.

What must NOT be translated
---------------------------
The profile option lists in app.py (GENDERS, SEEKING_OPTIONS,
RELATIONSHIP_TYPES, BODY_TYPES, FITNESS_LEVELS, HAIR_COLORS, EYE_COLORS,
TATTOO_LEVELS) are stored in the database and compared as strings by
searches_compatible() and SEEKING_MATCHES. Translating the stored value would
stop a Dutch user matching an English one. So the values stay canonical
English and only their *labels* are translated, via OPTION_LABELS below.
"""

# (code, name as speakers of it write it). Order is the order the switcher
# lists them in; the first entry is the fallback for everything.
LANGUAGES = [
    ("en", "English"),
    ("nl", "Nederlands"),
]

DEFAULT_LANGUAGE = LANGUAGES[0][0]
LANGUAGE_CODES = [code for code, _ in LANGUAGES]
LANGUAGE_NAMES = dict(LANGUAGES)

# Short label for the switcher button itself.
LANGUAGE_SHORT = {"en": "EN", "nl": "NL"}


TRANSLATIONS = {
    # ---------------------------------------------------------------- en ----
    # English is the source of truth: these values *are* the English copy,
    # and every other language mirrors these keys.
    "en": {
        # --- chrome: nav, tab bar, shared controls ---
        "nav.live_search": "Live search",
        "nav.chats": "Chats",
        "nav.profile": "Profile",
        "nav.help": "Help",
        "nav.new_profile": "New profile",
        "nav.log_out": "Log out",
        "nav.admin": "Admin",
        "tab.search": "Search",
        "tab.chats": "Chats",
        "tab.you": "You",
        "tab.help": "Help",
        "lang.choose": "Choose a language",

        # --- landing ---
        "landing.title": "Velvt",
        # Newlines are the typographic choice of each language: the template
        # turns them into <br>, so a language may use fewer or more lines.
        "landing.headline": "Something\nsofter than\nswiping.",
        "landing.lede": "Sign in and search — we pair you the moment someone is looking for you too.",
        "landing.cta_start": "Start searching",
        "landing.cta_signin": "I already have an account",
        "landing.fine": "Nobody matches you unless you match them back.",
        "pulse.live_one": "1 searching right now",
        "pulse.live_many": "{n} searching right now",
        "pulse.today_one": "1 search started today",
        "pulse.today_many": "{n} searches started today",
        "pulse.members": "{n} members",
        "pulse.be_first": "Be the first one searching tonight",

        # --- footer / help hub ---
        "footer.how": "How matching works",
        "footer.questions": "Questions",
        "footer.safety": "Safety",
        "footer.terms": "Terms",
        "footer.privacy": "Privacy",
        "footer.imprint": "Imprint",
        "footer.contact": "Contact",
        "help.title": "Help — Velvt",
        "help.eyebrow": "Velvt",
        "help.heading": "Questions, answered.",
        "help.how_body": (
            "Start a live search and we look for someone searching for you at "
            "the same time. When we find a match, you both get a short reveal, "
            "then a timed chat to see if it's worth continuing. Nobody is shown "
            "to anyone unless the interest goes both ways."
        ),
        "help.questions_body": "Something not covered here? Reach us any time — see {contact} below.",
        "help.safety_body": (
            "Meet new people the way you'd want a friend to: in public, on your "
            "own terms, and never with money or personal documents involved. "
            "Block or report anyone from their profile or a chat, any time."
        ),
        "help.terms_body": (
            "Use Velvt to meet people in good faith. Don't impersonate anyone, "
            "run bots or scripts against the app, or use it to harass or scam "
            "other members. Accounts that do can be removed without notice."
        ),
        "help.privacy_body": (
            "Your profile and photos are visible only to people you've matched "
            "with, or while a match is active. We don't sell your data. You can "
            "edit or remove your profile information at any time."
        ),
        "help.contact_body": (
            "Get in touch through the details on our {homepage}, or, if you're "
            "signed in, from your {settings}."
        ),
        "help.contact_homepage": "homepage",
        "help.contact_settings": "account settings",

        # --- auth ---
        "login.title": "Sign in — Velvt",
        "login.eyebrow": "Velvt",
        "login.heading": "Something softer\nthan swiping.",
        "login.subtitle": "Sign in and search — we pair you the moment someone is looking for you too.",
        "login.username": "Username",
        "login.password": "Password",
        "login.submit": "Sign in",
        "login.no_account": "New to Velvt?",
        "login.create": "Create an account",
        "register.title": "Create account — Velvt",
        "register.eyebrow": "Join Velvt",
        "register.heading": "Make your entrance.",
        "register.subtitle": "Pick a name and a password. Your profile comes next.",
        "register.username": "Username",
        "register.password": "Password",
        "register.password_hint": "At least 8 characters.",
        "register.confirm": "Confirm password",
        "register.submit": "Create account",
        "register.have_account": "Already a member?",
        "register.signin": "Sign in",

        # --- profile: view ---
        "profile.looking_for": "Looking for {seeking}",
        "profile.photos_locked": "Photos unlock once you both continue the match.",
        "profile.your_photo": "Your photo",
        "profile.photo_of": "Photo of {name}",
        "profile.interests": "Interests",
        "profile.hobbies": "Hobbies",
        "profile.wants": "What I want",
        "profile.needs": "What I need",
        "profile.height": "Height",
        "profile.body_type": "Body type",
        "profile.fitness": "Fitness",
        "profile.hair": "Hair",
        "profile.eyes": "Eyes",
        "profile.tattoos": "Tattoos",
        "profile.prefs_label": "Looking for (physical)",
        "profile.prefs_note": "Only you can see this. It counts both ways when ranking matches.",
        "profile.body_types": "Body types",
        "profile.edit": "Edit profile",

        # --- profile: edit ---
        "edit.title": "Edit profile — Velvt",
        "edit.back": "Back to your profile",
        "edit.heading": "Edit profile",
        "edit.save": "Save",
        "edit.save_changes": "Save changes",
        "edit.strength": "Profile strength",

        # --- admin: new profile ---
        "admin.title": "New profile — Velvt",
        "admin.heading": "Create a new profile",
        "admin.subtitle": "Admin only — adds a new member with a full profile to the database.",
        "admin.username": "Username",
        "admin.username_ph": "unique handle, e.g. maria92",
        "admin.password": "Password (optional)",
        "admin.password_ph": "lets this member log in themselves",
        "admin.password_hint": "Leave empty to create a profile without login access.",
        "admin.submit": "Create profile",

        # --- chats list ---
        "chats.title": "Chats — Velvt",
        "chats.heading": "Chats",
        "chats.subtitle": "Your matches and their conversations.",
        "chats.tag_match": "It's a match",
        "chats.tag_timed": "Timed chat",
        "chats.tag_deciding": "Awaiting decision",
        "chats.tag_ended": "Ended",
        "chats.no_messages": "No messages yet — say hi!",
        "chats.empty": "No chats yet. Start a {link} and we'll pair you the moment someone is looking for you too.",
        "chats.empty_link": "live search",

        # --- waiting screen ---
        "waiting.title": "Searching… — Velvt",
        "waiting.eyebrow": "Searching",
        "waiting.heading_1": "Feeling for",
        "waiting.heading_2": "a match",
        "waiting.searching_n": "{n} searching",
        "waiting.fits_n": "{n} fit",
        "waiting.recap_label": "Looking for",
        "waiting.none": (
            "Nobody searching right now fits all of this. You'll be paired the "
            "moment someone does — or change what you're after."
        ),
        "waiting.change": "Change",
        "waiting.stop": "Stop searching",
        "waiting.phrase_1": "Looking for someone who fits — and who's looking for you.",
        "waiting.phrase_2": "Checking who's searching right now…",
        "waiting.phrase_3": "Matching your filters against theirs…",
        "waiting.phrase_4": "Both sides have to fit — holding out for that…",
        "waiting.reconnecting": "Reconnecting…",
        "waiting.matched": "It's a match! Opening your chat…",
        # --- shared profile form (_profile_fields.html) ---
        "form.select": "— Select —",
        "form.fill": "Fill",
        "form.fill_all": "Fill everything",
        "form.about_you": "About you",
        "form.name": "Name",
        "form.age": "Age",
        "form.gender": "Gender",
        "form.seeking": "Looking for",
        "form.add_more": "Add more",
        "form.photos": "Photos",
        "form.add_photos": "Add photos",
        "form.set_main": "Set the main photo",
        "form.bio": "Bio",
        "form.bio_ph": "A few sentences about yourself...",
        "form.interests": "Interests",
        "form.location": "Location",
        "form.location_note": "Velvt is Maastricht-only for now",
        "form.relationship_type": "Relationship type",
        "form.hobbies": "Hobbies",
        "form.hobbies_ph": "e.g. hiking, gaming, painting",
        "form.wants": "What I want",
        "form.wants_ph": "What you're hoping to find...",
        "form.needs": "What I need",
        "form.needs_ph": "What matters most to you in a partner...",
        "form.physical": "Physical attributes",
        "form.height_cm": "Height (cm)",
        "form.height_ph": "e.g. 175",
        "form.eyes": "Eyes",
        "form.body_type": "Body type",
        "form.fitness_level": "Fitness level",
        "form.hair_colour": "Hair colour",
        "form.tattoos": "Tattoos",
        "form.prefs_heading": "What I'm looking for (physical)",
        "form.height_from": "Height from (cm)",
        "form.height_to": "Height to (cm)",
        "form.body_types_drawn": "Body types I'm drawn to",
        # --- live-search wizard (search_start.html) ---
        "wiz.title": "Live search — Velvt",
        "wiz.step": "Step {n} of {total}",
        "wiz.q_relationship_1": "What are you",
        "wiz.q_relationship_2": "looking for?",
        "wiz.q_seeking_1": "Who are you",
        "wiz.q_seeking_2": "looking for?",
        "wiz.q_age_1": "What age are",
        "wiz.q_age_2": "you after?",
        "wiz.hint_age": "Leave it at the full span for no preference.",
        "wiz.q_location_1": "Where are you",
        "wiz.q_location_2": "searching?",
        "wiz.hint_location": "We won't filter by distance — this only helps people who do filter by it find you.",
        "wiz.q_interests_1": "Share any",
        "wiz.q_interests_2": "interests?",
        "wiz.hint_interests": "Pick none for no preference, or up to {max} to only meet people who share at least one.",
        "wiz.more": "+ More",
        "wiz.q_body_1": "Any body type",
        "wiz.q_body_2": "in mind?",
        "wiz.hint_body": "Pick as many as you like, or none for no preference.",
        "wiz.skip": "Skip",
        "wiz.back_aria": "Previous step",
        "wiz.next_aria": "Next step",
        "wiz.start_aria": "Start searching",
        "wiz.sheet_title": "All interests",
        "wiz.sheet_close": "Close",
        "wiz.custom_ph": "Something else…",
        "wiz.custom_aria": "Add your own interest",
        "wiz.add": "Add",
        "wiz.done": "Done",
        "wiz.age_min_aria": "Minimum age",
        "wiz.age_max_aria": "Maximum age",

        # --- criteria screen ---
        "crit.title": "Search for a match — Velvt",
        "crit.heading": "What matters to you?",
        "crit.subtitle": (
            "Every filter in full, including the ones the setup doesn't ask "
            "about. Switch off anything you don't want to filter on — the more "
            "you leave on, the fewer people fit."
        ),
        "crit.change": "change",
        "crit.anywhere": "anywhere",
        "crit.within_km": "within {km} km",
        "crit.who": "Who I'm looking for",
        "crit.who_help": "Only people whose gender matches this are paired with you. Switch it off to be open to anyone.",
        "crit.anyone": "Anyone",
        "crit.age": "Age range",
        "crit.age_help": "Only people inside this range are paired with you. Everyone on Velvt is 18 or over.",
        "crit.distance": "Distance",
        "crit.no_location": "No location set",
        "crit.any_distance": "{place} · any distance",
        "crit.within_of": "Within {km} km of {place}",
        "crit.distance_help": "Only people inside your radius are paired with you. Switch it off to match with anyone, anywhere.",
        "crit.distance_change": "Change the location or radius",
        "crit.physical": "Physical traits",
        "crit.physical_summary": "Height, build, hair, eyes, tattoos",
        "crit.physical_help": (
            "Only people who fit every trait you set here are paired with you. "
            "Anything you leave blank isn't filtered on, so you can set just the "
            "one that matters."
        ),
        "crit.body_types": "Body types",
        "crit.fitness_level": "Fitness level",
        "crit.hair_colour": "Hair colour",
        "crit.eye_colour": "Eye colour",
        "crit.tattoos": "Tattoos",
        "crit.no_preference": "No preference",
        "crit.interests": "Interests",
        "crit.interests_summary": "Only matches people who share one",
        "crit.interests_help": (
            "Turning this on narrows the pool to people who share at least one "
            "of these. Among the people who do, the one with the most in common "
            "is paired first."
        ),
        "crit.interests_ph": "e.g. music, hiking",
        "crit.checking": "Checking the pool…",
        "crit.back": "Back",
        "crit.start": "Start searching",
        "crit.you_are": "You are {gender}",
        "crit.unspecified_gender": "unspecified gender",
        "crit.profile_note": "others' filters apply to you too, so keep {link} accurate.",
        "crit.profile_link": "your profile",
        "crit.pool_total_one": "1 person searching right now",
        "crit.pool_total_many": "{n} people searching right now",
        "crit.pool_fit_one": "1 person fits what you picked",
        "crit.pool_fit_many": "{n} people fit what you picked",
        "crit.sugg_age": "Widen to {min}–{max}",
        "crit.sugg_distance": "Match at any distance",
        "crit.sugg_gender": "Switch to {seeking}",
        "crit.sugg_people_one": "1 person",
        "crit.sugg_people_many": "{n} people",

        # --- chat / match lifecycle ---
        "chat.title": "Chat — Velvt",
        "chat.match_found": "Match found",
        "chat.you_matched": "You matched with",
        "chat.reveal_note": "You were both looking for each other. Photos unlock once you both continue.",
        "chat.already_here": "{name} is already in the room",
        "chat.ask_about": "Ask {pronoun} about",
        "chat.seconds": "seconds",
        "chat.reveal_aside": "Say yes to start now — or wait, and the chat opens on its own.",
        "chat.not_this_one": "Not this one",
        "chat.yes_start": "Yes, start chatting",
        "chat.times_up": "Time's up",
        "chat.continue_with": "Continue with",
        "chat.five_over": "Your five minutes are over.",
        "chat.they_decided": "{name} has already decided.",
        "chat.you_chose": "You chose {choice}.",
        "chat.waiting_for": "Waiting for {name}…",
        "chat.continue_word": "Continue",
        "chat.unmatch_word": "Unmatch",
        "chat.continue_match": "Continue match",
        "chat.match_ended": "Match ended",
        "chat.over_1": "This one's",
        "chat.over_2": "over",
        "chat.one_unmatched": "One of you chose to unmatch.",
        "chat.window_closed": "The decision window closed without an answer from both sides.",
        "chat.your_chats": "Your chats",
        "chat.search_again": "Search again",
        "chat.back_aria": "Back to chats",
        "chat.live": "live",
        "chat.matched_tag": "Matched",
        "chat.timed_tag": "Timed",
        "chat.time_left": "Time left in this room",
        "chat.neither_note": "If neither of you continues, the room closes and nobody is told who hesitated.",
        "chat.no_messages": "No messages yet — break the ice!",
        "chat.you_chose_inline": "You chose {choice} — waiting for {name}",
        "chat.to_continue": "to continue",
        "chat.to_unmatch": "to unmatch",
        "chat.not_decided": "{name} hasn't decided yet",
        "chat.input_ph": "Type a message…",
        "chat.admin_view": "Admin view — only the two matched members can write here",
        "chat.send": "Send",
        # --- server-side messages ---
        "msg.sign_in_first": "Please sign in first.",
        "msg.admin_only": "Only the admin can do that.",
        "msg.welcome": "Welcome! Now set up your profile.",
        "msg.throttled": "Too many attempts. Wait a few minutes before trying again.",
        "msg.bad_credentials": "Invalid username or password.",
        "msg.profile_saved": "Profile saved.",
        "msg.no_such_profile": "That profile does not exist.",
        "msg.profile_created": "Profile for {name} (@{username}) created.",
        "msg.fill_profile_first": "Fill in your profile first so others can match with you.",
        "msg.search_stopped": "Search stopped.",
        "msg.no_such_room": "That chatroom does not exist.",
        "msg.room_private": "That chatroom is private.",
        "msg.name_required": "Please enter your name.",
        "msg.age_invalid": "Please enter a valid age.",
        "msg.age_range": "Age must be between {min} and {max}.",
        "msg.pick_relationship": "Please pick a relationship type from the list.",
        "msg.pick_gender": "Please pick a gender from the list.",
        "msg.pick_seeking": "Please pick who you're looking for from the list.",
        "msg.username_short": "Username must be at least 3 characters.",
        "msg.password_short": "Password must be at least 8 characters.",
        "msg.password_short_optional": "Password must be at least 8 characters (or leave it empty).",
        "msg.passwords_differ": "Passwords do not match.",
        "msg.username_taken": "That username is already taken.",
        "msg.photo_too_big": "Each photo must be under 2 MB.",
        "msg.photo_type": "Photos must be JPEG, PNG, or WebP.",
        "msg.photo_count": "You can have at most {max} photos.",
        "msg.choose_connection": "Please choose what kind of connection you want.",
        "msg.choose_seeking": "Please choose who you're looking for.",
        "msg.check_age_radius": "Please check the age range and radius.",
        "msg.only_matched_write": "Only the two matched members can write in this chatroom.",
        "msg.not_open_yet": "The match hasn't opened for chat yet.",
        "msg.times_up_decide": "Time's up — press Continue or Unmatch to move on.",
        "msg.match_ended": "This match has ended.",
        "msg.empty_message": "Message can't be empty.",
        # relative timestamps on the chat list
        "time.now": "now",
        "time.minutes": "{n}m",
        "time.hours": "{n}h",
        "time.days": "{n}d",
        # waiting-screen summary chips
        "chip.anyone": "Anyone",
        "chip.any_age": "Any age",
        "msg.radius_range": "Radius must be between 1 and {max} km.",



    },

    # ---------------------------------------------------------------- nl ----
    "nl": {
        # --- chrome ---
        "nav.live_search": "Live zoeken",
        "nav.chats": "Gesprekken",
        "nav.profile": "Profiel",
        "nav.help": "Help",
        "nav.new_profile": "Nieuw profiel",
        "nav.log_out": "Uitloggen",
        "nav.admin": "Beheerder",
        "tab.search": "Zoeken",
        "tab.chats": "Chats",
        "tab.you": "Jij",
        "tab.help": "Help",
        "lang.choose": "Kies een taal",

        # --- landing ---
        "landing.title": "Velvt",
        "landing.headline": "Iets zachters\ndan swipen.",
        "landing.lede": "Meld je aan en zoek — we koppelen je zodra iemand anders ook naar jou zoekt.",
        "landing.cta_start": "Begin met zoeken",
        "landing.cta_signin": "Ik heb al een account",
        "landing.fine": "Niemand matcht met jou tenzij jij ook terugmatcht.",
        "pulse.live_one": "1 persoon zoekt nu",
        "pulse.live_many": "{n} mensen zoeken nu",
        "pulse.today_one": "1 zoekopdracht vandaag gestart",
        "pulse.today_many": "{n} zoekopdrachten vandaag gestart",
        "pulse.members": "{n} leden",
        "pulse.be_first": "Wees vanavond de eerste die zoekt",

        # --- footer / help hub ---
        "footer.how": "Hoe matchen werkt",
        "footer.questions": "Vragen",
        "footer.safety": "Veiligheid",
        "footer.terms": "Voorwaarden",
        "footer.privacy": "Privacy",
        "footer.imprint": "Colofon",
        "footer.contact": "Contact",
        "help.title": "Help — Velvt",
        "help.eyebrow": "Velvt",
        "help.heading": "Vragen, beantwoord.",
        "help.how_body": (
            "Start een live zoekopdracht en wij zoeken iemand die op hetzelfde "
            "moment naar jou zoekt. Bij een match krijgen jullie eerst een korte "
            "introductie en daarna een gesprek op de klok, om te kijken of het "
            "de moeite waard is. Niemand wordt aan iemand getoond tenzij de "
            "interesse van twee kanten komt."
        ),
        "help.questions_body": "Staat je vraag er niet bij? Neem gerust contact op — zie {contact} hieronder.",
        "help.safety_body": (
            "Ontmoet nieuwe mensen zoals je een vriend zou aanraden: op een "
            "openbare plek, op je eigen voorwaarden, en nooit met geld of "
            "persoonlijke documenten in het spel. Je kunt iemand altijd "
            "blokkeren of rapporteren via het profiel of het gesprek."
        ),
        "help.terms_body": (
            "Gebruik Velvt om mensen te ontmoeten met goede bedoelingen. Doe je "
            "niet voor als iemand anders, gebruik geen bots of scripts, en "
            "gebruik de app niet om andere leden te intimideren of te "
            "bedriegen. Accounts die dat doen kunnen zonder waarschuwing "
            "worden verwijderd."
        ),
        "help.privacy_body": (
            "Je profiel en je foto's zijn alleen zichtbaar voor mensen met wie "
            "je een match hebt, of zolang een match actief is. We verkopen je "
            "gegevens niet. Je kunt je profielgegevens altijd aanpassen of "
            "verwijderen."
        ),
        "help.contact_body": (
            "Neem contact op via de gegevens op onze {homepage}, of, als je "
            "ingelogd bent, via je {settings}."
        ),
        "help.contact_homepage": "homepagina",
        "help.contact_settings": "accountinstellingen",

        # --- auth ---
        "login.title": "Inloggen — Velvt",
        "login.eyebrow": "Velvt",
        "login.heading": "Iets zachters\ndan swipen.",
        "login.subtitle": "Meld je aan en zoek — we koppelen je zodra iemand anders ook naar jou zoekt.",
        "login.username": "Gebruikersnaam",
        "login.password": "Wachtwoord",
        "login.submit": "Inloggen",
        "login.no_account": "Nieuw bij Velvt?",
        "login.create": "Maak een account",
        "register.title": "Account aanmaken — Velvt",
        "register.eyebrow": "Word lid van Velvt",
        "register.heading": "Maak je entree.",
        "register.subtitle": "Kies een naam en een wachtwoord. Je profiel komt daarna.",
        "register.username": "Gebruikersnaam",
        "register.password": "Wachtwoord",
        "register.password_hint": "Minimaal 8 tekens.",
        "register.confirm": "Bevestig wachtwoord",
        "register.submit": "Account aanmaken",
        "register.have_account": "Al lid?",
        "register.signin": "Inloggen",

        # --- profile: view ---
        "profile.looking_for": "Op zoek naar {seeking}",
        "profile.photos_locked": "Foto's worden zichtbaar zodra jullie beiden doorgaan met de match.",
        "profile.your_photo": "Jouw foto",
        "profile.photo_of": "Foto van {name}",
        "profile.interests": "Interesses",
        "profile.hobbies": "Hobby's",
        "profile.wants": "Wat ik wil",
        "profile.needs": "Wat ik nodig heb",
        "profile.height": "Lengte",
        "profile.body_type": "Lichaamsbouw",
        "profile.fitness": "Fitheid",
        "profile.hair": "Haar",
        "profile.eyes": "Ogen",
        "profile.tattoos": "Tatoeages",
        "profile.prefs_label": "Op zoek naar (fysiek)",
        "profile.prefs_note": "Alleen jij ziet dit. Het weegt aan beide kanten mee bij het rangschikken van matches.",
        "profile.body_types": "Lichaamsbouw",
        "profile.edit": "Profiel bewerken",

        # --- profile: edit ---
        "edit.title": "Profiel bewerken — Velvt",
        "edit.back": "Terug naar je profiel",
        "edit.heading": "Profiel bewerken",
        "edit.save": "Opslaan",
        "edit.save_changes": "Wijzigingen opslaan",
        "edit.strength": "Profielsterkte",

        # --- admin: new profile ---
        "admin.title": "Nieuw profiel — Velvt",
        "admin.heading": "Maak een nieuw profiel",
        "admin.subtitle": "Alleen voor beheerders — voegt een nieuw lid met een volledig profiel toe.",
        "admin.username": "Gebruikersnaam",
        "admin.username_ph": "unieke naam, bijv. maria92",
        "admin.password": "Wachtwoord (optioneel)",
        "admin.password_ph": "hiermee kan dit lid zelf inloggen",
        "admin.password_hint": "Laat leeg om een profiel zonder inlogtoegang te maken.",
        "admin.submit": "Profiel aanmaken",

        # --- chats list ---
        "chats.title": "Gesprekken — Velvt",
        "chats.heading": "Gesprekken",
        "chats.subtitle": "Je matches en hun gesprekken.",
        "chats.tag_match": "Het is een match",
        "chats.tag_timed": "Gesprek op de klok",
        "chats.tag_deciding": "Wacht op beslissing",
        "chats.tag_ended": "Beëindigd",
        "chats.no_messages": "Nog geen berichten — zeg hallo!",
        "chats.empty": "Nog geen gesprekken. Start een {link} en we koppelen je zodra iemand anders ook naar jou zoekt.",
        "chats.empty_link": "live zoekopdracht",

        # --- waiting screen ---
        "waiting.title": "Zoeken… — Velvt",
        "waiting.eyebrow": "Zoeken",
        "waiting.heading_1": "Op zoek naar",
        "waiting.heading_2": "een match",
        "waiting.searching_n": "{n} aan het zoeken",
        "waiting.fits_n": "{n} passend",
        "waiting.recap_label": "Op zoek naar",
        "waiting.none": (
            "Niemand die nu zoekt past bij dit alles. Je wordt gekoppeld zodra "
            "iemand dat wel doet — of pas aan wat je zoekt."
        ),
        "waiting.change": "Aanpassen",
        "waiting.stop": "Stop met zoeken",
        "waiting.phrase_1": "Op zoek naar iemand die past — en die naar jou zoekt.",
        "waiting.phrase_2": "Kijken wie er nu aan het zoeken is…",
        "waiting.phrase_3": "Jouw filters vergelijken met die van anderen…",
        "waiting.phrase_4": "Het moet van twee kanten passen — daar wachten we op…",
        "waiting.reconnecting": "Opnieuw verbinden…",
        "waiting.matched": "Het is een match! Je gesprek wordt geopend…",
        # --- shared profile form (_profile_fields.html) ---
        "form.select": "— Kies —",
        "form.fill": "Vul in",
        "form.fill_all": "Vul alles in",
        "form.about_you": "Over jou",
        "form.name": "Naam",
        "form.age": "Leeftijd",
        "form.gender": "Geslacht",
        "form.seeking": "Op zoek naar",
        "form.add_more": "Meer toevoegen",
        "form.photos": "Foto's",
        "form.add_photos": "Foto's toevoegen",
        "form.set_main": "Stel de hoofdfoto in",
        "form.bio": "Over mij",
        "form.bio_ph": "Een paar zinnen over jezelf...",
        "form.interests": "Interesses",
        "form.location": "Locatie",
        "form.location_note": "Velvt is voorlopig alleen in Maastricht",
        "form.relationship_type": "Type relatie",
        "form.hobbies": "Hobby's",
        "form.hobbies_ph": "bijv. wandelen, gamen, schilderen",
        "form.wants": "Wat ik wil",
        "form.wants_ph": "Wat je hoopt te vinden...",
        "form.needs": "Wat ik nodig heb",
        "form.needs_ph": "Wat voor jou het belangrijkst is in een partner...",
        "form.physical": "Fysieke kenmerken",
        "form.height_cm": "Lengte (cm)",
        "form.height_ph": "bijv. 175",
        "form.eyes": "Ogen",
        "form.body_type": "Lichaamsbouw",
        "form.fitness_level": "Fitheidsniveau",
        "form.hair_colour": "Haarkleur",
        "form.tattoos": "Tatoeages",
        "form.prefs_heading": "Waar ik naar zoek (fysiek)",
        "form.height_from": "Lengte vanaf (cm)",
        "form.height_to": "Lengte tot (cm)",
        "form.body_types_drawn": "Lichaamsbouw die me aanspreekt",
        # --- live-search wizard ---
        "wiz.title": "Live zoeken — Velvt",
        "wiz.step": "Stap {n} van {total}",
        "wiz.q_relationship_1": "Waar ben je",
        "wiz.q_relationship_2": "naar op zoek?",
        "wiz.q_seeking_1": "Naar wie ben je",
        "wiz.q_seeking_2": "op zoek?",
        "wiz.q_age_1": "Welke leeftijd",
        "wiz.q_age_2": "zoek je?",
        "wiz.hint_age": "Laat het op de volle breedte staan voor geen voorkeur.",
        "wiz.q_location_1": "Waar ben je",
        "wiz.q_location_2": "aan het zoeken?",
        "wiz.hint_location": "We filteren niet op afstand — dit helpt alleen mensen die dat wél doen om jou te vinden.",
        "wiz.q_interests_1": "Deel je",
        "wiz.q_interests_2": "interesses?",
        "wiz.hint_interests": "Kies er geen voor geen voorkeur, of tot {max} om alleen mensen te ontmoeten die er minstens één delen.",
        "wiz.more": "+ Meer",
        "wiz.q_body_1": "Een bepaalde",
        "wiz.q_body_2": "lichaamsbouw?",
        "wiz.hint_body": "Kies er zoveel als je wilt, of geen voor geen voorkeur.",
        "wiz.skip": "Overslaan",
        "wiz.back_aria": "Vorige stap",
        "wiz.next_aria": "Volgende stap",
        "wiz.start_aria": "Begin met zoeken",
        "wiz.sheet_title": "Alle interesses",
        "wiz.sheet_close": "Sluiten",
        "wiz.custom_ph": "Iets anders…",
        "wiz.custom_aria": "Voeg je eigen interesse toe",
        "wiz.add": "Toevoegen",
        "wiz.done": "Klaar",
        "wiz.age_min_aria": "Minimumleeftijd",
        "wiz.age_max_aria": "Maximumleeftijd",

        # --- criteria screen ---
        "crit.title": "Zoek een match — Velvt",
        "crit.heading": "Wat is voor jou belangrijk?",
        "crit.subtitle": (
            "Alle filters, ook die de instelstappen niet vragen. Zet uit waarop "
            "je niet wilt filteren — hoe meer je aan laat staan, hoe minder "
            "mensen passen."
        ),
        "crit.change": "aanpassen",
        "crit.anywhere": "overal",
        "crit.within_km": "binnen {km} km",
        "crit.who": "Naar wie ik zoek",
        "crit.who_help": "Alleen mensen met een passend geslacht worden aan je gekoppeld. Zet uit om open te staan voor iedereen.",
        "crit.anyone": "Iedereen",
        "crit.age": "Leeftijdsbereik",
        "crit.age_help": "Alleen mensen binnen dit bereik worden aan je gekoppeld. Iedereen op Velvt is 18 of ouder.",
        "crit.distance": "Afstand",
        "crit.no_location": "Geen locatie ingesteld",
        "crit.any_distance": "{place} · elke afstand",
        "crit.within_of": "Binnen {km} km van {place}",
        "crit.distance_help": "Alleen mensen binnen je radius worden aan je gekoppeld. Zet uit om met iedereen te matchen, waar dan ook.",
        "crit.distance_change": "Wijzig de locatie of radius",
        "crit.physical": "Fysieke kenmerken",
        "crit.physical_summary": "Lengte, bouw, haar, ogen, tatoeages",
        "crit.physical_help": (
            "Alleen mensen die aan elk kenmerk voldoen dat je hier instelt "
            "worden aan je gekoppeld. Wat je leeg laat wordt niet gefilterd, "
            "dus je kunt alleen instellen wat voor jou uitmaakt."
        ),
        "crit.body_types": "Lichaamsbouw",
        "crit.fitness_level": "Fitheidsniveau",
        "crit.hair_colour": "Haarkleur",
        "crit.eye_colour": "Oogkleur",
        "crit.tattoos": "Tatoeages",
        "crit.no_preference": "Geen voorkeur",
        "crit.interests": "Interesses",
        "crit.interests_summary": "Matcht alleen mensen die er één delen",
        "crit.interests_help": (
            "Hiermee beperk je de groep tot mensen die er minstens één van "
            "delen. Van die mensen wordt degene met het meest gemeen als "
            "eerste gekoppeld."
        ),
        "crit.interests_ph": "bijv. muziek, wandelen",
        "crit.checking": "De groep wordt bekeken…",
        "crit.back": "Terug",
        "crit.start": "Begin met zoeken",
        "crit.you_are": "Je bent {gender}",
        "crit.unspecified_gender": "geslacht niet opgegeven",
        "crit.profile_note": "de filters van anderen gelden ook voor jou, dus houd {link} accuraat.",
        "crit.profile_link": "je profiel",
        "crit.pool_total_one": "1 persoon zoekt nu",
        "crit.pool_total_many": "{n} mensen zoeken nu",
        "crit.pool_fit_one": "1 persoon past bij wat je koos",
        "crit.pool_fit_many": "{n} mensen passen bij wat je koos",
        "crit.sugg_age": "Verbreed naar {min}–{max}",
        "crit.sugg_distance": "Match op elke afstand",
        "crit.sugg_gender": "Wijzig naar {seeking}",
        "crit.sugg_people_one": "1 persoon",
        "crit.sugg_people_many": "{n} mensen",

        # --- chat / match lifecycle ---
        "chat.title": "Gesprek — Velvt",
        "chat.match_found": "Match gevonden",
        "chat.you_matched": "Je hebt een match met",
        "chat.reveal_note": "Jullie zochten allebei naar elkaar. Foto's worden zichtbaar zodra jullie beiden doorgaan.",
        "chat.already_here": "{name} is al in de kamer",
        "chat.ask_about": "Vraag {pronoun} over",
        "chat.seconds": "seconden",
        "chat.reveal_aside": "Zeg ja om nu te beginnen — of wacht, dan opent het gesprek vanzelf.",
        "chat.not_this_one": "Deze niet",
        "chat.yes_start": "Ja, begin met chatten",
        "chat.times_up": "Tijd is om",
        "chat.continue_with": "Doorgaan met",
        "chat.five_over": "Je vijf minuten zijn voorbij.",
        "chat.they_decided": "{name} heeft al beslist.",
        "chat.you_chose": "Je koos {choice}.",
        "chat.waiting_for": "Wachten op {name}…",
        "chat.continue_word": "Doorgaan",
        "chat.unmatch_word": "Ontmatchen",
        "chat.continue_match": "Doorgaan met match",
        "chat.match_ended": "Match beëindigd",
        "chat.over_1": "Deze is",
        "chat.over_2": "voorbij",
        "chat.one_unmatched": "Een van jullie koos om te ontmatchen.",
        "chat.window_closed": "Het beslismoment sloot zonder antwoord van beide kanten.",
        "chat.your_chats": "Je gesprekken",
        "chat.search_again": "Opnieuw zoeken",
        "chat.back_aria": "Terug naar gesprekken",
        "chat.live": "live",
        "chat.matched_tag": "Match",
        "chat.timed_tag": "Op de klok",
        "chat.time_left": "Resterende tijd in deze kamer",
        "chat.neither_note": "Als geen van jullie doorgaat sluit de kamer, en niemand hoort wie twijfelde.",
        "chat.no_messages": "Nog geen berichten — breek het ijs!",
        "chat.you_chose_inline": "Je koos {choice} — wachten op {name}",
        "chat.to_continue": "om door te gaan",
        "chat.to_unmatch": "om te ontmatchen",
        "chat.not_decided": "{name} heeft nog niet beslist",
        "chat.input_ph": "Typ een bericht…",
        "chat.admin_view": "Beheerdersweergave — alleen de twee gematchte leden kunnen hier schrijven",
        "chat.send": "Verzenden",
        # --- server-side messages ---
        "msg.sign_in_first": "Meld je eerst aan.",
        "msg.admin_only": "Alleen de beheerder kan dat doen.",
        "msg.welcome": "Welkom! Stel nu je profiel in.",
        "msg.throttled": "Te veel pogingen. Wacht een paar minuten voordat je het opnieuw probeert.",
        "msg.bad_credentials": "Ongeldige gebruikersnaam of wachtwoord.",
        "msg.profile_saved": "Profiel opgeslagen.",
        "msg.no_such_profile": "Dat profiel bestaat niet.",
        "msg.profile_created": "Profiel voor {name} (@{username}) aangemaakt.",
        "msg.fill_profile_first": "Vul eerst je profiel in zodat anderen met jou kunnen matchen.",
        "msg.search_stopped": "Zoeken gestopt.",
        "msg.no_such_room": "Dat gesprek bestaat niet.",
        "msg.room_private": "Dat gesprek is privé.",
        "msg.name_required": "Vul je naam in.",
        "msg.age_invalid": "Vul een geldige leeftijd in.",
        "msg.age_range": "Leeftijd moet tussen {min} en {max} liggen.",
        "msg.pick_relationship": "Kies een type relatie uit de lijst.",
        "msg.pick_gender": "Kies een geslacht uit de lijst.",
        "msg.pick_seeking": "Kies uit de lijst naar wie je op zoek bent.",
        "msg.username_short": "Gebruikersnaam moet minimaal 3 tekens zijn.",
        "msg.password_short": "Wachtwoord moet minimaal 8 tekens zijn.",
        "msg.password_short_optional": "Wachtwoord moet minimaal 8 tekens zijn (of laat het leeg).",
        "msg.passwords_differ": "Wachtwoorden komen niet overeen.",
        "msg.username_taken": "Die gebruikersnaam is al bezet.",
        "msg.photo_too_big": "Elke foto moet kleiner zijn dan 2 MB.",
        "msg.photo_type": "Foto's moeten JPEG, PNG of WebP zijn.",
        "msg.photo_count": "Je kunt maximaal {max} foto's hebben.",
        "msg.choose_connection": "Kies wat voor connectie je wilt.",
        "msg.choose_seeking": "Kies naar wie je op zoek bent.",
        "msg.check_age_radius": "Controleer het leeftijdsbereik en de radius.",
        "msg.only_matched_write": "Alleen de twee gematchte leden kunnen in dit gesprek schrijven.",
        "msg.not_open_yet": "De match is nog niet open voor een gesprek.",
        "msg.times_up_decide": "Tijd is om — kies Doorgaan of Ontmatchen om verder te gaan.",
        "msg.match_ended": "Deze match is beëindigd.",
        "msg.empty_message": "Bericht mag niet leeg zijn.",
        # relative timestamps
        "time.now": "nu",
        "time.minutes": "{n}m",
        "time.hours": "{n}u",
        "time.days": "{n}d",
        # waiting-screen summary chips
        "chip.anyone": "Iedereen",
        "chip.any_age": "Elke leeftijd",
        "msg.radius_range": "Radius moet tussen 1 en {max} km liggen.",



    },
}


# Labels for the option lists whose *values* must stay canonical English --
# see the module docstring. A value with no entry here renders as-is, so a
# language can translate some and leave the rest.
OPTION_LABELS = {
    "nl": {
        # genders (profiles.gender)
        "Woman": "Vrouw",
        "Man": "Man",
        "Non-binary": "Non-binair",
        # seeking (searches.seeking)
        "Women": "Vrouwen",
        "Men": "Mannen",
        "Non-binary people": "Non-binaire mensen",
        "Everyone": "Iedereen",
        # relationship types
        "Long-term relationship": "Langdurige relatie",
        "Short-term relationship": "Kortdurende relatie",
        "Friendship": "Vriendschap",
        "Not sure yet": "Weet ik nog niet",
        # body types
        "Slim": "Slank",
        "Athletic": "Atletisch",
        "Average": "Gemiddeld",
        "Curvy": "Rondingen",
        "Muscular": "Gespierd",
        "Plus-size": "Plus-size",
        # fitness levels
        "Sedentary": "Weinig actief",
        "Lightly active": "Licht actief",
        "Active": "Actief",
        "Very active": "Zeer actief",
        "Athlete": "Atleet",
        # hair colours
        "Black": "Zwart",
        "Brown": "Bruin",
        "Blonde": "Blond",
        "Red": "Rood",
        "Grey/White": "Grijs/wit",
        "Other": "Anders",
        # eye colours ("Brown"/"Other" shared with hair above)
        "Blue": "Blauw",
        "Green": "Groen",
        "Hazel": "Hazelnootbruin",
        "Grey": "Grijs",
        # tattoos
        "None": "Geen",
        "A few": "Een paar",
        "Many": "Veel",
    },
}

# Interest keywords are matched by stemmed token overlap across everyone's
# searches, so the stored value has to be one shared vocabulary -- a Dutch
# user storing "koken" would never match an English user's "cooking". These
# translate the chip *label* only; the value posted stays the English key.
INTEREST_LABELS = {
    "nl": {
        "anime": "anime", "art": "kunst", "board games": "bordspellen",
        "books": "boeken", "cars": "auto's", "cooking": "koken",
        "cycling": "fietsen", "festivals": "festivals", "films": "films",
        "food": "eten", "football": "voetbal", "gaming": "gamen",
        "gardening": "tuinieren", "hiking": "wandelen", "jazz": "jazz",
        "languages": "talen", "museums": "musea", "music": "muziek",
        "photography": "fotografie", "poetry": "poëzie", "sailing": "zeilen",
        "techno": "techno", "travel": "reizen", "whisky": "whisky",
        "wine": "wijn",
    },
}


def normalize_language(code):
    """Map anything user- or browser-supplied onto a language we actually have.

    Accepts "nl", "NL", "nl-NL", "nl_BE" and friends. Returns None when there
    is no match, so callers can tell "not offered" from "chose the default".
    """
    if not code:
        return None
    code = str(code).strip().lower().replace("_", "-")
    if code in LANGUAGE_CODES:
        return code
    base = code.split("-")[0]
    return base if base in LANGUAGE_CODES else None


def translate(lang, key, **kwargs):
    """Look up one string, falling back rather than failing.

    Order: requested language -> DEFAULT_LANGUAGE -> the key itself. A missing
    translation therefore shows English, and a missing *key* shows the key,
    which is ugly on screen but harmless -- far better than a 500 on a page
    someone is trying to read. Same reason the format() is guarded: a
    translation with a typo'd placeholder degrades to the unformatted string
    instead of taking the page down.
    """
    catalogue = TRANSLATIONS.get(lang) or {}
    text = catalogue.get(key)
    if text is None:
        text = TRANSLATIONS[DEFAULT_LANGUAGE].get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def option_label(lang, value):
    """Display text for a stored option value. Returns it unchanged when the
    language has no translation for it, so stored values stay canonical."""
    if not value:
        return value
    return OPTION_LABELS.get(lang, {}).get(value, value)


def interest_label(lang, value):
    """Display text for an interest keyword; the stored value is unchanged."""
    if not value:
        return value
    return INTEREST_LABELS.get(lang, {}).get(value, value)


def missing_keys(lang):
    """Keys present in English but absent from `lang`. Used by the checker."""
    base = set(TRANSLATIONS[DEFAULT_LANGUAGE])
    return sorted(base - set(TRANSLATIONS.get(lang) or {}))
