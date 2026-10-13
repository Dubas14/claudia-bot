# Lyrics: the two files

| File | What it holds | Who reads it |
|---|---|---|
| `lyrics.txt` | the words **as sung**, one lyric line per line | the aligner (`slop analyze`), `slop lyrics lint`, the lyric gate |
| `display.txt` | each line **as it should read** on screen, as tokens | `slop lyrics display` -> the engine's on-screen lyrics |

Both files ignore blank lines and any line that starts with `[` (section tags such as `[Verse 1]`,
`[Chorus]`, `[Bridge: spoken]`, and notes). Line N of `display.txt` is the on-screen version of line N of
`lyrics.txt`, counting only the lines that are not ignored.

## lyrics.txt - as sung

- One line of the song per line, in sung order. Repeat a chorus every time it is sung (never "x2" or "repeat").
- Spell everything the way it is **sung**: numbers, symbols and abbreviations become words.

  | On screen | In lyrics.txt |
  |---|---|
  | `+25%` | `plus twenty five percent` |
  | `AGI` | `A G I` |
  | `2026` | `twenty twenty six` |
  | `$4.99` | `four ninety nine` |

- Ad-libs: include them only if they should appear as lyrics.
- Section tags in brackets help the storyboard and `slop lyrics lint` (a tag with "sung", "chorus" or "hook" means
  sung delivery; "chant", "shout" or "drop" means chant; anything else is spoken).
- Once the song is locked, the line numbers are fixed: `analysis/words.json`, `display.txt` and the storyboard
  key on them. Fix a word in place; never insert or delete lines after analysis without re-running `slop analyze`.

Example:

```
[Verse 1]
ladies gentlemen agents
we shipped it plus twenty five percent
```

## display.txt - as read

Tokens are separated by spaces. Each token appears at the aligned time of the sung word(s) it covers.

| Token | Covers | Example |
|---|---|---|
| `word` | 1 sung word (the default for a token with a letter or digit) | `Ladies.` |
| `TEXT\|n` | n sung words | `+25%\|4` for "plus twenty five percent"; `AGI\|3` for "A G I" |
| `TEXT\|0` | no sung word; shown with the next token | `->\|0` |
| a token with no letter or digit | defaults to `\|0` | `=` |

Styles wrap the token text: `~strike~`, `*accent*`, `_mono_` (for example `~human~ *agentic*`).

A display line must cover **exactly** the sung words of its `lyrics.txt` line, or the lyric gate fails.
Start the file from the sheet after `slop analyze` (`slop lyrics display --init --force` writes one line per sung
line and joins spaced capitals: `A G I` -> `AGI|3`), edit the lines that should read differently, then check with
`slop lyrics display`.

Example (matches the lyrics.txt example):

```
[Verse 1]
Ladies. Gentlemen. *Agents.*
We shipped it +25%|4
```
