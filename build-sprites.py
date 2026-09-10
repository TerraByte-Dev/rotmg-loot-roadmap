#!/usr/bin/env python3
"""
Crop every equippable item's sprite out of the client's atlases and pack them
into one small PNG for the roadmap.

Pipeline (run in this order after a game patch / asset re-extract):

    javac -cp <extractor>/Tomato-*.jar -d .build DumpSprites.java
    java  -cp "<extractor>/Tomato-*.jar;.build" DumpSprites \
          <your extracted assets>/flatbuffer/spritesheetf .build/sprites.tsv
    python build-sprites.py
    python build-data.py

Writes:
    .build/sprite-atlas.png   packed grid, 16x16 cells
    .build/sprite-index.json  object id -> cell number
"""

import csv
import io
import json
import os
import re
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required:  pip install pillow")

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
SPRITES = os.path.join(ASSETS, "sprites")
BUILD = os.path.join(HERE, ".build")
TSV = os.path.join(BUILD, "sprites.tsv")

CELL = 16          # every sprite is normalised into a 16x16 cell
COLS = 48          # atlas width in cells

# Equipment art lives in mapObjects; character art - every enemy, so every boss - lives in
# characters.png. The client says which via atlasId: 1/4 for static art, 2 for animated.
# Try the likely atlas first, then the other, and take the first with real pixels.
ATLAS_ORDER = ["mapObjects.png", "characters.png"]
ATLAS_BY_KIND = {"s": ["mapObjects.png", "characters.png"],
                 "a": ["characters.png", "mapObjects.png"]}

FAILURES = []


# ---------------------------------------------------------------------------
# Reading an object's OWN sprite
#
# This is the most damaging thing this file got wrong. A <Texture> search over the
# whole object body also matches art nested inside <AltTexture> (a reskin),
# <Animation><Frame> (a walk cycle), <Portrait> and <RandomTexture>. Bosses draw from
# <AnimatedTexture>, which the old regex refused outright, so it fell through to
# whichever nested tag it could find - almost always scenery from the *Objects* sheet
# instead of the boss on the *Chars* sheet.
#
# The damage: 39 of 56 dungeon bosses had the wrong sprite. Oryx the Mad God 3 rendered
# a tile of his own arena. 18 more resolved to File "invisible", which is a real 8x8
# rect of opaque pixels in the dump - so the blank-pixel guard below waved them straight
# through and they all shipped the same garbage tile, indistinguishable from real art.
# ---------------------------------------------------------------------------

NESTED_ART = ("AltTexture", "Animation", "Portrait", "RandomTexture", "Mask")


def own_art(body):
    """(sheet, index) for the object's own sprite, or None.

    Strips the wrapper elements first so nothing nested can be mistaken for the object's
    art, then prefers <Texture>, falling back to <AnimatedTexture> - which is how every
    dungeon boss is actually drawn.
    """
    trunk = body
    for w in NESTED_ART:
        trunk = re.sub("<%s(?=[\\s/>]).*?</%s>" % (w, w), "", trunk, flags=re.S)
    for tag_name in ("Texture", "AnimatedTexture"):
        # [^<]* rather than \s* between the children: a couple of objects put a comment
        # or stray text there, and Ring of Cubed Wisdom Shiny was lost to it.
        m = re.search(
            "<%s(?=[\\s/>])[^>]*>[^<]*<File>([^<]+)</File>[^<]*<Index>([^<]+)</Index>"
            % tag_name, trunk, re.S)
        if not m:
            continue
        sheet = m.group(1).strip()
        if sheet == "invisible":
            continue        # a sentinel, not art - and it defeats the blank guard
        raw = m.group(2).strip()
        return (sheet, int(raw, 16) if raw.lower().startswith("0x") else int(raw))
    return None


def objects(xml):
    """(id, body) for every <Object>. Mirrors build-data.py: the lookahead stops the
    root <Objects> and <ObjectId> from matching."""
    return re.findall(r"<Object(?=[\s/>])[^>]*id=\"([^\"]+)\"[^>]*>(.*?)</Object>", xml, re.S)


def guard(seen, got, label):
    """What exists vs what we extracted. build-data.py has had this for a while and this
    file did not - which is how 39 wrong boss sprites sat here unnoticed."""
    if seen and got < seen:
        FAILURES.append("%s: %d present, %d extracted (%.0f%%)"
                        % (label, seen, got, 100.0 * got / seen))


def each_xml():
    for fn in sorted(os.listdir(XML)):
        if not fn.endswith(".xml"):
            continue
        with io.open(os.path.join(XML, fn), encoding="utf-8", errors="ignore") as f:
            yield fn, f.read()


def load_index():
    """(sheet, index) -> (x, y, w, h, kind).

    The dump now carries both collections. Static art wins outright where it exists; for
    animated art we take the idle, front-facing frame - direction 0, action 0, set 0 -
    which is the frame a UI wants. Without the animated half no *Chars* sheet exists in
    the dump at all, and no dungeon boss can resolve to its real art.
    """
    if not os.path.exists(TSV):
        sys.exit("missing %s - run the DumpSprites step first (see this file's docstring)" % TSV)
    idx = {}
    with io.open(TSV, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter="\t"):
            kind = row.get("kind", "s")
            key = (row["sheet"], int(row["index"]))
            if kind == "a":
                if (int(row["direction"]), int(row["action"]), int(row["set"])) != (0, 0, 0):
                    continue
                if key in idx:
                    continue          # an existing static, or the first idle frame
            elif key in idx and idx[key][4] == "s":
                continue
            idx[key] = (int(row["x"]), int(row["y"]), int(row["w"]), int(row["h"]), kind)
    return idx


def item_textures():
    """id -> (sheet, index) for every equippable (non-consumable) item."""
    with io.open(os.path.join(XML, "equip.xml"), encoding="utf-8", errors="ignore") as f:
        eq = f.read()
    out, seen = {}, 0
    for iid, body in objects(eq):
        slot = re.search(r"<SlotType>(\d+)</SlotType>", body)
        if not slot or int(slot.group(1)) == 10:
            continue
        labels = re.search(r"<Labels[^>]*>([^<]*)</Labels>", body)
        if not labels or "EQUIPMENT" not in labels.group(1):
            continue
        seen += 1
        art = own_art(body)
        if art:
            out[iid] = art
    guard(seen, len(out), "equippable items")
    return out


def portal_textures():
    """Dungeon-door sprites. DungeonPortal objects live across ~20 files, not just
    portals.xml - reading only that one misses every modern endgame dungeon."""
    out, seen = {}, 0
    for fn, xml in each_xml():
        if "<DungeonPortal" not in xml:
            continue
        for pid, body in objects(xml):
            if "<DungeonPortal" not in body:
                continue
            seen += 1
            art = own_art(body)
            if art:
                out.setdefault("portal:" + pid, art)
    guard(seen, len(out), "dungeon portals")
    return out


def realm_textures():
    """The Realm portal itself - the globe. It is <Class>Portal</Class> with
    <IntergamePortal/>, NOT a <DungeonPortal>, so the dungeon-door extractor never saw
    it. Players use this glyph to recognise a realm white, which is what it is for here."""
    with io.open(os.path.join(XML, "portals.xml"), encoding="utf-8", errors="ignore") as f:
        px = f.read()
    out = {}
    for pid, body in objects(px):
        if pid not in ("Realm Portal", "Glowing Realm Portal"):
            continue
        art = own_art(body)
        if art:
            out["realm:" + pid] = art
    return out


def bag_textures():
    """BagType N is drawn by the object literally named "Loot Bag N" in containers.xml.
    These are the loot-rarity bags players actually recognise on the ground."""
    with io.open(os.path.join(XML, "containers.xml"), encoding="utf-8", errors="ignore") as f:
        co = f.read()
    out = {}
    for cid, body in objects(co):
        m = re.match(r"^Loot Bag (\d+)$", cid)
        if not m:
            continue
        art = own_art(body)
        if art:
            out["bag:" + m.group(1)] = art
    guard(10, len(out), "loot bags")
    return out


def enchant_textures():
    """Every one of the 1016 enchantments ships an icon - though only ~83 distinct ones.
    The packer deduplicates by (sheet, index), so they cost 83 cells, not 1016."""
    with io.open(os.path.join(XML, "enchantments.xml"), encoding="utf-8", errors="ignore") as f:
        en = f.read()
    out, seen = {}, 0
    for m in re.finditer(r"<Enchantment(?=[\s/>])[^>]*id=\"([^\"]*)\"[^>]*>(.*?)</Enchantment>",
                         en, re.S):
        seen += 1
        art = own_art(m.group(2))
        if art:
            out["ench:" + m.group(1)] = art
    guard(seen, len(out), "enchantments")
    return out


def skin_textures():
    """The character skin a full ST set transforms you into.

    The client marks these itself - <UnlockSpecial>Set Skin</UnlockSpecial>, 86 of them in
    skins.xml, drawn from playerskins16 via <AnimatedTexture>. Wearing a complete ST set
    changes your outfit, so the outfit is what the set should be pictured by. (Using the
    set's weapon piece instead made every set icon look like a random sword.)
    """
    with io.open(os.path.join(XML, "skins.xml"), encoding="utf-8", errors="ignore") as f:
        sk = f.read()
    out, seen = {}, 0
    for sid, body in objects(sk):
        if "Set Skin" not in body:
            continue
        seen += 1
        art = own_art(body)
        if art:
            out["setskin:" + sid] = art
    guard(seen, len(out), "ST set skins")
    return out


def class_textures():
    """Each of the 19 classes' own character art.

    players.xml gives every class an <AnimatedTexture> on the "players" sheet - Rogue is
    index 0, Archer 1, and so on. These are 8x8 sprites, so they upscale to the 16px cell
    and then again to whatever the UI asks for; image-rendering:pixelated keeps them
    crisp. This is the class as the game draws it, not an icon anyone invented.
    """
    with io.open(os.path.join(XML, "players.xml"), encoding="utf-8", errors="ignore") as f:
        pl = f.read()
    out, seen = {}, 0
    for cid, body in objects(pl):
        if "<Player" not in body:
            continue
        seen += 1
        art = own_art(body)
        if art:
            out["class:" + cid] = art
    guard(seen, len(out), "class art")
    return out


def chest_textures():
    """Loot chests. The client labels them itself - <Labels>CHEST</Labels> - so there is
    no name-guessing here. Covers the event chests (Event Chest MotMG, Event Chest O1,
    Halloween Haunted Event Chest, Frozen Chest) plus the per-set Selection Chests."""
    out, seen = {}, 0
    for fn, xml in each_xml():
        if "CHEST" not in xml:
            continue
        for cid, body in objects(xml):
            lab = re.search(r"<Labels[^>]*>([^<]*)</Labels>", body)
            if not lab or "CHEST" not in [x.strip() for x in lab.group(1).split(",")]:
                continue
            seen += 1
            art = own_art(body)
            if art:
                out.setdefault("chest:" + cid, art)
    guard(seen, len(out), "chests")
    return out


def boss_textures():
    """<Quest> on an <Enemy> marks a boss (Oryx 3, LH Void Entity, Septavius...).
    Keyed by the file it lives in, so a dungeon can show its own boss.

    Highest max-HP wins the file. That is a heuristic and not always the boss a player
    would name - but it now ranks candidates that all have their OWN art, rather than
    whichever object happened to contain a matching nested <Texture>.
    """
    out, files_with_bosses = {}, 0
    for fn, xml in each_xml():
        if "<Quest" not in xml:
            continue
        best, any_candidate = None, False
        for oid, body in objects(xml):
            # "<Enemy" as a substring also matches <EnemyOccupySquare>.
            if "<Quest" not in body or not re.search(r"<Enemy\s*/?>", body):
                continue
            any_candidate = True
            hp = re.search(r"<MaxHitPoints[^>]*>(\d+)</MaxHitPoints>", body)
            hp = int(hp.group(1)) if hp else 0
            art = own_art(body)
            if not art or hp <= 0:
                continue
            if best is None or hp > best[0]:
                best = (hp, oid, art)
        if any_candidate:
            files_with_bosses += 1
        if best:
            out["boss:" + fn] = best[2]
    guard(files_with_bosses, len(out), "dungeon bosses (one per file with a quest enemy)")
    return out


def main():
    os.makedirs(BUILD, exist_ok=True)
    idx = load_index()
    tex = item_textures()
    print("equippable items with a texture: %d" % len(tex))
    for label, fn in (("dungeon portals", portal_textures), ("loot bags", bag_textures),
                      ("enchantment icons", enchant_textures),
                      ("dungeon bosses", boss_textures),
                      ("ST set skins", skin_textures),
                      ("class art", class_textures),
                      ("realm globe", realm_textures),
                      ("loot / event chests", chest_textures)):
        got = fn()
        tex.update(got)
        print("%s: %d" % (label, len(got)))

    atlases = {}
    for name in ATLAS_ORDER:
        p = os.path.join(SPRITES, name)
        if os.path.exists(p):
            atlases[name] = Image.open(p).convert("RGBA")
    if not atlases:
        sys.exit("no atlases found in %s" % SPRITES)

    # Deduplicate by (sheet, index), not by id. All 1,016 enchantments share ~83 icons
    # and every Shiny reuses its base art, so one cell per id made the atlas several
    # times larger than the art it actually holds.
    cell_of, missing, blank = {}, 0, 0
    for iid, key in sorted(tex.items()):
        if key in cell_of:
            continue
        rect = idx.get(key)
        if not rect:
            missing += 1
            continue
        x, y, w, h, kind = rect
        best = None
        for name in ATLAS_BY_KIND.get(kind, ATLAS_ORDER):
            im = atlases.get(name)
            if im is None or x + w > im.size[0] or y + h > im.size[1]:
                continue
            c = im.crop((x, y, x + w, y + h))
            if any(p[3] > 0 for p in c.getdata()):     # first atlas with real pixels wins
                best = c
                break
        if best is None:
            blank += 1
            continue
        if best.size != (CELL, CELL):                  # nearest-neighbour keeps pixel art crisp
            best = best.resize((CELL, CELL), Image.NEAREST)
        cell_of[key] = best

    order = list(cell_of)
    cell_no = {key: n for n, key in enumerate(order)}
    index = {iid: cell_no[key] for iid, key in tex.items() if key in cell_no}

    print("  ids: %d   distinct sprites packed: %d   no rect: %d   empty: %d"
          % (len(index), len(order), missing, blank))

    rows = (len(order) + COLS - 1) // COLS
    sheet = Image.new("RGBA", (COLS * CELL, rows * CELL), (0, 0, 0, 0))
    for n, key in enumerate(order):
        sheet.paste(cell_of[key], ((n % COLS) * CELL, (n // COLS) * CELL))

    out_png = os.path.join(BUILD, "sprite-atlas.png")
    sheet.save(out_png, optimize=True)
    with io.open(os.path.join(BUILD, "sprite-index.json"), "w", encoding="utf-8") as f:
        json.dump({"cell": CELL, "cols": COLS, "index": index}, f, separators=(",", ":"))

    print("wrote %s  %dx%d  (%.0f KB, %d cells serving %d ids)"
          % (out_png, sheet.size[0], sheet.size[1], os.path.getsize(out_png) / 1024.0,
             len(order), len(index)))

    if FAILURES:
        print("")
        print("  !! %d EXTRACTION SHORTFALL(S):" % len(FAILURES))
        for f_ in FAILURES:
            print("     - %s" % f_)


if __name__ == "__main__":
    main()
