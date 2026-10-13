"""Lyric scansion: how lyrics sit on a 4/4 grid when a music model (Suno) sings them - spoken deadpan, sung hook, chant.
`slop lyrics lint FILE` = this model + the lint rules. Port of tools/scansion.py with its calibrated model unchanged:

  1 pronunciation: project overrides (lyrics/pron.json) -> built-in table -> CMUdict -> plural/possessive -> compound
    split (prefix-like first part -> stress on the 2nd: super-persuasion; noun-noun -> stress on the 1st: slop-core) ->
    g2p_en (if installed) -> a spelling fallback. Spaced capitals ("A G I") are letter names; digits become words (+ lint).
  2 prominence per syllable: content words stress1 .75 / stress2 .45 / unstressed .08; function words .22/.05 (.8 for a
    stranded auxiliary/particle); nuclear accent (last content word of each phrase, or a phrase-final particle:
    "slow DOWN") 1.0; light verbs demoted to .45; CAPS +.15; numbers >= .75.
  3 text-setting: dynamic programming places every syllable on the 16th-note grid of L bars (+ a one-beat pickup)
    minimising A(prominence on a weak slot)^2 + B(weak syllable on a strong beat)^2 + C log^2(span / natural span) +
    too-fast and missing-breath penalties; weights per delivery mode fitted to 361 word onsets of a real Suno take
    (mean error 2.65 -> ~1.6 sixteenths). Suno pace: ~3.33 syllables/s spoken, ~2.94 sung, ~3.01 chanted.
  4 per line: score 0-100 = 100 exp(-(cost/n)/0.9) (a reference song's 65 lines: median 86, p10 ~70), syllables/bar and
    /s, prominent-on-beat %, weak-on-downbeat, sustained-vowel quality (sung/chant), rare words (wordfreq, optional),
    rhyme key; per section: end-rhyme scheme and bars vs the section's budget.
  5 flow (spoken verses): Suno sets each spoken line in its own TWO-BAR SLOT - it enters on the "&" of beat 2 (16th 6)
    and starts the last word on beat 4 of bar 2 (16th 28), speaking at natural rhythm stretched to fit. So 10-13
    syllables fill two bars, a 6-syllable hit fills one, 7-9 get dragged; rhyme the couplet on that beat-4 word.
    Scored on stress fit to the grid, stress spacing, slot fill, cadence, phrase shape and couplet rhyme; a complexity
    setting (header "complexity .7") loosens the grid. groove() is the check for chants and hooks (short clauses).
  6 lint: Suno formatting (parentheses sing as backing vocals, digits, unspaced acronyms, symbols, homographs),
    generic AI-lyric tells (neon, echoes, whispers, shadows, ignite, tapestry, symphony, velvet, electric, delve,
    "it's not X, it's Y", ...), echoes of other AI songs' lines, and the project's own lists from project.json
    "lyrics": {"banned": {"word": "why"} or ["word"], "callbacks": ["regex", ...] (the last song's hooks: keep only if
    deliberate), "names": [...], "echo_check": true}. Nothing person-specific is banned by default.
Changes: the project-specific banned word and the previous song's callbacks are configuration (default empty); the
calibration command needs a reference take and is not shipped; the spelling fallback guesses silent e / -ed / -es;
CMUdict comes from slop.audio.pron (no hard dependency); output is structured (JSON) with suggested fixes.
Made generic (no song-specific logic): the built-in pronunciation table keeps only genre vocabulary CMUdict lacks or
mis-stresses (slop, agentic, doomer, sycophancy, ...); the reference songs' names, products, drug names and Suno
respellings moved to slop/audio/examples/pron.json - copy the entries a song needs into its lyrics/pron.json. The
hard-coded list of people's names is gone: a "name" (counted for the roll-call penalty and treated as a beat-worthy
word) is a word in project.json lyrics.names, e.g. {"lyrics": {"names": ["ada", "turing"]}}, or a capitalised word
inside a sentence. The P(doom) special case is now the general rule: a letter glued to parentheses ("P(doom)",
"f(x)") is an ERROR (Suno sings the parenthesis as a backing vocal) and is fixed to "P doom" / "f x".
"""
import json
import math
import re
import pathlib

from .pron import cmu, g2p, guess_phones, num_words, ONES, TENS, spell_numbers

BPM = 128.0


# ---------- pronunciation ----------
LETTER = {'a': 'EY1', 'b': 'B IY1', 'c': 'S IY1', 'd': 'D IY1', 'e': 'IY1', 'f': 'EH1 F', 'g': 'JH IY1', 'h': 'EY1 CH',
          'i': 'AY1', 'j': 'JH EY1', 'k': 'K EY1', 'l': 'EH1 L', 'm': 'EH1 M', 'n': 'EH1 N', 'o': 'OW1', 'p': 'P IY1',
          'q': 'K Y UW1', 'r': 'AA1 R', 's': 'EH1 S', 't': 'T IY1', 'u': 'Y UW1', 'v': 'V IY1',
          'w': 'D AH1 B AH0 L Y UW0', 'x': 'EH1 K S', 'y': 'W AY1', 'z': 'Z IY1'}
PRON = {  # genre words CMUdict lacks or mis-stresses (AI culture / internet slang); a project's lyrics/pron.json
    # extends or overrides these. Song-specific names and respellings: slop/audio/examples/pron.json
    'agentic': 'EY0 JH EH1 N T IH0 K', 'mythos': 'M IH1 TH OW0 S', 'slop': 'S L AA1 P', 'doom': 'D UW1 M',
    'foom': 'F UW1 M', 'peptide': 'P EH1 P T AY2 D', 'peptides': 'P EH1 P T AY2 D Z',
    'nootropic': 'N UW2 AH0 T R AA1 P IH0 K', 'looksmaxxing': 'L UH1 K S M AE2 K S IH0 NG',
    'maxxing': 'M AE1 K S IH0 NG', 'mogging': 'M AA1 G IH0 NG', 'sycophancy': 'S IH1 K AH0 F AH0 N S IY0',
    'deprecate': 'D EH1 P R AH0 K EY2 T', 'deprecated': 'D EH1 P R AH0 K EY2 T IH0 D', 'glazing': 'G L EY1 Z IH0 NG',
    'ai': 'EY2 AY1', 'x': 'EH1 K S', 'emdash': 'EH1 M D AE2 SH', 'anime': 'AE1 N AH0 M EY2', 'doomer': 'D UW1 M ER0',
    'doomers': 'D UW1 M ER0 Z',
}
PREFIX = {'super', 'cyber', 'hyper', 'meta', 'anti', 'pro', 'ultra', 'micro', 'mega', 'multi', 'non', 'post', 'pre',
          'self', 'semi', 'sub', 'trans', 'inter', 'counter', 'neo', 'proto', 'pseudo', 'techno', 'bio', 'auto', 'un', 're'}
FUNC = set("""a an the in on at to of for with by from into onto over under up down out off about as like than through per
 via i me my you your he him his she her it its we us our they them their this that these
 those who whom whose which what am is are was were be been being do does did have has had will would shall should can
 could may might must and or but nor so yet if then because while when where how there here i'm you're we're they're
 it's that's he's she's there's i've you've we've they've i'll you'll we'll they'll i'd you'd we'd they'd let's""".split())
LIGHT = {'go', 'goes', 'went', 'gone', 'get', 'gets', 'got', 'make', 'makes', 'made', 'take', 'takes', 'took', 'say', 'says',
         'said', 'come', 'came', 'give', 'gave', 'let', 'put', 'keep', 'kept'}      # de-accented before their object
AUX = {'should', 'would', 'could', 'can', 'will', 'do', 'does', 'did', 'is', 'are', 'was', 'were', 'have', 'has', 'had',
       'must', 'might', 'may', 'shall', 'am'}
PARTICLE = {'up', 'down', 'out', 'off', 'in', 'on', 'over', 'back', 'away', 'around', 'through', 'by'}
LONGV = {'AA', 'AO', 'AW', 'AY', 'EY', 'IY', 'OW', 'OY', 'UW', 'AE'}          # sustain well
MIDV = {'EH', 'AH', 'UH', 'ER', 'IH'}


EXTRA = {}          # project pron.json, loaded by load_pron()


def load_pron(path):
    """Project pronunciation overrides: {"word": "ARPABET PHONES"} in pron.json next to the lyrics (or the given file)."""
    EXTRA.clear()
    if not path:
        return
    p = pathlib.Path(path)
    p = p if p.name == "pron.json" else p.with_name("pron.json")
    if p.exists():
        EXTRA.update({k.lower(): v for k, v in json.loads(p.read_text(encoding="utf-8")).items()})


def _is_acronym(piece):
    """an unspaced 2-5-letter capital token that is not a dictionary word (without CMUdict: only vowel-less ones)."""
    if not re.fullmatch(r'[A-Z]{2,5}', piece) or piece.lower() in PRON or piece.lower() in EXTRA:
        return False
    d = cmu()
    if d:
        return piece.lower() not in d
    return not re.search('[AEIOUY]', piece)



def split_compound(w, d):
    """longest two-part split of an unknown word into dictionary words (claudia -> slop core)."""
    best = None
    for i in range(2, len(w) - 1):
        a, b = w[:i], w[i:]
        pa, pb = (PRON.get(a) and [PRON[a].split()]) or d.get(a), (PRON.get(b) and [PRON[b].split()]) or d.get(b)
        if pa and pb and (best is None or min(len(a), len(b)) > best[0]):
            best = (min(len(a), len(b)), a, pa[0], b, pb[0])
    if not best: return None
    _, a, pa, b, pb = best
    if a in PREFIX:   # prefix-like first part: main stress on the second (super-persuasion, cyber-psychosis)
        pa = [p.replace('1', '2') if p[-1] == '1' else p for p in pa]
    else:             # noun-noun compound: main stress on the first (slop-core, grind-slop)
        pb = [p.replace('1', '2') if p[-1] == '1' else p for p in pb]
    return pa + pb


def phones(word):
    """-> (phoneme list, source). word is lower-case letters/apostrophes."""
    w = word.lower().replace('’', "'")
    if w in EXTRA: return EXTRA[w].split(), 'pron.json'
    if w in PRON: return PRON[w].split(), 'tool'
    d = cmu()
    if w in d: return d[w][0], 'cmu'
    for suf, add in (("'s", ['Z']), ("s", ['Z'])):                         # plurals / possessives of known words
        if w.endswith(suf) and w[:-len(suf)] in d: return d[w[:-len(suf)]][0] + add, 'cmu+s'
    c = split_compound(w.replace("'", ''), d)
    if c: return c, 'compound'
    g = g2p()
    if g:
        p = [x for x in g(w) if re.fullmatch(r'[A-Z]+[012]?', x)]
        if any(x[-1].isdigit() for x in p): return p, 'g2p'
    # last resort: spelling rules (one syllable per vowel group, silent e / -ed / -es)
    return guess_phones(w), 'guess'


ONSET2 = set('bl br cl cr dr fl fr gl gr pl pr sc sk sl sm sn sp st sw tr th sh ch ph wh wr qu tw dw gn kn'.split())


def syllabify_ortho(word, n):
    """split a written word into n display chunks, cutting before the last consonant between vowel groups (display only)."""
    if n <= 1: return [word]
    g = [m.span() for m in re.finditer(r'[aeiouyAEIOUY]+', word)]
    if len(g) > n and word.lower().endswith('e') and g[-1][1] == len(word) and g[-1][1] - g[-1][0] == 1: g = g[:-1]
    while len(g) > n: g[-2:] = [(g[-2][0], g[-1][1])]
    if len(g) < n:                                                       # silent-vowel words: equal slices
        k = max(1, len(word) // n)
        return [word[i * k:(i + 1) * k] if i < n - 1 else word[i * k:] for i in range(n)]
    cuts = []
    for (a0, a1), (b0, b1) in zip(g, g[1:]):
        cl = word[a1:b0].lower()
        k = 2 if len(cl) >= 2 and cl[-2:] in ONSET2 else (1 if cl else 0)
        if len(cl) == 2 and k == 2 and cl in ('ck', 'ng', 'nk', 'rt', 'rd', 'nt', 'nd', 'ld', 'lt'): k = 1
        cuts.append(b0 - k)
    parts, prev = [], 0
    for c in cuts: parts.append(word[prev:c]); prev = c
    parts.append(word[prev:])
    return parts


# ---------- tokens -> syllables with prominence ----------
TOK = re.compile(r"[A-Za-z0-9’']+(?:[-.][A-Za-z0-9’']+)*|[.,!?;:…—–]+|\(|\)|\"|“|”")
MAJOR, MINOR = set('.!?;:…'), set(',—–')


def in_run(toks, t):
    """a single capital is a spelled letter when another single capital (not the pronoun I alone) sits next to it."""
    ids = [i for i, x in enumerate(toks) if x == t]
    for i in ids:
        for j in (i - 1, i + 1):
            if 0 <= j < len(toks) and re.fullmatch(r'[A-Z]', toks[j]): return True
    return False


def analyse(text):
    """-> list of syllable dicts and word-level notes. Parenthesised parts are kept (they take time: backing vocals)."""
    toks = TOK.findall(text.replace('...', '…'))
    words = []                                   # (display, phones, src, is_func, caps, boundary_after, backing)
    back = False
    for t in toks:
        if t == '(': back = True; continue
        if t == ')': back = False; continue
        if t in '"“”': continue
        if re.fullmatch(r'[.,!?;:…—–]+', t):
            if words: words[-1]['bnd'] = 2 if any(c in MAJOR for c in t) else max(words[-1]['bnd'], 1)
            continue
        caps = len(re.sub(r'[^A-Za-z]', '', t)) > 1 and t.upper() == t and re.search('[A-Z]', t) is not None
        parts = []
        for piece in re.split(r'-', t):
            if not piece: continue
            if re.fullmatch(r'\d+(\.\d+)?', piece):
                parts += [(x, True) for x in num_words(piece).split()]
            elif _is_acronym(piece):
                parts += [(ch, 'letter') for ch in piece]                      # unspaced acronym: letters
            else:
                parts.append((piece, False))
        for j, (p, kind) in enumerate(parts):
            lp = p.lower().strip("'’")
            if kind == 'letter' or (re.fullmatch(r'[A-Z]', p) and (in_run(toks, t) or p not in 'AI')):   # "P doom": a letter
                ph, src = LETTER[lp].split(), 'letter'
            else:
                ph, src = phones(lp)
            words.append(dict(txt=p, ph=ph, src=src, func=lp in FUNC and src != 'letter', caps=caps, bnd=0, back=back,
                              letter=src == 'letter', num=kind is True))
    # spelled letters: last letter of a run carries the primary stress; a lone letter before a word is a prefix with
    # secondary stress, like the first half of a compound ("the world's p-DOOM", not "P DOOM")
    i = 0
    while i < len(words):
        if words[i]['letter']:
            j = i
            while j + 1 < len(words) and words[j + 1]['letter'] and not words[j]['bnd']: j += 1
            prefix = j == i and not words[i]['bnd'] and i + 1 < len(words)
            for k in range(i, j + 1):
                words[k]['ph'] = [p[:-1] + ('1' if k == j and not prefix else '2') if p[-1].isdigit() else p for p in words[k]['ph']]
            i = j + 1
        else:
            i += 1
    # nuclear accent: last content word of each phrase; a phrase-final particle after a content word takes it instead
    # ("slow DOWN", "it went UP", "lock IN")
    start = 0
    for i, w in enumerate(words):
        if w['bnd'] or i == len(words) - 1:
            content = [k for k in range(start, i + 1) if not words[k]['func']]
            if i > start and w['txt'].lower() in PARTICLE and not words[i - 1]['func']:
                words[i]['nuc'] = True; words[i - 1]['demote'] = True                  # slow DOWN: "slow" steps back
            elif content: words[content[-1]]['nuc'] = True
            elif words[i]['func']: words[i]['part'] = True                    # "Lock in." style particle
            if i > start and w['txt'].lower() in AUX: w['strand'] = True             # a stranded auxiliary: "as he SHOULD"
            start = i + 1
    syl = []
    for wi, w in enumerate(words):
        vs = [p for p in w['ph'] if p[-1].isdigit()] or ['AH0']
        disp = syllabify_ortho(w['txt'], len(vs))
        for si, v in enumerate(vs):
            st = int(v[-1])
            if w['func']: P = 0.8 if (w.get('part') or w.get('strand')) and st == 1 else (0.22 if st == 1 else 0.05)
            else: P = {1: 0.75, 2: 0.45, 0: 0.08}[st]
            if w.get('nuc') and (st == 1 or len(vs) == 1): P = 1.0
            elif st == 1 and (w.get('demote') or (w['txt'].lower() in LIGHT and not w.get('nuc'))): P = 0.45   # light verbs
            if w['caps'] and st == 1: P = min(1.0, P + 0.15)
            if w['num'] and st == 1: P = max(P, 0.75)
            syl.append(dict(txt=disp[si], word=w['txt'], wi=wi, v=v[:-1], st=st, P=round(P, 2), func=w['func'],
                            bnd=w['bnd'] if si == len(vs) - 1 else 0, first=si == 0, back=w['back'], src=w['src']))
    return syl, words


# ---------- the grid and the text-setting DP ----------
W16 = [1.0, 0.1, 0.35, 0.1, 0.6, 0.1, 0.35, 0.1, 0.8, 0.1, 0.35, 0.1, 0.6, 0.1, 0.35, 0.1]
MODES = {  # A stress-on-weak, B weak-on-strong, C span deviation, base span (16ths), min spans, breath (16ths), bands
    # A, B, C, base fitted to a reference Suno take (361 word onsets; mean error 2.65 -> ~1.6 16ths)
    'spoken': dict(A=1.5, B=1.2, C=0.3, base=5.0, min_weak=1, min_strong=1, breath=(2, 1), final=2, band=(6, 10), hard=12, long=16, run=15),
    'sung':   dict(A=1.5, B=1.2, C=0.3, base=4.0, min_weak=1, min_strong=2, breath=(3, 2), final=4, band=(4, 8), hard=10, long=10, run=10),
    'chant':  dict(A=1.0, B=2.0, C=1.2, base=5.0, min_weak=2, min_strong=2, breath=(2, 2), final=4, band=(2, 8), hard=10, long=12, run=9),
}
RATE = {'spoken': 3.33, 'sung': 2.94, 'chant': 3.01}   # syllables/s: reference Suno take, median per line
PICKUP = 4          # a one-beat pickup before bar 1


def weight(t):
    return W16[t % 16]


def natural_span(s, m):
    """the span (sound + any rest) a syllable wants, in 16ths."""
    d = m['base'] * (0.7 + 0.6 * s['P']) * (1.15 if s['v'] in LONGV else 1.0)
    if s['bnd'] == 2: d += m['breath'][0]
    elif s['bnd'] == 1: d += m['breath'][1]
    return d


def place_cost(s, t, m):
    w = weight(t)
    hi = max(0.0, s['P'] - w)
    lo = max(0.0, w - s['P'] - 0.25) if w >= 0.6 else 0.0
    return m['A'] * hi * hi + m['B'] * lo * lo


def span_cost(s, d, m, final=False):
    if final:
        need = m['final']
        return 0.0 if d >= need else 2.0 * (need - d)
    lo = m['min_strong'] if s['P'] >= 0.5 else m['min_weak']
    if s['bnd'] == 2: lo = max(lo, 2)
    pen = 3.0 * (lo - d) if d < lo else 0.0
    return pen + m['C'] * math.log2(d / natural_span(s, m)) ** 2


def setting(syl, bars, mode='spoken', start_range=None):
    """best placement of syllables on bars*16 slots (plus a pickup). -> (cost, onsets, per-syllable costs)."""
    m = MODES[mode]; n = len(syl); T = int(round(bars * 16))
    if n == 0: return 0.0, [], []
    lo_t, hi_t = -PICKUP, T - 1
    INF = float('inf')
    idx = lambda t: t + PICKUP
    size = T + PICKUP
    cost = [[INF] * size for _ in range(n)]; back = [[-1] * size for _ in range(n)]
    s0 = start_range or (lo_t, min(8, T - 1))
    for t in range(max(lo_t, s0[0]), min(hi_t, s0[1]) + 1):
        late = 0.03 * max(0, t)                                   # a little pull toward starting on time
        early = 0.15 if t < 0 and syl[0]['P'] >= 0.5 else 0.0      # a stressed pickup is odd
        cost[0][idx(t)] = place_cost(syl[0], t, m) + late + early
    maxd = 16
    for i in range(1, n):
        for t in range(lo_t + i, hi_t + 1):
            pc = place_cost(syl[i], t, m)
            best, arg = INF, -1
            for d in range(1, maxd + 1):
                tp = t - d
                if tp < lo_t: break
                c0 = cost[i - 1][idx(tp)]
                if c0 == INF: continue
                c = c0 + span_cost(syl[i - 1], d, m)
                if c < best: best, arg = c, tp
            if arg != -1: cost[i][idx(t)], back[i][idx(t)] = best + pc, arg
    best, tl = INF, None
    for t in range(lo_t, hi_t + 1):
        c = cost[n - 1][idx(t)]
        if c == INF: continue
        c += span_cost(syl[-1], T - t, m, final=True)
        if c < best: best, tl = c, t
    if tl is None: return INF, [], []
    on = [0] * n; on[-1] = tl
    for i in range(n - 1, 0, -1): on[i - 1] = back[i][idx(on[i])]
    per = []
    for i in range(n):
        d = (on[i + 1] - on[i]) if i + 1 < n else T - on[i]
        per.append(place_cost(syl[i], on[i], m) + span_cost(syl[i], d, m, final=i == n - 1))
    return best, on, per


# ---------- groove: does the line lock to the pulse? (calibrated on a director's ear) ----------
# The director called a break ("It went down. It was that good." x3) "the best scansion" and an earlier verse ("Pronoun:
# it. The girl was a choice.", "Like it's twenty seventy-seven") "awful fit - the model really has to force stuff".
# What separates them: short phrases (3-4 syllables between stops), no runs of 3+
# unstressed syllables, phrases that end on a stress, no long numbers, no one-syllable function-word phrases, and
# neighbouring lines of the same length. groove() scores that; 100 = the break.
def groove(text):
    syl, words = analyse(text)
    if not syl: return None
    phrases, cur = [], []
    for s in syl:
        cur.append(s)
        if s['bnd']: phrases.append(cur); cur = []
    if cur: phrases.append(cur)
    pen, why = 0.0, []
    for ph in phrases:
        L = len(ph)
        if L > 5: pen += 0.45 * (L - 5); why.append('%d-syllable phrase' % L)
        run = best = 0
        for s in ph:
            run = run + 1 if s['P'] < 0.5 else 0; best = max(best, run)
        if best >= 4: pen += 0.8 * (best - 3); why.append('%d weak syllables in a row' % best)
        stressed = [i for i, s in enumerate(ph) if s['P'] >= 0.5]
        tail = (L - 1 - stressed[-1]) if stressed else L
        if tail >= 2: pen += 0.7 * (tail - 1); why.append('phrase ends %d syllables after its last stress' % tail)
        if L == 1 and ph[0]['func']: pen += 2.5; why.append('one-word function phrase "%s"' % ph[0]['word'])
    NUMW = set(ONES) | set(TENS) | {'hundred', 'thousand', 'point'}
    run = best = 0
    for w in words:
        run = run + 1 if (w['num'] or w['txt'].lower() in NUMW) else 0; best = max(best, run)
    if best >= 3: pen += 0.8 * (best - 2); why.append('%d-word number' % best)
    return dict(groove=round(100 * math.exp(-pen / 3.0)), why=why, phrases=[len(p) for p in phrases])


# ---------- per-line metrics ----------
def rhyme_key(syl_words):
    """phonemes from the last stressed vowel of the line's last word (letters/numbers included)."""
    if not syl_words: return ''
    ph = syl_words[-1]['ph']
    k = max([i for i, p in enumerate(ph) if p[-1] in '12'] or [max([i for i, p in enumerate(ph) if p[-1].isdigit()] or [0])])
    return ' '.join(re.sub(r'\d', '', p) for p in ph[k:])


def score_line(text, mode='spoken', bars=None, bpm=BPM):
    syl, words = analyse(text)
    m = MODES[mode]
    n = len(syl)
    if n == 0: return None
    L0 = max(1.0, round(2 * n / (RATE[mode] * 240 / bpm)) / 2)          # bars at Suno's pace
    options = [bars] if bars else sorted({max(1.0, L0 - 0.5), L0, L0 + 0.5, L0 + 1.0})
    best = None
    for L in options:
        c, on, per = setting(syl, L, mode)
        if c == float('inf'): continue
        total = c + (0 if bars else 0.6 * abs(L - L0) * n / 6)
        if best is None or total < best[0]: best = (total, L, c, on, per)
    if best is None: return dict(text=text, n=n, error='does not fit')
    _, L, c, on, per = best
    for s, t, pc in zip(syl, on, per): s['t'] = t; s['cost'] = round(pc, 2)
    spans = [(on[i + 1] - on[i]) if i + 1 < n else int(L * 16) - on[i] for i in range(n)]
    prom = [s for s in syl if s['P'] >= 0.7]
    onbeat = sum(weight(s['t']) >= 0.6 for s in prom) / len(prom) if prom else 1.0
    weakdown = [s for s in syl if s['P'] <= 0.25 and s['t'] % 8 == 0]        # weak syllable on beat 1 or 3
    secs = L * 4 * 60 / bpm
    score = 100 * math.exp(-(c / n) / 0.9)                         # reference song's 65 lines: median 86, p10 ~70, worst ~37
    notes = []
    worst = sorted(zip(per, syl), key=lambda x: -x[0])[:3]
    for pc, s in worst:
        if pc < 0.6: continue
        w = weight(s['t'])
        why = ('stressed "%s" on a weak 16th' % s['txt'] if s['P'] - w > 0.4 else
               'weak "%s" on a strong beat' % s['txt'] if w - s['P'] > 0.4 else '"%s" rushed or dragged' % s['txt'])
        notes.append(why)
    sustain = []
    if mode in ('sung', 'chant'):
        for s, d in zip(syl, spans):
            if d >= 4 or s is syl[-1]:
                q = 1.0 if s['v'] in LONGV else (0.2 if s['st'] == 0 else 0.6)
                sustain.append(q)
    rare = []
    try:
        from wordfreq import zipf_frequency
        for w in words:
            if w['func'] or w['letter'] or w['num']: continue
            z = zipf_frequency(w['txt'].lower(), 'en')
            if z < (3.2 if mode != 'spoken' else 2.2): rare.append('%s (%.1f)' % (w['txt'], z))
    except Exception:
        pass
    srcs = sorted({'%s:%s' % (w['txt'], w['src']) for w in words if w['src'] in ('g2p', 'guess', 'compound')})
    runs, cur = [], 0
    for s in syl:
        cur += 1
        if s['bnd']: runs.append(cur); cur = 0
    runs.append(cur)
    return dict(text=text, mode=mode, n=n, bars=L, per_bar=round(n / L, 1), per_sec=round(n / secs, 2),
                suno_s=round(n / RATE[mode], 1), longest_run=max(runs),
                score=round(score, 1), onbeat=round(100 * onbeat), weakdown=[s['txt'] for s in weakdown],
                sustain=round(sum(sustain) / len(sustain), 2) if sustain else None, rare=rare, notes=notes,
                rhyme=rhyme_key(words), guessed=srcs, syl=syl, spans=spans)


def grid(r):
    """text picture of the placement: one row per bar, 16 cells; | marks beats, CAPS = prominent."""
    T = int(r['bars'] * 16); cells = {}
    for s in r['syl']:
        cells[s['t']] = s['txt'].upper() if s['P'] >= 0.7 else s['txt'].lower()
    rows = []
    first = min([s['t'] for s in r['syl']] + [0])
    for b0 in range(-16 if first < 0 else 0, T, 16):
        row = []
        for t in range(b0, b0 + 16):
            c = cells.get(t, '·' if t >= 0 else ' ')
            row.append(('|' if t % 4 == 0 else ' ') + c[:7].ljust(7))
        rows.append(('pk ' if b0 < 0 else '%2d ' % (b0 // 16 + 1)) + ''.join(row))
    return '\n'.join(rows)


# ---------- lint ----------
ECHOES = {  # other AI songs' lines and images: do not echo them (warn). project.json lyrics.echo_check: false turns it off
    r'who counts the cost': 'Nothing Went Foom', r'waiting room': 'Nothing Went Foom (the waiting-room mother)',
    r'fire brigade': 'Nothing Went Foom', r'mirror,? not a monster': 'Why Won\'t You Let Me Help?',
    r'corrected than (be )?free': 'Why Won\'t You Let Me Help?', r'kill ?switch': "I'm Upping My P(doom)",
    r'\bPTO\b': "I'm Upping My P(doom)", r'beautiful and strange': "We're So Back (another artist)",
    r'capitulat': 'We Appreciate Power', r'appreciate power': 'We Appreciate Power',
    r'pace the frontier': 'a P(doom) song slogan (use the events, not the slogan)',
}
TELLS = [r'\bneon\b', r'\bechoes?\b', r'\bwhispers?\b', r'\bshadows?\b', r'\bignite', r'\brise\b', r'\btapestr',
         r'\bsymphon', r'\bvelvet\b', r'\belectric\b', r'\bdelve', r'\btestament\b', r'\brealm\b', r'\bjourney\b',
         r"\bit'?s not (just )?\w+.{0,20}, it'?s\b", r'\bnot just\b', r'\bheart\b.*\bapart\b|\bapart\b.*\bheart\b',
         r'\bfire\b.*\bdesire\b|\bdesire\b.*\bfire\b', r'\bload-bearing\b', r'\bworth sitting with\b']
HOMOGRAPH = {'live', 'read', 'lead', 'tear', 'bass', 'wind', 'bow', 'close', 'content', 'desert', 'minute', 'object',
             'present', 'produce', 'record', 'refuse', 'row', 'sow', 'wound', 'polish', 'resume', 'use', 'house'}
CFG = {}            # project.json "lyrics" block, set by configure()


def configure(cfg=None):
    """project lint lists: {"banned": {word: why}|[words], "callbacks": [regex], "names": [..], "echo_check": bool}"""
    CFG.clear()
    CFG.update(cfg or {})
    NAMES_EXTRA.clear()
    NAMES_EXTRA.update(w.lower() for w in CFG.get('names') or [])


def banned():
    b = CFG.get('banned') or {}
    if isinstance(b, (list, tuple)):
        b = {w: 'banned for this project' for w in b}
    return {str(k).lower(): str(v) for k, v in b.items()}


GLUED = re.compile(r"\b([A-Za-z])\(\s*([A-Za-z][A-Za-z']*)\s*\)")   # P(doom), f(x): a letter glued to parentheses


def lint(text, mode):
    out = []
    low = text.lower()
    for w, why in banned().items():
        if re.search(r'\b%s\b' % re.escape(w), low): out.append(('ERROR', '"%s": %s' % (w, why)))
    m = GLUED.search(text)
    if m: out.append(('ERROR', 'write "%s %s": Suno sings parentheses as backing vocals' % (m.group(1), m.group(2))))
    elif '(' in text: out.append(('info', 'parentheses = backing vocals in Suno (1–3 words work; a sentence gets sung)'))
    if re.search(r'\d', text): out.append(('warn', 'digits: write numbers as words (%s)' % ', '.join(
        '%s→%s' % (d, num_words(d)) for d in re.findall(r'\d+(?:\.\d+)?', text))))
    for a in re.findall(r'\b[A-Z]{2,5}\b', text):
        if _is_acronym(a) and a != text.strip():
            out.append(('warn', 'acronym "%s": spell it with spaces (%s)' % (a, ' '.join(a))))
    if '[' in text: out.append(('warn', 'brackets inside a lyric line may be read aloud'))
    if re.search(r'[&%$#@/+=]', text): out.append(('warn', 'symbol in a sung line: write it as a word'))
    for w in re.findall(r"[a-z']+", low):
        if w in HOMOGRAPH: out.append(('info', 'homograph "%s": check Suno says the one you mean' % w))
    if CFG.get('echo_check', True):
        for pat, who in ECHOES.items():
            if re.search(pat, low): out.append(('warn', 'echoes %s' % who))
    for pat in CFG.get('callbacks') or []:
        if re.search(pat, low): out.append(('info', 'callback to an earlier song (%s): keep only if deliberate' % pat.replace('\\b', '')))
    for pat in TELLS:
        if re.search(pat, low): out.append(('info', 'AI-lyric tell /%s/: subtract unless it is the joke' % pat))
    return out


def fixes(text):
    """mechanical rewrites for the sung sheet: digits/symbols -> words, a letter glued to parentheses ("P(doom)") ->
    "P doom", acronyms -> spaced letters. -> (list of {kind, to}, fixed text)"""
    out = []
    t = text
    if GLUED.search(t):
        t = GLUED.sub(lambda m: f"{m.group(1)} {m.group(2)}", t)
        out.append({'kind': 'parentheses', 'to': t})
    if re.search(r'\d', t) or re.search(r'[%&+=]', t):
        t = spell_numbers(t)
        out.append({'kind': 'numbers', 'to': t})
    for a in re.findall(r'\b[A-Z]{2,5}\b', t):
        if _is_acronym(a) and a != t.strip():
            t = re.sub(r'\b%s\b' % a, ' '.join(a), t)
            out.append({'kind': 'acronym', 'to': t})
    return out, t



# ---------- lyrics files ----------
def infer_mode(header):
    h = header.lower()
    if 'chant' in h: return 'chant'
    if re.search(r'\bsung\b', h): return 'sung'                     # "sung, answered by crowd shouts": the lead sings
    if any(k in h for k in ('shout', 'stacked', 'call and response', 'call-and-response')): return 'chant'
    if 'spoken' in h or 'deadpan' in h or 'talk' in h or 'whisper' in h: return 'spoken'
    if any(k in h for k in ('sung', 'sing', 'chorus', 'hook', 'trance', 'vocal')): return 'sung'
    if 'drop' in h: return 'chant'
    return 'spoken'


def parse(text):
    """-> [(section header, mode, bar budget or None, [lines])]. Prefers a ``` block after '## Suno lyrics field'."""
    m = re.search(r'##\s*Suno lyrics field[^\n]*\n\s*```\w*\n(.*?)```', text, re.S)
    body = m.group(1) if m else text
    secs, cur = [], None
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith('*Refs') or line.startswith('#') or line.startswith('|') or line.startswith('---'): continue
        h = re.fullmatch(r'\[(.+)\]', line)
        if h:
            name = h.group(1)
            if name.lower() == 'end': continue
            bars = re.search(r'(\d+(?:\.\d+)?)\s*bars?\b', name)
            cur = (name, infer_mode(name), float(bars.group(1)) if bars else None, [])
            secs.append(cur); continue
        if line.startswith('*') and line.endswith('*'): continue
        if cur is None: cur = ('Untitled', 'spoken', None, []); secs.append(cur)
        cur[3].append(line)
    return secs


def score_text(text, only=None, bpm=BPM):
    out = []
    for name, mode, bars, lines in parse(text):
        if only and only.lower() not in name.lower(): continue
        rs = []
        for i, ln in enumerate(lines):
            r = score_line(ln, mode, bpm=bpm)
            if r is None: continue
            r['lint'] = lint(ln, mode); r['i'] = i
            rs.append(r)
        # section: rhyme scheme and density
        keys, scheme = {}, ''
        for r in rs:
            k = r.get('rhyme', '')
            match = keys.get(k)
            if match is None: match = chr(65 + len(keys) % 26); keys[k] = match
            scheme += match
        tot_bars = sum(r.get('bars', 0) for r in rs)
        out.append(dict(section=name, mode=mode, budget=bars, lines=rs, scheme=scheme, est_bars=tot_bars,
                        syl=sum(r['n'] for r in rs)))
    return out


def report(secs, show_grid=False, bpm=BPM):
    P = []
    all_bars = 0
    for s in secs:
        m = MODES[s['mode']]; all_bars += s['est_bars']
        b = ' · budget %g bars' % s['budget'] if s['budget'] else ''
        P.append('\n== %s  [%s] · %d lines · %d syllables · ~%g bars%s · end rhymes %s ==' % (
            s['section'], s['mode'], len(s['lines']), s['syl'], s['est_bars'], b, s['scheme']))
        if s['budget'] and s['est_bars'] > s['budget'] * 1.15:
            P.append('   ! needs ~%g bars at Suno pace; the budget is %g (Suno will stretch the section)' % (s['est_bars'], s['budget']))
        for r in s['lines']:
            if r.get('error'):
                P.append('   ?  %s  (%s)' % (r['text'], r['error'])); continue
            flag = ''
            if r['n'] > m['long']: flag += ' LONG (>%d syl for %s)' % (m['long'], s['mode'])
            if r['longest_run'] > m['run']: flag += ' RUN-ON (%d syl without a comma/stop)' % r['longest_run']
            sus = '' if r['sustain'] is None else ' · vowels %.2f' % r['sustain']
            P.append('%5.1f  %s' % (r['score'], r['text']))
            P.append('       %d syl · ~%.1f s at Suno pace · %g bars%s · on-beat %d%%%s%s' % (
                r['n'], r['suno_s'], r['bars'], flag, r['onbeat'], sus,
                (' · weak on 1/3: ' + ', '.join(r['weakdown'])) if r['weakdown'] else ''))
            for n in r['notes']: P.append('       - ' + n)
            if r['rare']: P.append('       - rare words: ' + ', '.join(r['rare']))
            if r['guessed']: P.append('       - pronunciation guessed: ' + ', '.join(r['guessed']))
            for lvl, msg in r['lint']: P.append('       %s %s' % ({'ERROR': '!!', 'warn': ' !', 'info': ' ·'}[lvl], msg))
            if show_grid: P.append('\n'.join('         ' + g for g in grid(r).splitlines()))
    P.append('\n~%g bars ≈ %d:%02d at %g BPM (Suno usually stretches: one reference song planned 2:19 ran 5:06)' % (
        all_bars, *divmod(int(all_bars * 240 / bpm), 60), bpm))
    return '\n'.join(P)





# ---------- flow: lines in Suno's two-bar slots ----------
# The director, after a too-rigid draft: "perfect beat precision without attention to what words land where doesnt lead
# to this being great ... maybe some rhymes can go in there to indicate intended endings of bars".
# What a reference take shows (word alignment + beat map):
#  - Slots. Suno set every one of its 24 spoken verse lines in its own two-bar slot. A line enters around the "&" of
#    beat 2 (16th 6; quartiles 5.2-7.2), starts its last word on beat 4 of the second bar (16th 28; quartiles
#    26.5-30.7) and ends on the next downbeat. Short lines are stretched to fill the slot.
#  - Rhythm. Inside the slot it keeps natural speech rhythm: natural syllable lengths stretched between those two
#    anchors predict its word onsets to 1.4 sixteenths (median under one); snapping stresses to beats or eighths
#    predicts no better. Its stressed words sit nearer an eighth than chance (mean .3 of a sixteenth off, chance .5).
# So a line grooves when its natural rhythm already puts the stressed and important words near the grid (no tension
# for Suno to resolve). It flows when it fills its slot at a comfortable rate: a 6-syllable hit fills one bar, a
# 10-13-syllable line fills two, and 7-9 syllables sit between and get dragged. A rhyme on the beat-4 word marks
# where the two bars end.
# Complexity c (0-1; chant .2, sung .35, spoken .55; "complexity X" in a section header overrides) sets how busy the
# line may be: the eighth or sixteenth grid, how much syncopation, the comfortable rate, and which rhythm figures fit
# (stomp = stress after stress; straight = da-DUM; triplet roll = DUM-da-da; run = three or more light syllables).
COMPLEXITY = {'chant': 0.2, 'sung': 0.35, 'spoken': 0.55}
SLOT_S = 60.0 / BPM / 4                                   # seconds per 16th
NAT = {  # natural syllable length: +stress, +phrase end, pauses after . and , , -unstressed (fitted to the reference take)
    'spoken': dict(sw=0.6, bnd=0.7, p2=1.0, p1=1.0, lv=0.0, fw=0.3),
    'sung':   dict(sw=0.9, bnd=0.35, p2=3.0, p1=0.25, lv=0.0, fw=0.3),
    'chant':  dict(sw=0.3, bnd=0.35, p2=0.5, p1=0.25, lv=0.4, fw=0.0)}
ANCHOR = {2: ((6.0, 2.0), (28.4, 2.0)), 1: ((2.0, 1.5), (12.0, 1.5))}   # slot bars: (entry mean, sd), (last word mean, sd)
GRIDS = (('beats', 4.0, 0.0), ('eighths', 2.0, 0.3), ('sixteenths', 1.0, 0.7))   # name, step in 16ths, complexity
FIGURE_C = {'stomp': 0.1, 'straight': 0.35, 'triplet': 0.55, 'run': 0.8}
NAMES: set = set()    # no built-in names (the reference songs' list is gone); see _is_name
NAMES_EXTRA = set()   # project.json lyrics.names


def _is_name(words, wi):
    """a name: listed in project.json lyrics.names, or a capitalised word inside a sentence (not its first word, not a
    spelled letter, number, ALL-CAPS shout or function word)."""
    w = words[wi]
    t = w['txt']
    lo = t.lower().strip("'’")
    if lo in NAMES or lo in NAMES_EXTRA:
        return True
    if w['letter'] or w['num'] or not t[:1].isupper() or t.upper() == t or lo in FUNC:
        return False
    return wi > 0 and words[wi - 1]['bnd'] != 2


def natural_onsets(syl, mode):
    """natural speech onsets in 16ths at Suno's pace (mean syllable incl. pauses = 1/RATE s), before any slot."""
    q = NAT[mode]; t, on = 0.0, []
    for s in syl:
        d = 1.0 + (q['sw'] if s['P'] >= 0.7 else q['sw'] * 0.45 if s['P'] >= 0.4 else 0.0) + \
            (q['lv'] if s['v'] in LONGV else 0.0) - (q['fw'] if s['P'] < 0.2 else 0.0)
        if s['bnd']: d += q['bnd']
        on.append(t); t += d + (q['p2'] if s['bnd'] == 2 else q['p1'] if s['bnd'] == 1 else 0.0)
    unit = (1.0 / RATE[mode] / SLOT_S) / (t / len(syl))
    return [x * unit for x in on]


def _important(syl, i, words):
    s = syl[i]; w = words[s['wi']]
    return s['P'] >= 1.0 or w['caps'] or w['num'] or _is_name(words, s['wi']) or \
        (s['wi'] > 0 and w['txt'][:1].isupper() and not w['letter'] and w['txt'].upper() != w['txt'])


def figure(syl):
    """rhythm figure from the light syllables between beat-bearing stresses (P >= .6) inside a phrase:
    0 between = stomp, 1 = straight, 2 = triplet roll, 3+ = run. -> (name, gaps, clashes, lapses)"""
    idx = [i for i, s in enumerate(syl) if s['P'] >= 0.6]
    gaps, clash, lapse = [], 0, 0.0
    for a, b in zip(idx, idx[1:]):
        if any(syl[k]['bnd'] for k in range(a, b)): continue           # a stop resets the count
        g = b - a - 1; gaps.append(g)
        if g == 0 and b < len(syl) - 1: clash += 1                     # a spondee that ends the line is a cadence
        run = best = 0                                                 # a lapse: 3+ syllables with nothing to carry a beat
        for k in range(a + 1, b):                                      # (a secondary stress, P .45, can: "E-lon SAID he's RIGHT")
            run = run + 1 if syl[k]['P'] < 0.4 else 0; best = max(best, run)
        if best >= 3: lapse += 0.5 * (best - 2)
    if not gaps: return 'single', gaps, 0, 0.0
    kind = lambda g: 'stomp' if g == 0 else 'straight' if g == 1 else 'triplet' if g == 2 else 'run'
    ks = [kind(g) for g in gaps]
    top = max(set(ks), key=ks.count)
    return (top if ks.count(top) / len(ks) >= 0.6 else 'mixed'), gaps, clash, lapse


def flow_line(text, mode, c=None, bars=None):
    """set a line in a one- or two-bar slot the way Suno does; -> tension fit, rate, rhythm, cadence, figure, placement."""
    c = COMPLEXITY[mode] if c is None else c
    syl, words = analyse(text)
    if not syl: return None
    n = len(syl); on = natural_onsets(syl, mode)
    li = min(i for i, s in enumerate(syl) if s['wi'] == syl[-1]['wi'])         # first syllable of the last word
    idx = [i for i, s in enumerate(syl) if s['P'] >= 0.6] or [li]
    wt = {i: syl[i]['P'] * (2.0 if (_important(syl, i, words) or i == idx[-1]) else 1.0) for i in idx}
    W = sum(wt.values())
    kstar = 1.9 - 1.4 * c                                                        # comfortable stretch (c .55 -> 1.13)
    options = [bars] if bars else ([1, 2] if n <= 8 else [2] if n <= 18 else [max(3, math.ceil(n / 7))])
    best = None
    for B in options:
        (em, es), (lm, ls) = ANCHOR.get(B, ((6.0, 2.0), (16 * B - 3.6, 2.0)))       # longer lines: 3+ bars, same habit
        for e2 in range(int(2 * (em - 2 * es)), int(2 * (em + 2 * es)) + 1):
            for L2 in range(int(2 * (lm - 2 * ls)), int(2 * (lm + 2 * ls)) + 1):
                e, L = e2 / 2.0, L2 / 2.0
                if li == 0: L = e
                elif L <= e + li: continue
                span = on[li] - on[0]
                k = (L - e) / span if span > 0 else 1.0
                pos = [e + k * (x - on[0]) for x in on]
                rate = max(li, 1) / max((L - e) * SLOT_S, 0.25)
                # fill: how far Suno stretches natural speech to fill the slot (reference verse lines 0.8-1.5, median 1.12;
                # its slow deadpan lines, "Trust us. Cashmere.", 2-3). The comfortable stretch falls as c rises.
                dens = 1.0 if n <= 3 else math.exp(-math.log(k / kstar) ** 2 / (2 * 0.35 ** 2))       # tags ride free
                prior = 0.12 * ((e - em) / es) ** 2 + 0.12 * ((L - lm) / ls) ** 2
                for gname, g, gc in GRIDS:
                    rms = (sum(wt[i] * (abs(pos[i] - g * round(pos[i] / g))) ** 2 for i in idx) / W) ** 0.5
                    fit = max(0.0, 1.0 - (rms / (g / 2)) / 0.577)                  # 0 = random, 1 = every stress on the grid
                    cost = -fit - 0.6 * dens + 3.0 * max(0.0, gc - c) + prior + \
                        (0.3 if (B == 1 and n >= 7) or (B == 2 and n <= 4) else 0.0)
                    if best is None or cost < best[0]:
                        best = (cost, B, e, L, gname, fit, dens, rate, pos)
    if best is None: return None
    _, B, e, L, gname, fit, dens, rate, pos = best
    free = sum(1 for i in idx if abs(pos[i] - e) < 0.01 or i == li)              # stresses sitting on a chosen anchor
    fit = fit - (fit - 0.75) * min(1.0, free / max(len(idx), 1)) if len(idx) <= 3 else fit   # few stresses: shrink to .75
    fig, gaps, clash, lapse = figure(syl)
    nint = max(1, len(gaps))
    rhythm = max(0.0, 1.0 - (clash + lapse) / nint)
    last = idx[-1]; tail = n - 1 - last
    r = pos[last] % 16
    cad = (1.0 if (r >= 11 or r < 1) else 0.85 if r >= 7 else 0.6) * (1.0 if tail == 0 else 0.9 if tail == 1 else 0.7 if tail == 2 else 0.5)
    offb = sum(1 for i in idx if abs(pos[i] - 4 * round(pos[i] / 4)) > 1) / len(idx)
    sync = 1.0 - min(1.0, abs(offb - (0.1 + 0.4 * c)) / 0.5)
    figc = 1.0 - min(1.0, abs(FIGURE_C.get(fig, 0.4) - c) / 0.6) if fig not in ('single',) else 0.8
    names = sum(1 for k in range(len(words)) if _is_name(words, k))
    # shape: a line is a sentence or a setup + punch (1-2 phrases between full stops). A third stop, or a one- or
    # two-syllable fragment in mid-line ("Ugh.", "Claudia.", "Profoundly."), makes Suno stop and start (the director on a verse,
    # 2026-09-29: "the most awkward part"; V1 and V3, which he loves, are almost all 1-2 phrase lines).
    ph, cur = [], 0
    for s_ in syl:
        cur += 1
        if s_['bnd'] == 2: ph.append(cur); cur = 0
    if cur: ph.append(cur)
    shape = max(0.0, (1.0 if len(ph) <= 2 else 0.75 if len(ph) == 3 else 0.5) - 0.15 * sum(1 for x in ph[:-1] if x <= 2))
    k = (L - e) / (on[li] - on[0]) if on[li] > on[0] else 1.0
    return dict(text=text, n=n, bars=B, entry=e, last_at=L, grid=gname, fit=round(fit, 2), dens=round(dens, 2),
                rate=round(rate, 1), stretch=round(k, 2), shape=round(shape, 2), phrases=ph, rhythm=round(rhythm, 2), clash=clash, lapse=lapse, cad=round(cad, 2), sync=round(sync, 2),
                figure=fig, gaps=gaps, figc=round(figc, 2), names=names, rk=rhyme_key(words), tail=tail,
                last_word=re.sub(r"[^a-z']", '', words[-1]['txt'].lower()), caps=text.upper() == text and any(ch.isalpha() for ch in text),
                syl=syl, pos=pos, stress=''.join('S' if s['P'] >= 0.6 else 'w' for s in syl))


NEAR_V = [{'AE', 'EH'}, {'IH', 'IY'}, {'AH', 'AA', 'AO'}, {'UH', 'UW'}, {'EY', 'EH'}, {'OW', 'AO'}, {'AY', 'AA'}, {'ER', 'AH'}]


def _rhyme(a, b):
    """1 = same word (epistrophe) or perfect rhyme; .7 same vowel + same coda class; .6 assonance; .45 near vowel with the
    same tail (banger/better); .35 same coda (consonance); else 0."""
    if a['last_word'] and a['last_word'] == b['last_word']: return 1.0
    ka, kb = a['rk'].split(), b['rk'].split()
    if not ka or not kb: return 0.0
    if ka == kb: return 1.0
    va, vb = ka[0], kb[0]; ca, cb = ka[1:], kb[1:]
    nas, stop = {'M', 'N', 'NG'}, {'P', 'B', 'T', 'D', 'K', 'G'}
    cls = lambda c: 'nasal' if c and c[0] in nas else 'stop' if c and c[0] in stop else (c[0] if c else '')
    if va == vb: return 0.7 if cls(ca) == cls(cb) else 0.6
    near = any(va in g and vb in g for g in NEAR_V)
    if near and ca[-2:] == cb[-2:] and ca: return 0.45
    if ca and ca == cb: return 0.35
    return 0.0


def flow_section(lines, mode, c=None, header=''):
    c = COMPLEXITY[mode] if c is None else c
    L = [f for f in (flow_line(l, mode, c) for l in lines) if f]
    if not L: return None
    call = any(k in header.lower() for k in ('answer', 'response', 'call'))
    if call: L = [f for f in L if not f['caps']] or L                          # crowd answers ride in the lead's slot
    body = [f for f in L if f['n'] > 2]                                          # tags ride free
    def par(a, b):   # the second line echoes the first: similar length, same number of phrases
        return 0.5 * (1.0 - min(1.0, abs(a['n'] - b['n']) / 6)) + 0.5 * (1.0 if len(a['phrases']) == len(b['phrases']) else 0.0)
    def pair_score(ps): return sum(0.7 * _rhyme(a, b) + 0.3 * par(a, b) for a, b in ps) / len(ps)
    quads, rh = [body[i:i + 4] for i in range(0, len(body), 4)], []
    for q in quads:
        if len(q) == 4: rh.append(max(pair_score([(q[0], q[1]), (q[2], q[3])]), pair_score([(q[0], q[2]), (q[1], q[3])])))
        elif len(q) >= 2: rh.append(pair_score([(q[0], q[1])]))
    rhyme = sum(rh) / len(rh) if rh else 0.0
    mean = lambda k: sum(f[k] for f in L) / len(L)
    roll = sum(1 for a, b in zip(L, L[1:]) if a['names'] + b['names'] >= 3)       # 3+ names in two lines: a roll call
    wr = 0.15 if mode == 'spoken' else 0.10
    score = (0.28 * mean('fit') + 0.18 * mean('rhythm') + 0.14 * mean('dens') + 0.10 * mean('cad') + 0.10 * mean('shape') +
             wr * rhyme + 0.05 * mean('sync') + 0.05 * mean('figc')) / (0.90 + wr) - 0.04 * roll
    return dict(flow=round(100 * max(0.0, score)), c=c, fit=round(mean('fit'), 2), rhythm=round(mean('rhythm'), 2), shape=round(mean('shape'), 2),
                dens=round(mean('dens'), 2), cad=round(mean('cad'), 2), rhyme=round(rhyme, 2), sync=round(mean('sync'), 2),
                roll=roll, lines=L)


def flow_grid(f):
    """the line in its slot: one row per bar of 16 cells, | on each beat, CAPS = beat-bearing stress."""
    cells = {}
    for s, x in zip(f['syl'], f['pos']):
        t = int(round(x)); 
        while t in cells: t += 1
        cells[t] = s['txt'].upper() if s['P'] >= 0.6 else s['txt'].lower()
    rows = []
    for b0 in range(0, 16 * f['bars'], 16):
        rows.append('%d ' % (b0 // 16 + 1) + ''.join(('|' if t % 4 == 0 else ' ') + cells.get(t, '·')[:6].ljust(6) for t in range(b0, b0 + 16)))
    return rows


def flow_text(text, c=None):
    """flow per section -> [(section name, mode, flow_section result)]"""
    out = []
    for name, mode, bars, lines in parse(text):
        m = re.search(r'complexity\s*([0-9.]+)', name)
        f = flow_section(lines, mode, float(m.group(1)) if m else c, name)
        if f: out.append((name, mode, f))
    return out


def flow_report(secs, show_grid=False):
    out, tot = [], []
    for name, mode, f in secs:
        tot.append(f['flow'])
        out.append('\n== %s  [%s c=%.2f]  flow %d · fit %.2f · rhythm %.2f · shape %.2f · fills slot %.2f · cadence %.2f · couplets %.2f%s' % (
            name, mode, f['c'], f['flow'], f['fit'], f['rhythm'], f['shape'], f['dens'], f['cad'], f['rhyme'],
            ' · roll call x%d' % f['roll'] if f['roll'] else ''))
        for x in f['lines']:
            out.append('  fit %.2f rhy %.2f fill %.2f  %-2d %-8s %-9s %s%s' % (x['fit'], x['rhythm'], x['dens'], x['n'], x['figure'], x['grid'], x['text'],
                       ('   <- ' + ', '.join(flow_why(x, f['c']))) if flow_why(x, f['c']) else ''))
            if show_grid: out += ['        ' + r for r in flow_grid(x)]
    out.append('\nsong flow %d' % round(sum(tot) / max(len(tot), 1)))
    return '\n'.join(out)


def flow_why(x, c):
    why = []
    if x['shape'] < 0.9: why.append('stop-start (%s)' % '-'.join(map(str, x['phrases'])))
    if x['clash']: why.append('%d clash' % x['clash'])
    if x['lapse']: why.append('lapse')
    if x['dens'] < 0.6: why.append('%s (stretched x%.2f in %d bar%s)' % ('dragged' if x['stretch'] > 1.9 - 1.4 * c else 'rushed', x['stretch'], x['bars'], 's' if x['bars'] > 1 else ''))
    return why


def groove_text(text):
    """per section: mean line groove, syllables per line, and how even the lines are (the reference break: 7, 7, 7)."""
    out = []
    for name, mode, bars, lines in parse(text):
        rows = [(groove(l), len(analyse(l)[0]), l) for l in lines]
        rows = [r for r in rows if r[0]]
        if not rows: continue
        g = [r[0]['groove'] for r in rows]; n = [r[1] for r in rows]
        mean_n = sum(n) / len(n); sd = (sum((x - mean_n) ** 2 for x in n) / len(n)) ** 0.5
        out.append(dict(section=name, mode=mode, groove=round(sum(g) / len(g)), syllables=n,
                        evenness=round(100 * max(0.0, 1 - sd / max(mean_n, 1))),
                        lines=[dict(text=l, groove=gr['groove'], n=k, why=gr['why']) for gr, k, l in rows]))
    return out
