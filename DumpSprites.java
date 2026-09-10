// Dumps the sprite atlas index out of the client's spritesheetf (FlatBuffers).
//
// We compile against Tomato's own generated FlatBuffers classes rather than
// hand-rolling a parser — the schema is theirs, so their decoder is the one
// guaranteed to agree with the file.
//
//   javac -cp Tomato-v1.9.2.jar -d . DumpSprites.java
//   java  -cp "Tomato-v1.9.2.jar;." DumpSprites <spritesheetf> <out.tsv>
//
// SpriteSheetRoot holds TWO collections and both matter:
//
//   sprites[]          static art — every item, portal, bag, enchant icon and chest
//   animatedSprites[]  character art — every ENEMY, so every dungeon boss
//
// This originally dumped only the first, so no *Chars* sheet existed in the output at
// all. build-sprites.py could therefore never resolve a boss's real sprite and fell
// through to whatever nested <Texture> it could find — 39 of 56 bosses were scenery.
//
// An animated sprite is keyed by (name, index, set, direction, action); the idle,
// front-facing frame is direction 0 / action 0, which is the one a UI wants.
//
// Output is TSV: kind, sheet, atlasId, index, set, direction, action, x, y, w, h

import assets.flattbuffer.AnimatedSprite;
import assets.flattbuffer.Position;
import assets.flattbuffer.Sprite;
import assets.flattbuffer.SpriteSheet;
import assets.flattbuffer.SpriteSheetRoot;

import java.io.PrintWriter;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;

public class DumpSprites {
    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: DumpSprites <spritesheetf> <out.tsv>");
            System.exit(2);
        }
        byte[] raw = Files.readAllBytes(Paths.get(args[0]));
        ByteBuffer bb = ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN);
        SpriteSheetRoot root = SpriteSheetRoot.getRootAsSpriteSheetRoot(bb);

        int sheets = root.spritesLength();
        int animated = root.animatedSpritesLength();
        long statics = 0, anims = 0;

        try (PrintWriter out = new PrintWriter(
                Files.newBufferedWriter(Paths.get(args[1]), StandardCharsets.UTF_8))) {
            out.println("kind\tsheet\tatlasId\tindex\tset\tdirection\taction\tx\ty\tw\th");

            for (int i = 0; i < sheets; i++) {
                SpriteSheet ss = root.sprites(i);
                if (ss == null) continue;
                String name = ss.name();
                long atlas = ss.atlasId();
                int n = ss.spritesLength();
                for (int j = 0; j < n; j++) {
                    Sprite sp = ss.sprites(j);
                    if (sp == null) continue;
                    Position p = sp.position();
                    if (p == null) continue;
                    out.printf("s\t%s\t%d\t%d\t0\t0\t0\t%.0f\t%.0f\t%.0f\t%.0f%n",
                            name, atlas, sp.index(), p.x(), p.y(), p.w(), p.h());
                    statics++;
                }
            }

            for (int i = 0; i < animated; i++) {
                AnimatedSprite as = root.animatedSprites(i);
                if (as == null) continue;
                Sprite sp = as.sprites();
                if (sp == null) continue;
                Position p = sp.position();
                if (p == null) continue;
                out.printf("a\t%s\t%d\t%d\t%d\t%d\t%d\t%.0f\t%.0f\t%.0f\t%.0f%n",
                        as.name(), sp.aId(), as.index(), as.set(), as.direction(), as.action(),
                        p.x(), p.y(), p.w(), p.h());
                anims++;
            }
        }
        System.out.printf("sheets=%d static=%d animated=%d -> %s%n",
                sheets, statics, anims, args[1]);
    }
}
