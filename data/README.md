# `data/` — the files a human has to write

Everything else in this project is read out of the game client. These are not, and
each one exists because the client genuinely does not contain what it holds. They are all
optional: the build runs without any of them and simply says less.

| File | What it supplies | Status |
|---|---|---|
| `realmeye-untiered-by-dungeon.tsv` | UT item → dungeon | captured, 521 rows |
| `realmeye-set-tier-items.tsv` | **ST item → dungeon** | **empty — see below** |
| `captures/` | anything saved from RealmEye, in any shape | empty, and read automatically |
| `derived-sources.json` | sources traced out of the client by cross-reference | 68 entries, each with quoted evidence |
| `unobtainable.json` | items that can no longer be obtained | 31, curated |
| `pet-levels.json` | feed power → pet level | empty — the client has no pet levels at all |

## Capturing a RealmEye page

**Claude does not fetch these.** `realmeye.com/robots.txt` names `Claude-Code`, `ClaudeBot`,
`Claude-User`, `Claude-Web` and `anthropic-ai` among 197 agents and then says `Disallow: /`.
Routing around that with a third-party fetcher would be the same request with a different
return address. A person browsing the site themselves is not a crawler, so the fetch is a
human step — but the reshaping is not.

### The easy way: `data/captures/`

Save the page, or select-all and paste it into a text file, and drop it in
`data/captures/`. Any name, any extension. Then run `build.ps1`.

The parser recognises **both ends against names the client already ships**: a line becomes
the current place only if it matches a real portal, and a line becomes an item only if it
matches a real item. That makes it safe to point at an arbitrary file — it cannot invent a
dungeon or an item — and tolerant of how the page came out. All three of these work:

```
Undead Lair                          <h2>Undead Lair</h2>        Undead Lair: Doom Bow,
Doom Bow                             <li>Doom Bow</li>             Spectral Sword
Spectral Sword                       <li>Spectral Sword</li>
```

The build prints what it did — `capture: page.html -> 137 items placed, 4 names not
recognised (…)` — so a page that came out wrong says so instead of silently doing nothing.
A capture only ever fills a gap: an item the client already places is never overruled.

### The precise way: a TSV

`realmeye-untiered-by-dungeon.tsv` and `realmeye-set-tier-items.tsv` are the same shape: one dungeon per line, a tab, then the items separated by
pipes.

```
Undead Lair	Doom Bow|Spectral Sword|Wandering Souls Spell|Ring of Skeletal Specters
Spider Den	Poison Fang Dagger|Spider's Eye Ring
```

Item names must match the game's display name exactly; the build matches them
case-insensitively with punctuation normalised, so a curly apostrophe is fine.

### The ST one specifically

`https://www.realmeye.com/wiki/set-tier-items` is the ST equivalent of the untiered page.
Save it, reshape it to the two columns above, drop it in as
`realmeye-set-tier-items.tsv`, and re-run `build.ps1`. 265 set pieces that currently say
**"set only"** will get a place.

They say "set only" because the client has nothing to offer, and that was checked four
ways before giving up on it:

* no enemy file anywhere names an ST item,
* no dungeon file names a set,
* set shards in `token.xml` carry no `ORG_` label,
* and no file in the dump references a shard object at all.

The 83 pieces that *do* have a source got it from `forgeProperties.xml`, which states the
craft recipe outright — for a modern ST that is the real answer.

## The rule these files live under

Anything in here is **community knowledge, not game data**, and the app says so wherever it
uses it: a `community` source is labelled "Player knowledge (RealmEye), not from the game
files" on hover, and `pet-levels.json`'s numbers are stamped with the sentence you write in
its `source` field. An entry with no stated provenance is treated as no entry.
