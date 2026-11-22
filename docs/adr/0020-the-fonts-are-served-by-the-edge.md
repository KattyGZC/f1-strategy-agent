# 0020. The fonts are served by the edge

- Status: Accepted
- Date: 2026-11-20

## Context

The screens are set in Titillium Web and JetBrains Mono (`App.css`). `index.html` loaded them from Google Fonts: a stylesheet from `fonts.googleapis.com` and font files from `fonts.gstatic.com`. The content security policy of ADR 0016 is `default-src 'self'`, with no `style-src` or `font-src`, so the browser blocks both, and every screen fell back to `system-ui` and `ui-monospace`.

Vite's build also inlines any asset under 4 KB as a `data:` URI (`build.assetsInlineLimit`). The policy blocks those too: six small font subsets were refused once the fonts came from the build (2026-11-20, in Edge).

## Options

1. **Open the policy to Google Fonts** (`style-src` and `font-src` for the two hosts). No build change; a third party serves styles to the page, and every visit sends the visitor's address to it.
2. **System fonts only.** Nothing to load; the screens lose the type they were designed with.
3. **The fonts in the build.** The `@fontsource` packages (OFL-1.1) put the weights in use under `/assets/`, served by nginx under `'self'`; nothing inlined.

## Decision

Option 3. `main.tsx` imports the weights `App.css` uses (Titillium Web 400, 600, 700 and 900; JetBrains Mono 500 and 700), and `vite.config.ts` sets `assetsInlineLimit: 0`. The policy of ADR 0016 does not change.

## Consequences

- No request leaves the origin to draw a screen.
- Each weight ships one file per subset (Titillium Web: latin and latin-ext; JetBrains Mono also cyrillic, cyrillic-ext, greek and vietnamese), as woff2 with a woff fallback: 40 files in the build. Their `unicode-range` makes the browser fetch only the woff2 of the subsets a page uses: on today's screens, the latin ones, about 12 to 22 KB each.
- The font files are hashed assets, kept for a year like the scripts (ADR 0019).
- A new weight in `App.css` needs its import in `main.tsx`; without it the browser synthesizes the weight from the nearest one.
- No asset is ever inlined, images included, since the policy allows no `data:` URI.
- `make edge-check` asserts that `index.html` names no other origin, that the styles inline nothing and load nothing from another origin, and that a font from the build is served with its type and caching.
