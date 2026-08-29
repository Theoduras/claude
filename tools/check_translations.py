#!/usr/bin/env python3
"""Report translation gaps, and copy that never got wired up.

    python tools/check_translations.py

Nothing here is enforced at runtime -- translate() falls back to English and
then to the key, so a gap degrades rather than breaks. This is the thing that
tells you a gap exists. Exits non-zero when it finds one, so it can gate a
commit if you ever want it to.

Three checks:
  1. keys English has that another language doesn't  (that screen shows English)
  2. keys a language has that English doesn't        (usually a typo'd key)
  3. keys defined but referenced nowhere             (dead copy)
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from translations import (  # noqa: E402
    DEFAULT_LANGUAGE,
    LANGUAGES,
    OPTION_LABELS,
    TRANSLATIONS,
)

problems = 0


def scanned_sources():
    """Every file that could reference a key: app.py plus the templates."""
    yield os.path.join(ROOT, "app.py")
    tpl = os.path.join(ROOT, "templates")
    for name in sorted(os.listdir(tpl)):
        if name.endswith(".html"):
            yield os.path.join(tpl, name)


used = set()
for path in scanned_sources():
    with open(path, encoding="utf-8") as fh:
        body = fh.read()
    # t('key'), t("key"), translate(lang, "key")
    used.update(re.findall(r"""\bt\(\s*['"]([\w.]+)['"]""", body))
    used.update(re.findall(r"""translate\([^,]+,\s*['"]([\w.]+)['"]""", body))

base = TRANSLATIONS[DEFAULT_LANGUAGE]
print(f"{DEFAULT_LANGUAGE}: {len(base)} keys, {len(used)} referenced in code\n")

for code, name in LANGUAGES:
    if code == DEFAULT_LANGUAGE:
        continue
    catalogue = TRANSLATIONS.get(code) or {}
    missing = sorted(set(base) - set(catalogue))
    extra = sorted(set(catalogue) - set(base))
    identical = sorted(
        k for k in set(base) & set(catalogue)
        if base[k] == catalogue[k] and len(base[k]) > 3 and not base[k][0].isdigit()
    )

    print(f"--- {code} ({name}) : {len(catalogue)} keys")
    if missing:
        problems += len(missing)
        print(f"    MISSING {len(missing)} (these render in {DEFAULT_LANGUAGE}):")
        for k in missing:
            print(f"      {k}")
    if extra:
        problems += len(extra)
        print(f"    UNKNOWN {len(extra)} (not in {DEFAULT_LANGUAGE} -- typo?):")
        for k in extra:
            print(f"      {k}")
    if identical:
        # Not an error: "Privacy", "Contact" and "jazz" are genuinely the same
        # word in both. Worth eyeballing once, though.
        print(f"    same as {DEFAULT_LANGUAGE} ({len(identical)}) -- check these are "
              f"deliberate: {', '.join(identical[:12])}"
              f"{' …' if len(identical) > 12 else ''}")
    if not missing and not extra:
        print("    complete")
    print()

unused = sorted(set(base) - used)
if unused:
    print(f"--- defined but never referenced ({len(unused)}):")
    for k in unused:
        print(f"      {k}")
    print("    (dead copy, or a key built dynamically -- check before deleting)")
    print()

# Option labels are keyed by canonical English value, not by dotted key, so
# they get their own coverage note.
print("--- option labels (profile dropdowns)")
for code, name in LANGUAGES:
    if code == DEFAULT_LANGUAGE:
        continue
    n = len(OPTION_LABELS.get(code, {}))
    print(f"    {code}: {n} values translated"
          + ("" if n else "  (dropdowns will show English)"))

print()
if problems:
    print(f"FAIL: {problems} key problem(s)")
    sys.exit(1)
print("OK: every language has every key")
