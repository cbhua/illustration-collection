# fonts/

Open-source fonts used only by `ogkit`'s Linux preview renderer so that previews look
like OmniGraffle on macOS.  They are **not** needed on the Mac (OmniGraffle uses the
fonts installed there).

| File | Font | Source | License |
|---|---|---|---|
| `MapleMono-*.ttf` | Maple Mono v7.9 (Latin build of *Maple Mono NF CN*) | https://github.com/subframe7536/maple-font | SIL OFL 1.1 |
| `FiraCode-*.ttf`  | Fira Code 6.2 | https://github.com/tonsky/FiraCode | SIL OFL 1.1 |

`fonts.conf` adds this folder on top of the system fontconfig; `ogkit.fonts` points
`FONTCONFIG_FILE` at it automatically.  Latin Modern (LM Sans 10 / CMU Serif
equivalent) comes from TeX Live on the system.
