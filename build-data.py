#!/usr/bin/env python3
"""
Build rotmg-data.json (and inline it into roadmap.html) from the client's own XML.

Use build.ps1 rather than calling this directly - sprites have to be packed first.
Nothing here touches the network.

Reads (in place, never modifies):
    <your extracted assets>/xml/{players,equip,enchantments,portals}.xml
"""

import base64
import json
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
def asset_root():
    """Where the extracted client assets live.

    Resolved, in order: the ROTMG_ASSETS environment variable, a local (git-ignored)
    assets-path.txt beside this script, then the historical sibling default.

    Why the indirection: this repo is published so friends can install the app, and the
    extractor that produces these assets is a separate tool that this project deliberately
    does not link itself to. Hard-coding its path put its name in every published copy.
    """
    env = os.environ.get("ROTMG_ASSETS")
    if env and os.path.isdir(env):
        return os.path.abspath(env)
    local = os.path.join(HERE, "assets-path.txt")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            cand = f.read().strip()
        if cand and os.path.isdir(cand):
            return os.path.abspath(cand)
    return os.path.normpath(os.path.join(HERE, "..", "rotmg-assets"))


ASSETS = asset_root()
XML = os.path.join(ASSETS, "xml")
OUT = os.path.join(HERE, "rotmg-data.json")

SLOT_NAMES = {
    1: "Sword", 2: "Dagger", 3: "Bow", 4: "Tome", 5: "Shield", 6: "Leather Armor",
    7: "Heavy Armor", 8: "Wand", 9: "Ring", 10: "Consumable", 11: "Spell", 12: "Seal",
    13: "Cloak", 14: "Robe", 15: "Quiver", 16: "Helm", 17: "Staff", 18: "Poison",
    19: "Skull", 20: "Trap", 21: "Orb", 22: "Prism", 23: "Scepter", 24: "Katana",
    25: "Star", 27: "Wakizashi", 28: "Lute", 29: "Mace", 30: "Sheath", 31: "Sigil",
}

# ORG_* -> dungeon name. Codes we cannot confidently name are ABSENT on purpose:
# the UI shows the raw code rather than a guess, because a wrong dungeon costs
# somebody an evening of farming.
ORG_NAMES = {
    "ABYSS": "Abyss of Demons", "CASTLE": "Oryx's Castle", "CDEPTHS": "The Crawling Depths",
    "CEM": "Haunted Cemetery", "CLAND": "Candyland Hunting Grounds", "CRYSTAL": "Crystal Cavern",
    "CULT": "Cultist Hideout", "DAVY": "Davy Jones' Locker", "DDOCKS": "Deadwater Docks",
    "FMAZE": "Forest Maze", "FUNGAL": "Fungal Cavern", "HIVE": "The Hive",
    "HTT": "High Tech Terror", "ICECAVE": "Ice Cave", "KOGBOLD": "Kogbold Steamworks",
    "LAB": "Mad Lab", "LH": "Lost Halls", "LIBRARY": "Cursed Library",
    "LOD": "Lair of Draconis", "MANOR": "Manor of the Immortals", "MOONLIGHT": "Moonlight Village",
    "MTEMPLE": "Mountain Temple", "NEST": "The Nest", "ORYXMAS": "Oryxmas (event)",
    "OSANC": "Oryx's Sanctuary", "OTRENCH": "Ocean Trench", "PARASITE": "Parasite Chambers",
    "PCAVE": "Pirate Cave", "PUPPET": "Puppet Master's Theatre", "REEF": "Cnidarian Reef",
    "RUINS": "Ancient Ruins", "SETPIECE": "Realm setpiece", "SEWER": "Toxic Sewers",
    "SHAITAN": "Lair of Shaitan", "SHTT": "The Shatters", "SPECTRAL": "Spectral Penitentiary",
    "SPIDER": "Spider Den", "SPIT": "Snake Pit", "SPRITE": "Sprite World",
    "TOMB": "Tomb of the Ancients", "UDL": "Undead Lair", "VOID": "The Void",
    "WETLANDS": "Sulfurous Wetlands", "WLAB": "Woodland Labyrinth", "3D": "The Third Dimension",
    "UMI": "Moonlight Village — secret boss",
    # These five were left raw until the portal list confirmed them. Each name below is
    # a DungeonPortal DisplayId read out of the client - not inferred from item names.
    "JUNGLE": "Forbidden Jungle", "ENCORE": "Puppet Master's Encore",
    "TAVERN": "The Tavern", "THICKET": "Secluded Thicket", "MWOODS": "Magic Woods",
}

ORG_NOTES = {
    "UMI": "Secret boss after the Moonlight Village boss. Only spawns if the run was completed "
           "to the required proficiency — a bad run will not open it.",
}

# Non-dungeon source labels. REALMWHITE's exact meaning is NOT documented in the data;
# inspecting its 101 members shows event whites, seasonal variants and reskins
# (Helm of the Juggernaut - Chaos/Jade/Midas, Fossilized Skull, Dirk of Cronus).
# So it is named descriptively and given no invented explanation.
SPECIAL_SOURCES = {
    "REALMWHITE": ("Event / realm white", "Not tied to one dungeon."),
    "ALIEN": ("Alien Invasion (event)", None),
    "NEO_ALIEN": ("Alien Invasion — Neo (event)", None),
}

STATS = ["MAXHP", "MAXMP", "ATT", "DEF", "SPD", "DEX", "VIT", "WIS"]

# Slots that hold an actual weapon. Only these get a comparable DPS number.
WEAPON_SLOTS = {1, 2, 3, 8, 17, 24}

# Low-tier tiered gear is noise: nobody farms a T4 sword, and 300-odd of them bury the
# items that matter. Tate's cutoffs. The kind comes from the item's OWN <Labels>, not from
# the slot number - the game already says WEAPON / ARMOR / ABILITY / RING.
TIER_FLOOR = {"WEAPON": 13, "ARMOR": 13, "ABILITY": 6, "RING": 6}


def tier_num(labels):
    """The T-number on a tiered item, or None when it carries no T label."""
    for l in labels:
        m = re.fullmatch(r"T(\d+)", l)
        if m:
            return int(m.group(1))
    return None


def below_floor(labels):
    """True for tiered gear beneath its kind's cutoff. Untiered gear is never dropped,
    and a tiered item with no T label at all is KEPT - we cannot judge it."""
    if "TIERED" not in labels:
        return False
    n = tier_num(labels)
    if n is None:
        return False
    for kind, floor in TIER_FLOOR.items():
        if kind in labels:
            return n < floor
    return False

# Portal rows that are not places you farm.
PORTAL_SKIP = re.compile(r"^(Legacy |Admin|Test|Easter|Snowball|Tutorial)|Arena|Test Map", re.I)


def read(name):
    p = os.path.join(XML, name)
    if not os.path.exists(p):
        sys.exit("missing: %s\nRe-extract assets in Tomato first." % p)
    with open(p, encoding="utf-8", errors="ignore") as f:
        return f.read()


def tag(body, name):
    # Elements routinely carry attributes - <MaxHitPoints max="700">100</MaxHitPoints>,
    # <Texture xOffset="0">. Requiring a bare <X> silently returns None and the field
    # just vanishes. This has already cost us item sprites, enchant slots and class stats.
    m = re.search(r"<%s[^>]*>([^<]*)</%s>" % (name, name), body)
    return m.group(1).strip() if m else None


def tag_attr(body, name, attr):
    """Read an attribute off an element, e.g. the max="" on a class stat."""
    m = re.search(r'<%s([^>]*)>' % name, body)
    if not m:
        return None
    a = re.search(r'%s="([^"]*)"' % attr, m.group(1))
    return a.group(1) if a else None


def num(body, name):
    v = tag(body, name)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def clean_desc(d):
    if not d:
        return ""
    d = d.replace(chr(92) + "n", " ").replace(chr(10), " ")
    d = re.sub(r"\s*Sprite Credits?:.*$", "", d, flags=re.I | re.S)
    return re.sub(r"\s+", " ", d).strip()


def ench_slots(body):
    """<EnchantmentSlots> is a self-closing element with ATTRIBUTES, not a text node.
    The slot count is the length of the slotChance list ("0.5,0.375,0.25,0.125" -> 4)."""
    m = re.search(r"<EnchantmentSlots([^>]*)/?>", body)
    if not m:
        return None
    sc = re.search(r'slotChance="([^"]*)"', m.group(1))
    if sc:
        return len([x for x in sc.group(1).split(",") if x.strip()])
    mx = re.search(r'maxNumber="(\d+)"', m.group(1))
    return int(mx.group(1)) if mx else None


def ench_chance(body):
    """Per-slot roll probability. 1.0 = that slot is guaranteed on every drop.
    This varies a lot (1,1,1,1 = always 4 slots) and is the number a min/maxer wants."""
    m = re.search(r"<EnchantmentSlots([^>]*)/?>", body)
    if not m:
        return None
    sc = re.search(r'slotChance="([^"]*)"', m.group(1))
    if not sc:
        return None
    out = []
    for x in sc.group(1).split(","):
        try:
            out.append(float(x))
        except ValueError:
            pass
    return out or None


def ench_dust(body):
    """Dust type and per-slot cost - the actual currency of enchanting."""
    m = re.search(r"<EnchantmentSlots([^>]*)/?>", body)
    if not m:
        return None
    t = re.search(r'dustType="([^"]*)"', m.group(1))
    a = re.search(r'dustAmounts="([^"]*)"', m.group(1))
    if not t and not a:
        return None
    return {"type": t.group(1) if t else None, "amounts": a.group(1) if a else None}


def norm_dungeon(name):
    """Normalise a dungeon or key name so the two can be joined."""
    n = re.sub(r"\s*Key\s*$", "", name or "", flags=re.I)
    n = re.sub(r"^(Solo|Guild|Cursed|Augmented|Enchanted|Advanced|Heroic)\s+", "", n, flags=re.I)
    n = re.sub(r"\s*Portal\s*$", "", n, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", n.lower())


def dungeon_difficulty():
    """The client DOES ship difficulty - on dungeon KEYS in equipKeys.xml, 0-10.
    An earlier build claimed it did not exist, because a grep for '<Difficulty'
    never matches '<DungeonDifficulty'."""
    path = os.path.join(XML, "equipKeys.xml")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        xml = f.read()
    out = {}
    for kid, _oa, body in objects(xml):
        d = num(body, "DungeonDifficulty")
        if d is None:
            continue
        out.setdefault(norm_dungeon(kid), d)
    return out



# ---------------------------------------------------------------------------
# Order-independent XML primitives.
#
# This project has now lost data EIGHT times to regexes that assumed a shape the
# client does not guarantee. The last one assumed attribute ORDER:
#   <EffectInfo name=".." description=".."/>   1,641 occurrences
#   <EffectInfo description=".." name=".."/>   1,858 occurrences
# A name-first regex silently dropped 53% of them. Parse attributes into a dict;
# never match them positionally.
# ---------------------------------------------------------------------------

SKIN_WORD_MATCHES = []
ATTR_RE = re.compile(r'([A-Za-z_][\w:.-]*)\s*=\s*"([^"]*)"')
DROP_RE = re.compile(
    r"(?:defeating|entertaining|completing)\s+(?:the\s+)?(.+?)\s+in\s+(?:the\s+)?(.+?)\.?$")
FAILURES = []


def attrs(open_tag_inner):
    """Attributes of an open tag, order-independent."""
    return dict(ATTR_RE.findall(open_tag_inner or ""))


def elems(body, name):
    """Every <name ...> in body as (attrdict, inner_text).
    Handles self-closing, paired, and attribute-bearing forms alike."""
    out = []
    for m in re.finditer(r"<%s(?=[\s/>])([^>]*?)(/?)>" % name, body):
        a = attrs(m.group(1))
        if m.group(2):
            out.append((a, ""))
        else:
            close = re.search(r"</%s>" % name, body[m.end():])
            out.append((a, body[m.end(): m.end() + close.start()] if close else ""))
    return out


def guard(xml, name, parsed, label=""):
    """Count how many <name> exist vs how many we consumed. Any shortfall means a
    shape we did not anticipate - which is exactly how the previous eight bugs hid."""
    seen = len(re.findall(r"<%s[\s/>]" % name, xml))
    if seen and parsed < seen:
        FAILURES.append("%s: %d <%s> present, %d parsed (%.0f%%)"
                        % (label or name, seen, name, parsed, 100.0 * parsed / seen))
    return seen


# ---------------------------------------------------------------------------
# Source resolution
#
# An item's origin comes from several places, at different confidence. They are
# resolved in order and tagged with a `kind` so the UI can be honest about which
# is a fact from the game files and which is community knowledge.
#
#   dungeon   ORG_* label, forge dismantle label, or <CommonDungeon>   (client)
#   set       setName attribute -> an ST set                          (client)
#   event     event/campaign label                                    (client)
#   community RealmEye's "Untiered Items by Dungeon" page             (external)
# ---------------------------------------------------------------------------

# Event and campaign labels. The client states these; the human names are ours.
EVENT_LABELS = {
    "RETROWINDS": "Retrowinds (event)", "MOTMG_2024": "MotMG 2024",
    "MOTMG2023": "MotMG 2023", "HALLOWEEN_2024": "Halloween 2024",
    "ORYXMAS_ENCHANTABLE": "Oryxmas", "FROST_ENCHANTABLE": "Frost event",
    "VALENTINE_ENCHANTABLE": "Valentine's", "EASTER_ENCHANTABLE": "Easter",
    "EASTER_UT": "Easter", "HALLOWEEN_ENCHANTABLE": "Halloween",
    "THANKSGIVING_ENCHANTABLE": "Thanksgiving", "AOO": "Agents of Oryx",
    "LEGION_ELITE": "Legion Elite", "VENERABLE": "Venerable",
    "GLORY": "Glory", "INSIGHT": "Insight", "REHEARSAL": "Shatters Rehearsal",
    "HYDROFLOW": "Hydroflow (event)", "INTERREGNUM": "Court of Oryx",
    "MATRIX_ARMOR": "Matrix", "BEEHEMOTH": "Beehemoth",
}


def load_equipment_sets():
    """equipmentsets.xml: 125 sets, their pieces, and their 2/3/all-piece bonuses."""
    path = os.path.join(XML, "equipmentsets.xml")
    if not os.path.exists(path):
        return {}, {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        xml = f.read()
    sets, piece_to_set = {}, {}
    # INSTANCE #9 of this project's recurring bug class. The file's ROOT tag is the plural
    # <EquipmentSets>, and <EquipmentSet([^>]*)> happily matches it - capturing "s" as the
    # attribute string, then running to the first </EquipmentSet> and swallowing the first
    # real set whole. Exactly the <Difficulty> / <DungeonDifficulty> shape; Angelic Bard
    # Set was disappearing this way. (?=[\s/>]) fixes it: in "<EquipmentSets>" there is no word
    # boundary between "t" and "s".
    for m in re.finditer(r"<EquipmentSet(?=[\s/>])([^>]*)>(.*?)</EquipmentSet>", xml, re.S):
        attrs, body = m.group(1), m.group(2)
        sid = re.search(r'id="([^"]*)"', attrs)
        stype = re.search(r'type="([^"]*)"', attrs)
        if not sid:
            continue
        name = sid.group(1)
        pieces = re.findall(r'<Setpiece[^>]*itemtype="([^"]*)"', body)
        bonuses = {}
        for tier, tag_name in (("all", "ActivateOnEquipAll"), ("3", "ActivateOnEquip3"),
                               ("2", "ActivateOnEquip2")):
            rows = []
            for bm in re.finditer(r'<%s([^>]*)>([^<]*)<' % tag_name, body):
                st = re.search(r'stat="(\w+)"', bm.group(1))
                am = re.search(r'amount="(-?[\d.]+)"', bm.group(1))
                if st and am and bm.group(2).strip() == "IncrementStat":
                    rows.append({"stat": st.group(1), "amt": float(am.group(1))})
            if rows:
                bonuses[tier] = rows
        sets[name] = {"name": name, "type": stype.group(1) if stype else None,
                      "pieces": pieces, "bonuses": bonuses}
        guard(body, "Setpiece", len(pieces), "%s setpieces" % name)
        for pt in pieces:
            # 145 itemtypes belong to more than one set; first writer wins so a piece keeps
            # the set it shipped with rather than the last one parsed.
            piece_to_set.setdefault(pt.lower(), name)
    guard(xml, "EquipmentSet", len(sets), "equipmentsets.xml")
    return sets, piece_to_set


def load_forge_sources():
    """forgeProperties.xml <RequireDismantleWithLabel>ORG_MANOR</..> - a validated
    dungeon proxy (459/484 exact agreement with items' own ORG_ labels)."""
    path = os.path.join(XML, "forgeProperties.xml")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8", errors="ignore") as f:
        xml = f.read()
    out = {}
    for m in re.finditer(r"<ForgeProperties(?=[\s/>])([^>]*)>(.*?)</ForgeProperties>", xml, re.S):
        fid = re.search(r'id="([^"]*)"', m.group(1))
        if not fid:
            continue
        for lm in re.finditer(r"<RequireDismantleWithLabel[^>]*>([^<]*)</RequireDismantleWithLabel>",
                              m.group(2)):
            # This is sometimes a LIST: "ORG_LH,ORG_CULT,ORG_VOID". Taking lab[4:]
            # on the whole string yields garbage and the field vanishes.
            codes = [t.strip()[4:] for t in lm.group(1).split(",")
                     if t.strip().startswith("ORG_")]
            if codes:
                out.setdefault(fid.group(1), codes)
    return out


def load_drop_locations():
    """<EffectInfo name="Drop location" description="Obtained by defeating X in the Y"/>
    A verbatim boss->dungeon dictionary. Attribute ORDER varies (39 name-first,
    15 description-first), so parse attributes into a dict - never positionally."""
    eq = read("equip.xml")
    found = 0
    out = {}
    for a, _ in elems(eq, "EffectInfo"):
        if a.get("name") != "Drop location":
            continue
        found += 1
        text = a.get("description", "")
        m = DROP_RE.search(text)
        if not m:
            continue
        dungeon = m.group(2).strip().rstrip(".")
        out[norm_dungeon(dungeon)] = {"boss": m.group(1).strip(),
                                      "dungeon": dungeon, "text": text}
    if found != 54:
        FAILURES.append("Drop location: expected 54 entries, parsed %d" % found)
    return out


def load_community_sources():
    """RealmEye's "Untiered Items by Dungeon" page, captured once into data/.
    Community knowledge, NOT game data - every entry is labelled as such."""
    path = os.path.join(HERE, "data", "realmeye-untiered-by-dungeon.tsv")
    if not os.path.exists(path):
        return {}
    TAB = chr(9)
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip(chr(10)).rstrip(chr(13))
            if TAB not in line:
                continue
            dungeon, items = line.split(TAB, 1)
            for it in items.split("|"):
                nm = it.strip()
                if not nm:
                    continue
                out.setdefault(norm_name(nm), dungeon.strip())
    return out


# Event name -> the distinctive word in the chest object's id. Everything else falls
# back to the plain "Event Chest" object, which is what the game shows for a generic one.
CHEST_WORDS = [("oryxmas", "Xmas"), ("frost", "Frozen"), ("halloween", "Halloween"),
               ("motmg", "MotMG"), ("easter", "Easter"), ("alien", "Alien"),
               ("shaitan", "Shaitan"), ("thanksgiving", "Turkey"),
               ("valentine", "Valentine"), ("court of oryx", "O2 Court")]


def chest_cell(event_name, cells):
    """Sprite cell for the chest an event pays out from. Falls back to the generic one
    rather than guessing a themed chest that may not exist."""
    low = (event_name or "").lower()
    for needle, word in CHEST_WORDS:
        if needle in low:
            for k, cell in cells.items():
                if k.startswith("chest:") and word.lower() in k.lower():
                    return cell
    return cells.get("chest:Event Chest")


def ench_mutations(body):
    """Every stat an enchantment moves.

    INSTANCE #10 of this project's recurring bug class. This was
        <ActivateOnEquip amount=".." stat="..">
    read positionally, which caught 865 of the 1,206 in enchantments.xml and silently
    dropped 341: the 284 that carry a third attribute (statRelativeTo), 50 amount-only
    and 7 mult-only. The 284 are precisely the enchantments that SCALE off another stat -
    the same distinction that once shipped Conqueror's Crown as a flat +25 ATT helm.
    Flat and scaled are kept in separate fields so the UI can never add them together.
    """
    out = []
    for a, _ in elems(body, "ActivateOnEquip"):
        row = {}
        if a.get("stat"):
            row["stat"] = a["stat"]
        if a.get("amount"):
            row["amt"] = a["amount"]
        if a.get("mult") or a.get("multiplier"):
            row["mult"] = a.get("mult") or a.get("multiplier")
        if a.get("statRelativeTo"):
            row["of"] = a["statRelativeTo"]
        if row:
            out.append(row)
    return out


# Everything inside <Mutators> that is a plain multiplier on the weapon itself. These are
# the numbers behind "Increases Weapon Damage by 5%" - the percentage is ONLY in the
# English description, but the multiplier is right here as 1.05, machine-readable, and
# the build had never read it. INSTANCE #12 of this project's recurring bug class: a whole
# element family sitting in a file the build already opens.
#
# projectileId="-1" and subAttackIndex="-1" both mean "all of them", and 84 of the 85
# occurrences say -1. The one exception is Ice Rush, whose MultiplyLifetimeMS targets
# projectile 0 - so the target is recorded alongside the value rather than assumed away,
# and the UI can say which projectile it applies to.
MUTATOR_FIELDS = {
    "MultiplyMinDamage": "dmgMin", "MultiplyMaxDamage": "dmgMax",
    "MultiplyRateOfFire": "rof",   "MultiplySpeed": "speed",
    "MultiplyLifetimeMS": "life",  "MultiplySize": "size",
    "MultiplyMPCost": "mp",
}


def ench_multipliers(body, eid):
    """The multiplicative half of an enchantment: what it does to the weapon, not to you."""
    out = {}
    for m in re.finditer(r"<Mutators>(.*?)</Mutators>", body, re.S):
        for name, field in MUTATOR_FIELDS.items():
            for a, inner in elems(m.group(1), name):
                target = a.get("projectileId") or a.get("subAttackIndex")
                try:
                    out[field] = round(float(inner.strip()), 6)
                except ValueError:
                    FAILURES.append("%s: %s is not a number (%r)" % (eid, name, inner))
                    continue
                if target is not None and target != "-1":
                    out.setdefault("only", {})[field] = target
    return out


METHOD_NOTE = {
    "xml-crossref": "Traced through the client's own cross-references between XML files.",
    "description": "Stated in the item's own description or effect text.",
    "neighbour-order": "Inferred from the items released alongside it in equip.xml.",
    "sprite-sheet": "Inferred from its position in the client's sprite sheet.",
}


def skin_key(name, class_names):
    """Normalise a set name and a skin name onto the same key.

    Three differences have to be absorbed: the skin is suffixed " Skin", the skin usually
    drops the class word ("Phylactery Set Skin" for "Phylactery Mystic Set"), and some
    sets carry a "Legacy " prefix the skin does not.
    """
    n = re.sub(r"\s*Skin\s*$", "", name or "", flags=re.I)
    n = re.sub(r"\s*Set\s*$", "", n, flags=re.I)
    n = re.sub(r"^Legacy\s+", "", n, flags=re.I)
    for c in class_names:
        n = re.sub(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(c), " ", n, flags=re.I)
    return re.sub(r"[^a-z0-9]", "", n.lower())


SKIN_STOPWORDS = {"set", "skin", "the", "of", "a", "and", "mini", "new", "legacy", "st"}


def skin_tokens(name, class_names):
    """Distinctive words in a set or skin name, class words and filler removed.

    The exact-key join gets 69 of 111. The rest differ only by word order or a leftover
    filler word - "Easter Set Knight" vs "Easter Knight Set", "Geb Set Skin" vs "Priest of
    Geb Set" - so compare the word SETS instead. Deliberately conservative: a pairing is
    only accepted when every distinctive word of the shorter name appears in the longer,
    which keeps "Raijin Disciple" from grabbing "Raijin Ninja".
    """
    n = re.sub(r"(?<=[a-z])ST(?![A-Za-z])", " ", name or "")
    for c in class_names:
        n = re.sub(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(c), " ", n, flags=re.I)
    words = re.findall(r"[A-Za-z]+", n.lower())
    return frozenset(w for w in words if w not in SKIN_STOPWORDS and len(w) > 2)


def load_set_skins(class_names):
    """Set name key -> the skin object id of the outfit a full ST set turns you into.

    The client marks them itself: <UnlockSpecial>Set Skin</UnlockSpecial>, 86 of them in
    skins.xml. A completed ST set changes your character's outfit, so the outfit is the
    honest icon for the set - not one of its weapons.
    """
    path = os.path.join(XML, "skins.xml")
    if not os.path.exists(path):
        return {}
    # class type hex -> class name, so a skin can be checked against the set's class
    by_type = {}
    for cid, ca, _b in objects(read("players.xml")):
        if ca.get("type"):
            try:
                by_type[int(ca["type"], 16)] = cid
            except ValueError:
                pass
    out, by_tokens = {}, []
    for sid, _a, body in objects(read("skins.xml")):
        if "Set Skin" not in body:
            continue
        pct = tag(body, "PlayerClassType")
        try:
            cname = by_type.get(int(pct, 16)) if pct else None
        except ValueError:
            cname = None
        out.setdefault(skin_key(sid, class_names), sid)
        by_tokens.append((skin_tokens(sid, class_names), sid, cname))
    return out, by_tokens


def match_skin(set_name, exact, by_tokens, class_names):
    """The skin for a set: exact key first, then a conservative word-subset match."""
    sid = exact.get(skin_key(set_name, class_names))
    if sid:
        return sid, "key"
    want = skin_tokens(set_name, class_names)
    if not want:
        return None, None
    # The set must name a class, and the skin must be FOR that class. Without this gate a
    # single generic word carries the match: "Agents of Oryx I" grabbed "Oryx Set Skin",
    # and "Phantom Archer Set" grabbed "Undersea Phantom WIZARD Set Skin".
    set_class = next((c for c in class_names
                      if re.search(r"(?<![A-Za-z])%s(?![A-Za-z])" % re.escape(c),
                                   set_name or "", re.I)), None)
    if not set_class:
        return None, None
    hits = []
    for toks, cand, cname in by_tokens:
        if not toks or cname != set_class:
            continue
        short, long_ = (want, toks) if len(want) <= len(toks) else (toks, want)
        if short and short <= long_:
            hits.append(cand)
    # Ambiguity is a reason to show the weapon piece, not to pick one at random.
    return (hits[0], "words") if len(set(hits)) == 1 else (None, None)


def load_biome_bands():
    """Vertical extent of each biome's row in the bestiary infographic, so the app can jump
    to one and highlight it.

    Read by ten vision agents over overlapping slices of the 2019x5195 image; they were told
    not to guess a label they could not read, so unlabelled bands are absent rather than
    invented. NOTE the infographic is organised by realm BIOME - dungeons do not appear in
    it at all, so a dungeon door has nowhere to jump to. Only biome-shaped sources can link.
    """
    path = os.path.join(HERE, "data", "biome-bands.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("bands", {})


def load_unobtainable():
    """Items that can no longer be obtained - hidden by default in the roadmap.

    The client does NOT encode this. There is no LIMITED / RETIRED / UNOBTAINABLE token in
    any of the 4,240 items' <Labels>, and Ceremonial Wand even carries ORG_LIBRARY as
    though it still drops in the Cursed Library. So data/unobtainable.json is CURATED, not
    derived, and it is the one file in this project that needs a human.
    """
    path = os.path.join(HERE, "data", "unobtainable.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("items", {})


def load_derived_sources():
    """data/derived-sources.json - drop sources DERIVED from the local client XML for items
    that state none directly. Not scraped; see that file's _README. Every entry survived two
    independent adversarial refuters, both told to default to refuted, so 40 of the 107
    original claims are deliberately absent."""
    path = os.path.join(HERE, "data", "derived-sources.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("sources", {})


def norm_name(n):
    """Match item names across sources: RealmEye uses curly apostrophes, the client
    uses straight ones, and (SB)/Shiny suffixes must not block a match."""
    n = (n or "").replace("’", "'").replace("‘", "'")
    n = re.sub(r"\s*\((SB|Limited|Seasonal)\)\s*$", "", n)
    n = re.sub(r"\s+Shiny$", "", n)
    return re.sub(r"[^a-z0-9]", "", n.lower())


def objects(xml):
    """(id, attributes, body). setName / setType / type live in the Object's opening
    tag, not its body - a body-only reader misses all 385 set memberships outright."""
    out = []
    for m in re.finditer(r"<Object(?=[\s/>])([^>]*)>(.*?)</Object>", xml, re.S):
        a = attrs(m.group(1))
        if "id" in a:
            out.append((a["id"], a, m.group(2)))
    return out


# ---------------------------------------------------------------------------
# Pets
#
# Read this before changing anything here.
#
# The client ships the ENDPOINTS of every pet ability - the value at the ability's
# lowest level and at its highest - and nothing else. The four curve names it uses
# (exp_incr, dim_returns, exp_decr, linear) appear in pets.xml and in no other file
# in the dump, and no file defines what any of them compute. Nothing anywhere states
# what level range those endpoints span, and nothing relates feedPower to a pet level
# or to XP of any kind.
#
# So: this emits min, max and the curve NAME, verbatim. It does not interpolate, it
# does not name a level, and it does not convert feed into levels. A feed calculator
# that is confidently wrong sends someone to waste an evening of real drops.
# ---------------------------------------------------------------------------

# <FirstAbility> names a <Class>PetAbility</Class> id; the numbers live on a
# <Class>PetBehavior</Class> object with a DIFFERENT id. Five de-space cleanly
# ("Attack Far" -> AttackFar) and four do not, so this is a hand-written map rather
# than a string transform. Nine rows, all checkable by eye.
ABILITY_BEHAVIOR = {
    "Attack Close": "AttackClose",
    "Attack Mid": "AttackMid",
    "Attack Far": "AttackFar",
    "Heal": "Heal",
    "Magic Heal": "MagicHeal",
    "Electric": "ElectricZap",       # not "Electric"
    "Decoy": "PetDecoy",             # not "Decoy"
    "Rising Fury": "PetRisingFury",  # not "RisingFury"
    "Savage": "PetSavage",           # a real ability that no pet declares as its first
}


def load_pet_abilities():
    """The 9 pet abilities, each joined to the behaviour object that carries its numbers.

    Three shapes live in a <Parameters> block and all three matter:
        <MaxHeal min="10" max="90" curve="exp_incr" />   a scaling range
        <ThreatRange value="4.5" />                      a constant
        <ProjectileId value="CloseRangeAttack" />        a join to a <PetProjectile>
    """
    path = os.path.join(XML, "pets.xml")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="ignore") as f:
        px = f.read()

    behaviors, projectiles, abilities = {}, {}, []
    for oid, _oa, body in objects(px):
        if "<PetProjectile" in body:
            projectiles[oid] = {
                "id": oid,
                "min": num(body, "MinDamage"),
                "max": num(body, "MaxDamage"),
                "speed": num(body, "Speed"),
                "life": num(body, "LifetimeMS"),
            }
            continue
        if "<PetBehavior" in body:
            bb = elems(body, "BaseBehavior")
            base = bb[0][0].get("id") if bb else None
            params = []
            for _pa, pinner in elems(body, "Parameters"):
                # Every child of <Parameters> is a parameter. Read the attributes with
                # attrs() so ORDER never matters - the <EffectInfo> bug cost 53% of a
                # field to exactly that assumption.
                #
                # ElectricZap nests a whole <Effect> block - Type, Probability, Duration -
                # inside its parameters. Flattened, its "Duration" reads as the zap's
                # duration when it is the paralysis it applies. Tag the nested ones.
                for eff, einner in elems(pinner, "Effect"):
                    pinner = pinner.replace(einner, "")
                    for m in re.finditer(r"<([A-Za-z]\w*)(?=[\s/>])([^>]*?)/?>", einner):
                        a = attrs(m.group(2))
                        if a:
                            params.append({"name": m.group(1), "min": a.get("min"),
                                           "max": a.get("max"), "value": a.get("value"),
                                           "curve": a.get("curve"), "in": "Effect"})
                for m in re.finditer(r"<([A-Za-z]\w*)(?=[\s/>])([^>]*?)/?>", pinner):
                    a = attrs(m.group(2))
                    if not a:
                        continue
                    params.append({"name": m.group(1), "min": a.get("min"),
                                   "max": a.get("max"), "value": a.get("value"),
                                   "curve": a.get("curve")})
            behaviors[oid] = {"base": base, "params": params}
            continue
        if "<PetAbility" in body:
            abilities.append({"id": oid, "group": tag(body, "Group"),
                              "desc": clean_desc(tag(body, "Description"))})

    for a in abilities:
        b = behaviors.get(ABILITY_BEHAVIOR.get(a["id"], ""))
        if not b:
            FAILURES.append("pet ability %r has no behaviour object" % a["id"])
            continue
        a["base"] = b["base"]
        a["params"] = [{k: v for k, v in p.items() if v is not None} for p in b["params"]]
        # Damage for the three shoot abilities comes from a <PetProjectile>, joined on
        # ProjectileId. NOT on <ObjectId> - all three share "Pet Bullet 3", and that
        # object carries no damage at all, so an ObjectId join silently zeroes them.
        pid = next((p.get("value") for p in b["params"] if p["name"] == "ProjectileId"), None)
        if pid and pid in projectiles:
            a["proj"] = projectiles[pid]

    # Which starter pets open with which ability. Only the 70 Common pets declare one;
    # every Rare and Divine pet in the file declares none, because the loadout is
    # assigned server-side at hatch.
    firsts = {}
    for oid, _oa, body in objects(px):
        if "<Class>Pet</Class>" not in body:
            continue
        fa = tag(body, "FirstAbility")
        if fa:
            firsts.setdefault(fa, []).append(oid)
    for a in abilities:
        a["first"] = sorted(firsts.get(a["id"], []))

    guard(px, "PetAbility", len(abilities), "pet abilities")
    guard(px, "PetBehavior", len(behaviors), "pet behaviours")
    guard(px, "PetProjectile", len(projectiles), "pet projectiles")
    return abilities


def load_pet_food(cells, gone):
    """Everything the client itself marks as pet food, plus every egg.

    Roughly 5,000 objects carry a <feedPower> - almost anything can be sacrificed to a
    pet - so listing them all is noise. <PetFood /> is the client's own mark for the
    consumables that exist to be fed, and the eggs are what a new pet hatches from.
    Equippable gear keeps its feed power on the item itself, over in the Items table.

    PETBLACKLIST is a hard exclusion: 358 objects advertise a feedPower and carry that
    label, and the game will not accept them. Their stated number is a lie.
    """
    out = []
    for fn in sorted(os.listdir(XML)):
        if not fn.endswith(".xml"):
            continue
        egg_file = fn in ("equipEggs.xml", "permapets.xml")
        with open(os.path.join(XML, fn), encoding="utf-8", errors="ignore") as f:
            xml = f.read()
        if not egg_file and "<PetFood" not in xml:
            continue
        for oid, _oa, body in objects(xml):
            feed = tag(body, "feedPower")
            if feed is None:
                continue
            if not egg_file and "<PetFood" not in body:
                continue
            labels = [x.strip() for x in (tag(body, "Labels") or "").split(",") if x.strip()]
            if "PETBLACKLIST" in labels or "<AdminOnly" in body:
                continue
            # The curated unobtainable list carries the dev objects too - "Feed", whose
            # whole description is "Ultimate Feed Power.", sat at the top of this table at
            # twice the next real food. Marked, not deleted; the UI hides it by default.
            row = {"id": oid, "name": tag(body, "DisplayId") or oid,
                   "feed": int(float(feed)), "kind": "egg" if egg_file else "food",
                   "desc": clean_desc(tag(body, "Description")),
                   "bag": tag(body, "BagType"),
                   "gone": True if oid in gone else None}
            if egg_file:
                row["fam"] = tag(body, "PetFamily")
                row["rar"] = tag(body, "Rarity")
                row["pet"] = tag(body, "PetId")
            n = cells.get(("egg:" if egg_file else "food:") + oid)
            if n is not None:
                row["sp"] = n
            out.append({k: v for k, v in row.items() if v is not None and v != ""})
    out.sort(key=lambda r: (-r["feed"], r["name"]))
    return out


def load_feed_ladders():
    """What a tiered item is worth as feed, by slot and tier.

    Every tiered item in equip.xml sits on one of a handful of ladders keyed by slot -
    within a (slot, tier) pair the feed power is a single value, no exceptions. The
    ladders are DERIVED here rather than hard-coded: slots whose whole tier->feed table
    is identical get merged, so if a patch splits one apart this splits with it instead
    of quietly reporting the old grouping.
    """
    path = os.path.join(XML, "equip.xml")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="ignore") as f:
        eq = f.read()
    by_slot = {}
    for _oid, _oa, body in objects(eq):
        slot, tier, feed = tag(body, "SlotType"), tag(body, "Tier"), tag(body, "feedPower")
        if not slot or tier is None or feed is None:
            continue
        s = int(slot)
        if s == 10:
            continue        # potions and wines - consumables, not a gear ladder
        by_slot.setdefault(s, {}).setdefault(int(tier), set()).add(int(float(feed)))
    merged = {}
    for s, rows in by_slot.items():
        # A slot whose tiers disagree with themselves is a shape we did not anticipate;
        # say so rather than picking one silently.
        for t, vals in rows.items():
            if len(vals) > 1:
                FAILURES.append("feed ladder: slot %d tier %d has %d feed values"
                                % (s, t, len(vals)))
        key = tuple(sorted((t, sorted(v)[0]) for t, v in rows.items()))
        merged.setdefault(key, []).append(s)
    out = []
    for key, slots in merged.items():
        out.append({"slots": sorted(slots),
                    "names": [SLOT_NAMES.get(s, str(s)) for s in sorted(slots)],
                    "rows": [[t, f] for t, f in key]})
    out.sort(key=lambda l: -len(l["rows"]))
    return out


def load_pet_levels():
    """Community numbers for the one thing the client does not contain.

    Nothing in the 246 XML files relates feedPower to a pet level - no XP value, no
    per-level table, no cap by rarity. data/pet-levels.json is where a human puts a table
    they trust, and the app labels every number that comes from it as not-from-the-files.
    Empty by default, and the app is complete without it: an absent table means the level
    calculator is hidden, not that a number gets invented.
    """
    path = os.path.join(HERE, "data", "pet-levels.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    # A table with no stated provenance is exactly the thing this project refuses to
    # print, so an unsourced file counts as no file.
    if not (d.get("source") or "").strip():
        return None
    rows = sorted(([int(a), int(b)] for a, b in d.get("feedToLevel", [])),
                  key=lambda r: r[0])
    if not rows:
        return None
    return {"source": d["source"].strip(), "maxLevel": d.get("maxLevel") or {},
            "feedToLevel": rows}

def load_pet_yard():
    """The Pet Yard upgrades, with the gold and fame the client actually asks for."""
    path = os.path.join(XML, "staticobjects.xml")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8", errors="ignore") as f:
        xml = f.read()
    out = []
    for oid, _oa, body in objects(xml):
        if "<Class>YardUpgrader</Class>" not in body:
            continue
        # One of the five upgraders carries no price at all. Ship it as it is rather
        # than inventing a number for it.
        row = {"id": oid, "yard": tag(body, "PetYardType"),
               "price": num(body, "Price"), "fame": num(body, "Fame")}
        out.append({k: v for k, v in row.items() if v is not None})
    out.sort(key=lambda r: (r.get("price") is None, r.get("price") or 0))
    return out


def main():
    print("reading %s" % XML)

    # ---- classes -------------------------------------------------------------
    classes = []
    for cid, _oa, body in objects(read("players.xml")):
        st = tag(body, "SlotTypes")
        if not st:
            continue
        slots = [int(x) for x in st.split(",")[:4] if x.strip().lstrip("-").isdigit()]
        if len(slots) != 4:
            continue
        base, maxed = {}, {}
        # HpRegen/MpRegen are the XML names for VIT/WIS - that is the game's own naming,
        # not a mistake: VIT drives HP regen and WIS drives MP regen.
        for xml_name, key in (("MaxHitPoints", "MAXHP"), ("MaxMagicPoints", "MAXMP"),
                              ("Attack", "ATT"), ("Defense", "DEF"), ("Speed", "SPD"),
                              ("Dexterity", "DEX"), ("HpRegen", "VIT"), ("MpRegen", "WIS")):
            v = num(body, xml_name)
            if v is not None:
                base[key] = v
            mx = tag_attr(body, xml_name, "max")
            if mx is not None:
                try:
                    maxed[key] = float(mx)
                except ValueError:
                    pass
        # <Equipment> is the class's own starting gear, one entry per slot in SlotTypes
        # order. Using it for the slot tabs means the icons are real in-game art for
        # exactly the right slot type, and the client has no empty-slot placeholder
        # sprites of its own - I looked.
        eq = [x.strip() for x in (tag(body, "Equipment") or "").split(",")]
        classes.append({
            "name": cid, "slots": slots, "startGear": eq[:4],
            "slotNames": [SLOT_NAMES.get(s, "Slot %d" % s) for s in slots],
            "base": base, "max": maxed,
        })
    classes.sort(key=lambda c: c["name"])
    print("  classes: %d" % len(classes))

    # ---- source tables -------------------------------------------------------
    # Loaded once and consulted in confidence order inside the item loop.
    eqsets, piece_to_set = load_equipment_sets()
    set_by_type = {v["type"].lower(): k for k, v in eqsets.items() if v.get("type")}
    forge_src = load_forge_sources()
    drop_locs = load_drop_locations()
    community = load_community_sources()
    derived = load_derived_sources()
    gone = load_unobtainable()
    biome_bands = load_biome_bands()
    set_skins, set_skin_tokens = load_set_skins([c["name"] for c in classes])
    class_names = [c["name"] for c in classes]
    print("  sources: %d sets (%d pieces) | %d forge entries | %d drop locations | "
          "%d community rows | %d derived | %d set skins"
          % (len(eqsets), len(piece_to_set), len(forge_src), len(drop_locs),
             len(community), len(derived), len(set_skins)))
    print("  unobtainable (curated, hidden by default): %d" % len(gone))

    # ---- items ---------------------------------------------------------------
    items = []
    type_to_id = {}
    for iid, oattr, body in objects(read("equip.xml")):
        slot_raw = tag(body, "SlotType")
        if slot_raw is None:
            continue
        slot = int(slot_raw)
        if slot == 10:
            continue
        labels = [x.strip() for x in (tag(body, "Labels") or "").split(",") if x.strip()]
        if "EQUIPMENT" not in labels:
            continue

        sources = []
        for lab in labels:
            if lab.startswith("ORG_"):
                o = lab[4:]
                b = re.sub(r"_(S|CORE|SHINY|CORE_SHINY)$", "", o)
                sources.append({"kind": "dungeon", "code": o,
                                "name": ORG_NAMES.get(b, ORG_NAMES.get(o)),
                                "note": ORG_NOTES.get(b) or ORG_NOTES.get(o)})
            elif lab in SPECIAL_SOURCES:
                nm, note = SPECIAL_SOURCES[lab]
                sources.append({"kind": "realm", "code": lab, "name": nm, "note": note})

        # stat bonuses actually granted on equip
        # Flat and scaled bonuses are DIFFERENT THINGS and must never be summed together.
        # IncrementStatRelative / BonusStatRelative scale off another stat; adding their
        # amount as flat points invents numbers that exist nowhere in the game
        # (Conqueror's Crown was shipping as a flat +25 ATT helm).
        bonus, scaled = {}, []
        for m in re.finditer(r"<ActivateOnEquip(?=[\s/>])([^>]*)>([^<]*)<", body):
            attrs, eff = m.group(1), m.group(2).strip()
            st = re.search(r'stat="(\w+)"', attrs)
            am = re.search(r'amount="(-?[\d.]+)"', attrs)
            rel_to = re.search(r'statRelativeTo="(\w+)"', attrs)
            if not (st and am):
                continue
            if eff == "IncrementStat":
                bonus[st.group(1)] = bonus.get(st.group(1), 0) + float(am.group(1))
            elif eff in ("IncrementStatRelative", "BonusStatRelative"):
                scaled.append({"stat": st.group(1), "amt": float(am.group(1)),
                               "of": rel_to.group(1) if rel_to else None, "kind": eff})

        # <EffectInfo> ships in BOTH attribute orders (1,858 description-first vs
        # 1,641 name-first). A positional regex here was dropping 53% of them.
        # trunk = the item's own fields, with every WRAPPER block removed so nothing
        # nested can leak up and be read as the item's own number.
        #
        # <Subattack> was the known one. INSTANCE #11 is <Ability name="...">: 132 of them
        # across 63 switch-form items (skulls, sigils, ST katanas). The old trunk ignored
        # it, and "mp" was read straight off the raw body, so 37 items reported one firing
        # mode's MP cost as the item's own and 24 listed another mode's tooltip lines as
        # their own. Sinister Syringes shipped 20 MP/s - that is the "Sharps" mode;
        # "Stitches" costs 10, and the item itself declares neither.
        #
        # guard() could never have caught this: it fires on a SHORTFALL, and a wrapper
        # leak over-consumes.
        trunk = body
        for _w in ("Subattack", "Ability"):
            trunk = re.sub("<%s(?=[\s/>]).*?</%s>" % (_w, _w), "", trunk, flags=re.S)

        # The firing modes themselves, kept as data rather than silently flattened.
        modes = []
        for _am, _ab in elems(body, "Ability"):
            modes.append({"name": _am.get("name") or ("Mode %d" % (len(modes) + 1)),
                          "mp": num(_ab, "MpCost"), "mps": num(_ab, "MpCostPerSecond")})

        def _own_or_agreed(field, key):
            """The item's own value; failing that, the modes' value only when they all
            agree. When they disagree there is no single number, and inventing one is
            exactly what shipped the wrong MP cost."""
            v = num(trunk, field)
            if v is not None or not modes:
                return v
            vals = set(m[key] for m in modes if m[key] is not None)
            return vals.pop() if len(vals) == 1 else None

        effects = []
        for ea, _ in elems(trunk, "EffectInfo"):
            enm, edesc = ea.get("name", ""), clean_desc(ea.get("description", ""))
            if enm or edesc:
                effects.append({"name": enm, "desc": edesc})
        # A switch-form item's per-mode tooltips belong to that mode, not to the item.
        for _am, _ab in elems(body, "Ability"):
            _mode = _am.get("name") or "Alternate mode"
            for ea, _ in elems(_ab, "EffectInfo"):
                enm, edesc = ea.get("name", ""), clean_desc(ea.get("description", ""))
                if enm or edesc:
                    effects.append({"name": ("%s - %s" % (_mode, enm)) if enm else _mode,
                                    "desc": edesc, "mode": _mode})

        # ---- where it drops -----------------------------------------------
        # Resolved in confidence order, first hit wins, each entry carrying the KIND
        # of evidence it came from. Steps 1-2 (the item's own ORG_/REALMWHITE labels)
        # already ran above; the rest fire only when the item said nothing itself.
        disp = tag(body, "DisplayId") or iid

        if not sources:
            # 3. the item states its own drop location, in English, in the client.
            d = next((e for e in effects if e["name"] == "Drop location"), None)
            if d:
                m = DROP_RE.search(d["desc"])
                if m:
                    sources.append({"kind": "boss", "name": m.group(2).strip().rstrip("."),
                                    "boss": m.group(1).strip(), "note": d["desc"]})

        if not sources:
            # 4. ST set membership. Join on the setType HEX, never the display name:
            #    the client ships the typo "Venertable Pyramid Set" and a name join
            #    silently loses every piece of it.
            nm = (set_by_type.get((oattr.get("setType") or "").lower())
                  or oattr.get("setName")
                  or piece_to_set.get((oattr.get("type") or "").lower()))
            if nm:
                sources.append({"kind": "set", "name": nm, "set": nm})

        if not sources:
            # 5. event / campaign label.
            ev = next((l for l in labels if l in EVENT_LABELS), None)
            if ev:
                sources.append({"kind": "event", "code": ev, "name": EVENT_LABELS[ev]})

        if not sources:
            # 6. the dungeon the forge makes you dismantle in. Often a LIST
            #    ("ORG_LH,ORG_CULT,ORG_VOID") - show every one, never pick one.
            codes = forge_src.get(iid) or []
            named = [ORG_NAMES.get(c) or ("ORG_" + c) for c in codes]
            if named:
                sources.append({"kind": "forge", "code": codes[0], "name": named[0],
                                "alts": named[1:] or None,
                                "note": "The forge requires dismantling here."})

        if not sources:
            # 7. community layer - RealmEye's untiered-items-by-dungeon page, captured
            #    once into data/. External knowledge, flagged as such, never blended
            #    into the client facts above.
            cd = community.get(norm_name(disp))
            if cd:
                sources.append({"kind": "community", "name": cd,
                                "note": "From RealmEye's Untiered Items by Dungeon page, "
                                        "captured once. Community knowledge, not game data."})

        if not sources and iid in derived:
            # 8. derived from the client's own files - a cross-reference, the item's own
            #    prose, its sprite-sheet neighbours. Weaker than a label the game states
            #    outright, so it is tagged `via: derived` and the UI says so on hover.
            dv = derived[iid]
            sources.append({"kind": dv["kind"], "name": dv["source"], "via": "derived",
                            "boss": dv.get("boss") or None,
                            "conf": dv["confidence"],
                            "note": METHOD_NOTE.get(dv["method"], dv["method"])})

        if not sources and "TIERED" in labels:
            # Tiered gear is not dungeon-specific - Tate's own rule: "i can find tiered
            # items in any dungeon, while UT/ST are dungeon/enemy specific". That is a real
            # answer, not a gap; filing 418 tiered items under "none" made the coverage
            # table read far worse than the data actually is.
            sources.append({"kind": "tiered", "name": "Many dungeons",
                            "note": "Tiered gear drops from enemies everywhere. Higher "
                                    "tiers are weighted toward harder content."})

        # Name the boss for any dungeon we know one for, so the Source column can show
        # the enemy as well as the door.
        for src in sources:
            if src.get("boss") or not src.get("name"):
                continue
            dl = drop_locs.get(norm_dungeon(src["name"].split(chr(8212))[0].strip()))
            if dl:
                src["boss"] = dl["boss"]

        # ---- combat -------------------------------------------------------
        # Weapons come in two shapes. Simple ones put MinDamage/MaxDamage/RateOfFire/
        # NumProjectiles at the top level. Complex ones declare several <Projectile id="N">
        # and a <Subattack projectileId="N"> per firing pattern, each with its own rate and
        # projectile count. A whole-body regex silently reads a sub-attack's numbers as the
        # item's own, which is how Ravenous Wand shipped a single-shot number.
        projectiles = {}
        # A <Projectile> may omit its id, in which case it is the Nth by position.
        # Matching only id-bearing ones made shiny variants read a different (stronger)
        # projectile than their base and report inflated DPS.
        # (?=[\s/>]) matters here too: <ProjectilePattern ...> occurs 15 times in equip.xml and
        # would otherwise match, inventing a projectile and running to the next
        # </Projectile>.
        for n_p, pm in enumerate(re.finditer(r"<Projectile(?=[\s/>])([^>]*)>(.*?)</Projectile>", body, re.S)):
            a, b2 = num(pm.group(2), "MinDamage"), num(pm.group(2), "MaxDamage")
            if a is None or b2 is None:
                continue
            pid = re.search(r'id="(\d+)"', pm.group(1))
            projectiles[pid.group(1) if pid else str(n_p)] = (a, b2)

        subattacks = []
        for sm in re.finditer(r'<Subattack\b([^>]*)>(.*?)</Subattack>', body, re.S):
            pid = re.search(r'projectileId="(\d+)"', sm.group(1))
            subattacks.append({
                "pid": pid.group(1) if pid else "0",
                "shots": num(sm.group(2), "NumProjectiles") or 1.0,
                "rof": num(sm.group(2), "RateOfFire"),
            })

        base_rof = num(trunk, "RateOfFire")

        if projectiles:
            strongest = max(projectiles.values(), key=lambda t: t[0] + t[1])
            mn, mx = strongest
        else:
            mn, mx = num(trunk, "MinDamage"), num(trunk, "MaxDamage")

        rof = base_rof
        shots = num(trunk, "NumProjectiles")
        rel = proc = None
        rel_assumed = False

        if subattacks:
            # Sum each firing pattern: average damage x its projectiles x its rate.
            total = 0.0
            for sa in subattacks:
                dmg = projectiles.get(sa["pid"]) or (mn, mx)
                if dmg[0] is None:
                    continue
                total += ((dmg[0] + dmg[1]) / 2.0) * sa["shots"] * (sa["rof"] if sa["rof"] else 1.0)
            value = total * (base_rof if base_rof else 1.0)
            shots = sum(sa["shots"] for sa in subattacks)
        elif mn is not None and mx is not None:
            if base_rof is None:
                rel_assumed = True
            value = ((mn + mx) / 2.0) * (base_rof if base_rof else 1.0) * (shots if shots else 1.0)
        else:
            value = None

        if value is not None:
            if slot in WEAPON_SLOTS:
                rel = value
            else:
                proc = value

        type_to_id[(oattr.get("type") or "").lower()] = iid
        coll_icon = oattr.get("collectionIcon")
        items.append({
            "id": iid,
            "name": tag(body, "DisplayId") or iid,
            "slot": slot,
            "slotName": SLOT_NAMES.get(slot, "Slot %d" % slot),
            "labels": labels,
            "tier": "ST" if "ST" in labels else ("UT" if "UT" in labels else
                    ("Tiered" if "TIERED" in labels else None)),
            # kept only as a raw game label - it is NOT a quality ranking, see CONTEXT.md
            "ptag": next((l.split("_", 1)[1] for l in labels if l.startswith("POWERTIER_")), None),
            "sources": sources,
            # scalar of sources[0]["kind"] - what the UI filters and sorts on
            "sk": sources[0]["kind"] if sources else "none",
            "soulbound": "<Soulbound" in body,
            "admin": ("<AdminOnly" in body) or None,
            "ci": coll_icon,
            # Curated, not derived - the client has no flag for this. Hidden by default.
            "gone": (gone[iid]["reason"] if iid in gone else None),
            "tradeable": "TRADEABLE" in labels,
            "shiny": "SHINY" in labels or iid.endswith(" Shiny"),
            "reskin": "RESKIN" in labels,
            # "Retro X" and "XOld" are legacy re-releases that share a display name with
            # the current item and are otherwise indistinguishable in a table.
            "legacy": bool(re.match(r"^(Retro |Legacy )", iid) or iid.endswith("Old")) or None,
            "desc": clean_desc(tag(body, "Description")),
            "feed": tag(body, "feedPower"),
            "bag": tag(body, "BagType"),
            "ench": ench_slots(body),
            "dust": ench_dust(body),
            "chance": ench_chance(body),
            "mp": _own_or_agreed("MpCost", "mp"),
            "dmg": [mn, mx] if mn is not None else None,
            "rof": rof, "shots": shots,
            "rel": round(rel, 1) if rel is not None else None,
            "proc": round(proc, 1) if proc is not None else None,
            "relAssumed": rel_assumed or None,
            "multi": len(subattacks) or None,
            "bonus": bonus or None, "scaled": scaled or None,
            "effects": effects or None,
            "pw": num(trunk, "PowerLevel"),
            "mps": _own_or_agreed("MpCostPerSecond", "mps"),
            "modes": modes or None,
        })

    # Two signals, both stated by the client, separate real gear from engine plumbing:
    #   <AdminOnly/>      7 dev-only objects
    #   no <BagType>    215 proc / sub-projectile carriers ("Shadows Proc",
    #                   "Onhit Quiver Projectile T6", "MotMG 2024 Bow Glory Projectiles")
    # Checked by hand: every no-BagType object is plumbing, and the four "Scorchium
    # Stone" procs sit beside the real 2MysticST1 which does carry BagType 8.
    # Do NOT filter on "looks like junk" - that plan would have deleted The Mistake,
    # a real 30-piece set.
    before = len(items)
    items = [i for i in items if not i["admin"] and i["bag"]]
    print("  dropped %d engine objects (AdminOnly, or no BagType)" % (before - len(items)))

    before = len(items)
    items = [i for i in items if not below_floor(i["labels"])]
    print("  dropped %d low-tier tiered items (weapons/armor under T%d, abilities/rings under T%d)"
          % (before - len(items), TIER_FLOOR["WEAPON"], TIER_FLOOR["ABILITY"]))
    for i in items:
        i.pop("admin", None)

    # collectionIcon groups items by the dungeon collection they appear in. 49 of the 50
    # groups that have three or more already-resolved members are UNANIMOUS about which
    # dungeon that is, which makes it a real resolver rather than a coincidence. An item
    # with no source of its own inherits the group's, but only when every resolved member
    # agrees and there are at least three of them.
    #
    # Found by an agent deriving The Heart of the Dragon: all 7 other items carrying
    # collectionIcon="142" have ORG_ENCORE, and forgeProperties.xml independently pairs
    # icon index 142 with ORG_ENCORE.
    by_icon = {}
    for i in items:
        if i.get("ci"):
            by_icon.setdefault(i["ci"], []).append(i)
    coll_hits = 0
    for ci, members in by_icon.items():
        agreed = {m["sources"][0]["name"] for m in members
                  if m["sk"] in ("dungeon", "boss") and m["sources"]}
        resolved = sum(1 for m in members if m["sk"] in ("dungeon", "boss"))
        if len(agreed) != 1 or resolved < 3:
            continue
        name = agreed.pop()
        for m in members:
            if m["sk"] != "none":
                continue
            m["sources"] = [{"kind": "dungeon", "name": name, "via": "collection",
                             "conf": "high",
                             "note": ("Every one of the %d items in this dungeon's collection "
                                      "that names a source names this one." % resolved)}]
            m["sk"] = "dungeon"
            coll_hits += 1
    print("  resolved by collection icon: %d" % coll_hits)
    for i in items:
        i.pop("ci", None)          # served its purpose; not worth shipping in the payload

    # 8. inheritance - the last resort. A Shiny or (SB) printing of an item drops
    #    exactly where the item does; nothing else may be inherited.
    by_norm = {}
    for i in items:
        if i["sk"] != "none":
            by_norm.setdefault(norm_name(i["name"]), i)
    inherited = 0
    for i in items:
        if i["sk"] != "none":
            continue
        base = by_norm.get(norm_name(i["name"]))
        if base is not None and base is not i and base["sources"]:
            i["sources"] = [dict(x, kind="inherit", of=base["name"]) for x in base["sources"]]
            i["sk"] = "inherit"
            inherited += 1
    print("  inherited a source from a base printing: %d" % inherited)

    # (SB) is the soulbound printing of an existing item, not a different item - all 133
    # have a non-SB twin. Merge onto the base row, but gate on a stat fingerprint:
    # Scorching Blast Spell (SB) really does hit 60-110 against the base's 50-90, and
    # collapsing that would be a lie.
    def fingerprint(i):
        return (i["slot"], tuple(i["dmg"] or ()), i["rof"], i["shots"], i["mp"],
                tuple(sorted((i["bonus"] or {}).items())))
    by_id = {i["id"]: i for i in items}
    merged, distinct, keep = 0, [], []
    for i in items:
        base = by_id.get(i["id"][:-4].strip()) if i["id"].endswith("(SB)") else None
        if base is not None and fingerprint(base) == fingerprint(i):
            base["sb"] = True
            merged += 1
            continue
        if i["id"].endswith("(SB)"):
            distinct.append(i["name"])
        keep.append(i)
    items = keep
    print("  (SB) merged onto their base row: %d   kept as genuinely different: %d %s"
          % (merged, len(distinct), distinct or ""))

    # shiny <-> base pairing, so a shiny can be shown beside its normal form
    ids = {i["id"] for i in items}
    by_name = {}
    for it in items:
        if not it["shiny"]:
            by_name.setdefault(it["name"], []).append(it["id"])
    pairs = 0
    for it in items:
        if not it["shiny"]:
            continue
        # Prefer the id join ("X Shiny" -> "X"); fall back to the display name only when
        # it resolves to exactly one non-shiny item, otherwise 4 quivers collapse onto one.
        base_id = None
        if it["id"].endswith(" Shiny") and it["id"][:-6] in ids:
            base_id = it["id"][:-6]
        else:
            cands = by_name.get(it["name"], [])
            if len(cands) == 1:
                base_id = cands[0]
        if base_id and base_id != it["id"]:
            it["baseOf"] = base_id
            pairs += 1
    shiny_of = {}
    for it in items:
        if it.get("baseOf"):
            shiny_of[it["baseOf"]] = it["id"]
    for it in items:
        s = shiny_of.get(it["id"])
        if s:
            it["shinyId"] = s

    items.sort(key=lambda i: (i["name"] or "").lower())
    print("  items: %d equippable  (%d shiny paired to a base form)" % (len(items), pairs))

    # ---- dungeons ------------------------------------------------------------
    # DungeonPortal objects are spread across ~20 files, not just portals.xml. Reading only
    # portals.xml silently drops every modern endgame dungeon - Lost Halls, Oryx's Sanctuary,
    # The Nest, Fungal Cavern, Cursed Library, Kogbold Steamworks, Moonlight Village...
    diffs = dungeon_difficulty()
    portals, seen_names = [], set()
    for fn in sorted(os.listdir(XML)):
        if not fn.endswith(".xml"):
            continue
        try:
            xml = read(fn)
        except SystemExit:
            continue
        if "<DungeonPortal" not in xml:
            continue
        for pid, _oa, body in objects(xml):
            if "<DungeonPortal" not in body:
                continue
            nm = tag(body, "DisplayId") or tag(body, "DungeonName") or pid
            if PORTAL_SKIP.search(pid) or PORTAL_SKIP.search(nm) or nm in seen_names:
                continue
            seen_names.add(nm)
            portals.append({
                "id": "portal:" + pid, "name": nm,
                "dungeon": tag(body, "DungeonName") or "",
                "diff": diffs.get(norm_dungeon(nm)),
                "file": fn,            # lets us attach that dungeon's boss sprite
            })
    portals.sort(key=lambda p: p["name"].lower())
    print("  dungeon portals: %d distinct (%d with a difficulty rating)"
          % (len(portals), sum(1 for p in portals if p["diff"] is not None)))

    # ---- enchantments --------------------------------------------------------
    enchants = []
    for m in re.finditer(r"<Enchantment\b[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</Enchantment>",
                         read("enchantments.xml"), re.S):
        eid, body = m.group(1), m.group(2)
        el = [x.strip() for x in (tag(body, "EnchantmentLabels") or "").split(",") if x.strip()]
        enchants.append({
            "id": eid, "name": tag(body, "DisplayId") or eid,
            "desc": clean_desc(tag(body, "Description")),
            "labels": el,
            "tier": next((l for l in el if l.startswith("TIER")), None),
            "compat": [x.strip() for x in (tag(body, "CompatibleWithItemLabels") or "").split(",") if x.strip()],
            "excl": [x.strip() for x in (tag(body, "IncompatibleWithEnchantmentLabels") or "").split(",") if x.strip()],
            # Needed to work out what may legally roll on a given item.
            "noItem": [x.strip() for x in (tag(body, "IncompatibleWithItemLabels") or "").split(",") if x.strip()],
            "noIds": [x.strip() for x in (tag(body, "IncompatibleWithItemIds") or "").split(",") if x.strip()],
            "weight": tag(body, "Weight"),
            "mut": ench_mutations(body),
            "mx": ench_multipliers(body, eid) or None,
        })
    # Enchantment LEVELS, not rarities. The client ships each rollable enchantment as
    # four objects - Attack_Defense_Tradeoff_1..4 - and the id suffix is exactly its
    # TIER label every single time (verified: 0 mismatches across all 1,016). So the
    # family is the id with that suffix removed, and "top" is the best roll of that
    # enchantment. 203 families of four, plus 204 single-level enchantments that are
    # their own top.
    fam_top = {}
    for e in enchants:
        m = re.match(r"^(.*)_([1-9]\d*)$", e["id"])
        lv = int(e["tier"][4:]) if (e["tier"] or "").startswith("TIER") else None
        if m and lv is not None:
            if int(m.group(2)) != lv:
                FAILURES.append("enchant %s: id says level %s, label says %d"
                                % (e["id"], m.group(2), lv))
            e["fam"], e["lv"] = m.group(1), lv
        else:
            e["fam"], e["lv"] = e["id"], 1
        fam_top[e["fam"]] = max(fam_top.get(e["fam"], 0), e["lv"])
    for e in enchants:
        if e["lv"] == fam_top[e["fam"]]:
            e["top"] = True
    print("  enchantment families: %d  (%d are the best roll of their kind)"
          % (len(fam_top), sum(1 for e in enchants if e.get("top"))))
    enchants.sort(key=lambda e: ((e["tier"] or "zz"), e["name"]))
    ench_xml = read("enchantments.xml")
    guard(ench_xml, "Enchantment", len(enchants), "enchantments.xml")
    guard(ench_xml, "ActivateOnEquip", sum(len(e["mut"]) for e in enchants), "enchant mutations")
    print("  enchantments: %d  (%d stat mutations)"
          % (len(enchants), sum(len(e["mut"]) for e in enchants)))

    # ---- coverage ------------------------------------------------------------
    # The ratchet. This project has shipped eight silent parse failures; a table of
    # what resolved, by kind, is the cheapest way to see the next one arrive.
    KIND_ORDER = ["dungeon", "boss", "set", "realm", "event", "forge", "community",
                  "tiered", "inherit", "none"]
    cov = Counter(i["sk"] for i in items)
    print("  source coverage (%d items):" % len(items))
    for k in KIND_ORDER:
        if cov.get(k):
            print("      %-10s %5d  (%.1f%%)" % (k, cov[k], 100.0 * cov[k] / len(items)))
    gap = [i for i in items if i["sk"] == "none" and i["tier"] in ("UT", "ST")]
    print("      UT/ST with no source at all: %d" % len(gap))
    if len(gap) > 219:
        FAILURES.append("UT/ST source gap regressed to %d (was 219 or better)" % len(gap))
    for nm in sorted(i["name"] for i in gap)[:25]:
        print("          %s" % nm)
    if len(gap) > 25:
        print("          ... and %d more" % (len(gap) - 25))

    unmapped = Counter(s.get("code") for it in items for s in it["sources"] if not s["name"])
    if unmapped:
        print("  unmapped source codes (UI shows the raw code):")
        for c, n in unmapped.most_common():
            print("      ORG_%-20s %d" % (c, n))

    # ---- sprites -------------------------------------------------------------
    # boss file name -> normalised dungeon name, so "lostHallsObjects.xml" finds "Lost Halls"
    boss_by_name = {}
    sprites, cells, bagcells = {}, {}, {}
    sidx_path = os.path.join(HERE, ".build", "sprite-index.json")
    if os.path.exists(sidx_path):
        with open(sidx_path, encoding="utf-8") as f:
            sidx = json.load(f)
        cells = sidx["index"]  # noqa: F841 - also used by the source-icon pass below
        for key, cell in cells.items():
            if not key.startswith("boss:"):
                continue
            stem = key[5:]
            for suffix in ("Objects.xml", "Object.xml", ".xml"):
                if stem.endswith(suffix):
                    stem = stem[: -len(suffix)]
                    break
            boss_by_name[norm_dungeon(stem)] = cell
        for it in items:
            n = cells.get(it["id"])
            if n is not None:
                it["sp"] = n
        # Each class's own character art, so the rail can show the class instead of
        # spelling its name in a list.
        for c in classes:
            n = cells.get("class:" + c["name"])
            if n is not None:
                c["sp"] = n
            # slot tab icons, from that class's own starting equipment
            gear = c.pop("startGear", []) or []
            sp = [cells.get(type_to_id.get((h or "").lower(), "")) for h in gear]
            # Classes start with no ring (<Equipment> ends in -1), and the client ships no
            # empty-slot placeholder art. Fall back to the lowest-tier real item of that
            # slot, so every tab still shows in-game art for the right kind of thing.
            while len(sp) < 4:
                sp.append(None)
            for k, slot in enumerate(c["slots"]):
                if sp[k] is None:
                    pick = sorted((i for i in items if i["slot"] == slot and "sp" in i),
                                  key=lambda i: (tier_num(i["labels"]) or 99, i["name"]))
                    if pick:
                        sp[k] = pick[0]["sp"]
            c["slotSp"] = sp
        for p in portals:
            n = cells.get(p["id"])
            if n is not None:
                p["sp"] = n
            bn = cells.get("boss:" + p.get("file", ""))
            if bn is None:
                bn = boss_by_name.get(norm_dungeon(p["name"]))
            if bn is not None:
                p["boss"] = bn
        bagcells.update({k.split(":", 1)[1]: v for k, v in cells.items() if k.startswith("bag:")})
        for e in enchants:
            n = cells.get("ench:" + e["id"])
            if n is not None:
                e["sp"] = n
        # Art for the navigation rail, so the menu uses the game's own imagery rather than
        # words. The realm portal is the grey/black door players know; the rest are picked
        # from what the atlas already holds.
        beast = next((v for k, v in cells.items() if k.startswith("boss:undeadLair")), None)
        t4 = next((e for e in enchants if e.get("tier") == "TIER4" and e.get("sp") is not None), None)
        # Stat icon + colour, both from the game's own potion art. The client states
        # which bottle raises which stat, so this is a join and not a guess.
        statcells = {k.split(":", 1)[1]: v for k, v in cells.items() if k.startswith("stat:")}
        sprites = {"cell": sidx["cell"], "cols": sidx["cols"], "bags": bagcells,
                   "stats": statcells, "statColors": sidx.get("statColors") or {},
                   "ui": {"realm": cells.get("realm:Realm Portal"),
                          "ench": (t4 or {}).get("sp"),
                          "beast": beast,
                          "bag": bagcells.get("6"),
                          "pet": cells.get("egg:Common Feline Egg")}}
        print("  sprites: %d items, %d portals"
              % (sum(1 for i in items if "sp" in i), sum(1 for p in portals if "sp" in p)))

    # Source -> dungeon door. Lets the Source column render the actual portal sprite
    # with the dungeon name (and difficulty) on hover, instead of a wall of text.
    portal_by_norm = {}
    for p in portals:
        portal_by_norm.setdefault(norm_dungeon(p["name"]), p)
        if p.get("dungeon"):
            portal_by_norm.setdefault(norm_dungeon(p["dungeon"]), p)

    src_bags = {}
    for it in items:
        for src in it["sources"]:
            k = src["name"] or ("ORG_" + src.get("code", "?"))
            src_bags.setdefault(k, Counter())[it.get("bag")] += 1

    source_icons, matched = {}, 0
    seen_src = set()
    for it in items:
        for src in it["sources"]:
            key = src["name"] or ("ORG_" + src.get("code", "?"))
            if key in seen_src:
                continue
            seen_src.add(key)
            entry = {"name": key, "kind": src.get("kind", "dungeon")}
            if src["name"]:
                lookup = src["name"].split("—")[0].strip()   # "X - secret boss" -> "X"
                pt = portal_by_norm.get(norm_dungeon(lookup))
                if pt:
                    if "sp" in pt:
                        entry["sp"] = pt["sp"]
                    if pt.get("boss") is not None:
                        entry["boss"] = pt["boss"]
                    if pt.get("diff") is not None:
                        entry["diff"] = pt["diff"]
                    matched += 1
            if "sp" not in entry and entry["kind"] == "set":
                # An ST set has no door. Wearing the full set transforms your character
                # into a new outfit, so THAT is the set - use its skin.
                sk_id, how = match_skin(key, set_skins, set_skin_tokens, class_names)
                cell = cells.get("setskin:" + sk_id) if sk_id else None
                if cell is not None:
                    entry["sp"] = cell
                    entry["skin"] = sk_id
                    if how == "words":
                        SKIN_WORD_MATCHES.append("%s -> %s" % (key, sk_id))
            if "sp" not in entry and entry["kind"] == "set":
                # No skin: an "Alien Core" or a "Path of ..." is a stat bundle, not an
                # outfit. Fall back to the set's own weapon piece (pieces are listed
                # slot-first, so pieces[0] is the weapon).
                for pt_hex in (eqsets.get(key, {}).get("pieces") or []):
                    cell = cells.get(type_to_id.get(pt_hex.lower(), ""))
                    if cell is not None:
                        entry["sp"] = cell
                        break
            if "sp" not in entry and entry["kind"] == "realm" and "realm white" in key.lower():
                # The Realm portal - the globe players actually use to recognise a realm
                # white. Better than a loot bag, which says rarity but not where.
                cell = cells.get("realm:Realm Portal")
                if cell is not None:
                    entry["sp"] = cell
                    entry["globe"] = True
            if "sp" not in entry and ("(event)" in key.lower() or entry["kind"] == "event"):
                # Some events arrive as an ORG_ code rather than an event label
                # (ORG_ORYXMAS -> "Oryxmas (event)"), so match the name too or they render
                # as bare text beside rows that all have art. Match "(event)" exactly, NOT
                # the bare word: "Event / realm white" is a white BAG, not a chest.
                # Events pay out from a chest, and the client ships the chest art.
                cell = chest_cell(key, cells)
                if cell is not None:
                    entry["sp"] = cell
                    entry["chest"] = True
            if "sp" not in entry:
                # Last resort, and only when the data is unambiguous: if effectively
                # everything from this source lands in the same loot bag, show that bag.
                # 100 of the 101 realm whites drop in bag 6, so "Event / realm white"
                # correctly becomes the white bag. Tiered gear spans every bag, so
                # "Many dungeons" correctly stays iconless rather than being given a lie.
                bags = src_bags.get(key)
                if bags and sum(bags.values()) >= 3:
                    # >= 3 members, or "80% of one item" is trivially true and a lone item's
                    # own bag gets promoted to look like evidence about the source.
                    top, n = bags.most_common(1)[0]
                    if top and n >= 0.8 * sum(bags.values()):
                        cell = bagcells.get(top)
                        if cell is not None:
                            entry["sp"] = cell
                            entry["bag"] = top
            if src.get("note"):
                entry["note"] = src["note"]
            source_icons[key] = entry
    if SKIN_WORD_MATCHES:
        print("  set skins matched by words rather than an exact name (%d) - eyeball these:"
              % len(SKIN_WORD_MATCHES))
        for r in sorted(SKIN_WORD_MATCHES):
            print("      %s" % r)
    print("  source icons: %d of %d sources matched to a dungeon door"
          % (matched, len(source_icons)))

    # ---- combination maths (asked for; also just a fun number) ---------------
    from math import comb
    by_slot = {}
    for it in items:
        if it.get("legacy") or it["shiny"]:
            continue
        by_slot.setdefault(it["slot"], []).append(it)
    combos = {}
    total_kits = 0
    for c in classes:
        counts = [len(by_slot.get(sl, [])) for sl in c["slots"]]
        n = 1
        for x in counts:
            n *= max(x, 1)
        combos[c["name"]] = {"perSlot": counts, "kits": n}
        total_kits += n

    # Enchant space: for a 4-slot item, choose 4 distinct enchantments from the pool
    # legal on it. Averaged over every item that can roll slots.
    ench_pool = []
    for it in items:
        slots = it.get("ench") or 0
        if slots <= 0:
            continue
        L = set(it["labels"])
        legal = 0
        for e in enchants:
            # CompatibleWithItemLabels is AND: the item must carry EVERY token. Reading
            # it as "shares any label" made PATH_OF_THE_MAGUS_STAFF legal on 1,473 items
            # instead of the single item it is written for, and inflated this count.
            if "ROLLABLE" not in e["labels"]:
                continue
            if e["compat"] and not set(e["compat"]).issubset(L):
                continue
            if set(e["noItem"]) & L:          # IncompatibleWithItemLabels is OR
                continue
            if it["id"] in e["noIds"]:
                continue
            legal += 1
        ench_pool.append((slots, legal))
    avg_legal = sum(l for _, l in ench_pool) // max(1, len(ench_pool))
    four_slot = comb(avg_legal, 4) if avg_legal >= 4 else 0
    combos["_meta"] = {
        "totalKits": total_kits,
        "itemsWithSlots": len(ench_pool),
        "avgLegalEnchants": avg_legal,
        "fourSlotCombosPerItem": four_slot,
    }
    print("  kit combinations: %s across %d classes | avg %d legal enchants per item, "
          "%s ways to fill 4 slots" % (f"{total_kits:,}", len(classes), avg_legal, f"{four_slot:,}"))

    # ---- pets ----------------------------------------------------------------
    # Endpoints and feed power only. See the module comment above load_pet_abilities.
    pet_abilities = load_pet_abilities()
    pet_food = load_pet_food(cells, gone)
    feed_ladders = load_feed_ladders()
    pet_yard = load_pet_yard()
    pet_levels = load_pet_levels()
    print("  pet level table: %s" % ("none - data/pet-levels.json is empty or unsourced, "
          "so the level calculator stays hidden" if not pet_levels
          else "%d rows from %s" % (len(pet_levels["feedToLevel"]), pet_levels["source"])))
    print("  pets: %d abilities, %d feedable food/eggs, %d feed ladders"
          % (len(pet_abilities), len(pet_food), len(feed_ladders)))
    scaling = sum(1 for ab in pet_abilities for pp in ab.get("params", []) if "curve" in pp)
    print("  pet ability parameters that scale with level: %d - endpoints only, the "
          "curve functions are named in pets.xml and defined nowhere" % scaling)

    data = {
        # Not a game version string - nothing in the extracted assets states one.
        # This is provable: when the assets on disk were written.
        "built": __import__("datetime").datetime.now().strftime("%b %d %H:%M"),
        "assetsBuilt": __import__("datetime").datetime.fromtimestamp(
            os.path.getmtime(os.path.join(XML, "equip.xml"))).strftime("%Y-%m-%d"),
        # Read from tauri.conf.json rather than hard-coded, so Settings cannot drift
        # from what the installer actually says.
        "appVersion": (json.load(open(os.path.join(HERE, "src-tauri", "tauri.conf.json"),
                                     encoding="utf-8")).get("version")
                       if os.path.exists(os.path.join(HERE, "src-tauri", "tauri.conf.json"))
                       else None),
        "biomeBands": biome_bands,
        # Source name -> biome, for the "click a place, see its mobs" jump. Only exact
        # name matches: the infographic has no dungeons in it, so anything else would be
        # a guess about which biome a dungeon spawns in.
        "biomeOf": {k: k for k in biome_bands
                    if k in {(s["name"] or "") for it in items for s in it["sources"]}},
        "sprites": sprites, "classes": classes, "items": items,
        "portals": portals, "enchants": enchants, "slotNames": SLOT_NAMES,
        "sourceIcons": source_icons, "combos": combos,
        "stats": STATS,
        "pets": {"abilities": pet_abilities, "food": pet_food,
                 "levels": pet_levels,
                 "ladders": feed_ladders, "yard": pet_yard},
        "counts": {"items": len(items), "enchants": len(enchants),
                   "classes": len(classes), "portals": len(portals),
                   "petAbilities": len(pet_abilities), "petFood": len(pet_food)},
    }
    if FAILURES:
        print("")
        print("  !! %d PARSE FAILURE(S) - data is incomplete:" % len(FAILURES))
        for f_ in FAILURES:
            print("     - %s" % f_)
        print("")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)
    print("wrote %s (%.1f MB)" % (OUT, os.path.getsize(OUT) / 1048576.0))

    # src/index.html is the single canonical template. Vite builds the app bundle from it
    # too, so there is exactly one file to edit - a second copy at roadmap-template.html
    # would drift the moment either build touched it.
    tpl = os.path.join(HERE, "src", "index.html")
    if not os.path.exists(tpl):
        print("no roadmap-template.html - skipped html build")
        return
    with open(tpl, encoding="utf-8") as f:
        html = f.read()
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("__ROTMG_DATA__", payload)

    atlas = os.path.join(HERE, ".build", "sprite-atlas.png")
    if os.path.exists(atlas):
        with open(atlas, "rb") as f:
            html = html.replace("__SPRITE_ATLAS__",
                                "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii"))
    else:
        html = html.replace("__SPRITE_ATLAS__", "")

    best = os.path.join(HERE, "assets", "bestiary.jpg")
    if os.path.exists(best):
        with open(best, "rb") as f:
            html = html.replace("__BESTIARY__",
                                "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii"))
    else:
        html = html.replace("__BESTIARY__", "")

    out_html = os.path.join(HERE, "roadmap.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote %s (%.1f MB) - single file, open it anywhere"
          % (out_html, os.path.getsize(out_html) / 1048576.0))


if __name__ == "__main__":
    main()
