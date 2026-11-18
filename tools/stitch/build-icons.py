"""Rebuild the self-hosted Material Symbols subset used by the site.

    pip install fonttools brotli
    npm i material-symbols          # provides material-symbols-outlined.woff2 (variable font)
    python3 tools/stitch/build-icons.py <path/to/material-symbols-outlined.woff2>

Keeps only the icons listed in tools/stitch/icons-included.txt (add a name there and rerun), instanced to
wght 400 / opsz 24 / GRAD 0 with the FILL axis kept, and writes frontend/public/fonts/material-symbols-outlined-60online.woff2.
"""
import os, sys
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer
from fontTools import subset

HERE = os.path.dirname(os.path.abspath(__file__))
src = sys.argv[1]
names = [l.strip() for l in open(os.path.join(HERE, 'icons-included.txt')) if l.strip()]
f = TTFont(src, lazy=False)
cmap = f.getBestCmap(); rev = {g: chr(c) for c, g in cmap.items()}
lig = {}
for lk in f['GSUB'].table.LookupList.Lookup:
    for st in lk.SubTable:
        t = st if lk.LookupType == 4 else (st.ExtSubTable if lk.LookupType == 7 else None)
        if t is None or not hasattr(t, 'ligatures'):
            continue
        for first, ligs in t.ligatures.items():
            for L in ligs:
                lig[''.join(rev.get(g, '?') for g in [first] + list(L.Component))] = L.LigGlyph
missing = [n for n in names if n not in lig]
if missing:
    print('not in font (skipped):', missing)
keep = sorted(set(n for n in names if n in lig))
letters = [cmap[ord(c)] for c in 'abcdefghijklmnopqrstuvwxyz0123456789_' if ord(c) in cmap]
opts = subset.Options(); opts.layout_features = ['liga', 'rlig', 'calt', 'ccmp']; opts.notdef_outline = True; opts.layout_closure = False
s = subset.Subsetter(opts); s.populate(glyphs=[lig[n] for n in keep] + letters); s.subset(f)
inst = instancer.instantiateVariableFont(f, {'GRAD': 0, 'opsz': 24, 'wght': 400})
out = os.path.join(HERE, '..', '..', 'frontend', 'public', 'fonts', 'material-symbols-outlined-60online.woff2')
inst.flavor = 'woff2'; inst.save(out)
print(len(keep), 'icons ->', os.path.getsize(out), 'bytes')
