# RotMG Loot Roadmap

Pick your class, see every item you can actually farm for it, and **where to go and get it** —
the dungeon's own door, the enemy that drops it, and what you want enchanted on it.

Built from Realm of the Mad God's own client files. Not a scraper, not a wiki mirror: the
item database, the sprites, the dungeon doors, the boss art and the enchantments all come out
of the game's XML and sprite sheets, so it is versioned to the client you actually have.

## Install

Grab the latest **Setup.exe** from [Releases](../../releases/latest) and run it.

It installs to your user folder, so there is **no UAC prompt**. It is not code-signed, so the
first launch shows **"Windows protected your PC"** — click **More info → Run anyway**. That
happens exactly once; in-app updates after that never show it again. Every release lists the
SHA-256 of both files if you want to check the download first.

There is also a portable ZIP. Run `Unblock-File .\RotMG-Loot-Roadmap_*_x64_portable.zip`
**before** extracting it, or Windows copies its download mark onto the .exe inside and you get
the same prompt anyway. The portable build does not self-update.

Prefer no install at all? `roadmap.html` on the release is the whole thing in one file — open
it in any browser, or drop it in a Discord DM.

## What's in it

- **Items** — every equippable item for your class, by slot, with a comparable DPS number,
  its loot bag, and where it drops.
- **Track** — what you're hunting, grouped by *place*, with the boss that drops it and a
  per-item enchant plan.
- **Kit** — build a four-slot loadout and see the stat totals, base and maxed.
- **Enchants** — all 1,016, filterable to the ones that can legally roll on your kit.
- **Dungeons** — every portal in the client, with the difficulty rating the game itself
  stores on its dungeon keys.
- **Bestiary** — the community realm infographic, with a jump-to-biome picker.
- **Pets** — what every pet ability actually does at each end of its scale, and what
  everything in the game is worth as pet food.

## Where the data comes from, and how much to trust it

Every drop source is tagged with the *kind* of evidence behind it, and the app says so on
hover. In descending order of confidence:

| Kind | Signal |
|---|---|
| `dungeon` | the item's own `ORG_*` label in `equip.xml` |
| `boss` | the client's own `<EffectInfo name="Drop location">` sentence |
| `set` | ST set membership, joined on the set's type hex |
| `event` | an event/campaign label the client carries |
| `forge` | what the forge requires you to dismantle |
| `derived` | traced out of the client files by cross-reference — see `data/derived-sources.json`, which carries the exact quoted evidence for each |
| `community` | RealmEye's *Untiered Items by Dungeon* page, captured once into `data/` |
| `tiered` | tiered gear, which drops anywhere by design |

The Pets page is the sharpest example of the rule. The client states the **endpoints** of
every pet ability — a maxed Heal tops out at 90, a maxed Magic Heal at 45 — and names the
curve between them, but defines that curve nowhere and never says what level range the two
ends span. Nothing anywhere relates feed power to a level. So the app shows both ends and
draws nothing in between, and there is no feed-to-level calculator unless you put a
community table into `data/pet-levels.json` — which the app then labels as not-from-the-files
wherever it uses it.

**81 UT/ST items still say "not recorded".** That is deliberate. Nothing in the client, the
captured page or the derived layer says where they drop, and a wrong dungeon costs somebody an
evening of farming.

`data/unobtainable.json` and `data/pet-levels.json` are the two files here that are
**curated by hand**: the client has no
"limited" or "retired" flag of any kind, so items that can no longer be obtained are listed
manually and hidden by default. There is a toggle to show them.

## Building it yourself

You need the extracted client assets — 246 XML files, the sprite atlases and `spritesheetf` —
plus a JDK, Python 3 with Pillow, and Node 22+.

```powershell
# point the build at your extracted assets (or set ROTMG_ASSETS)
"D:\path\to\assets" | Set-Content assets-path.txt

.\build.ps1        # sprite index -> atlas -> rotmg-data.json -> roadmap.html
npm install
npm run build      # standalone roadmap.html + the app bundle
npm run app:build  # the Windows installer
```

The build refuses to continue past a failed step, so a green **Done.** means the artifact on
disk is the one that was just built.

## Credits

The bestiary infographic is community work by **GHZD** and is included with credit; it is not
game data and is not cross-checked against the client. Realm of the Mad God is Deca Games'.
This project reads files the game already put on your disk and talks to nothing.
