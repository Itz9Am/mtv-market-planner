# Marknad Tent Planner — agent instructions

Site-layout planner for **Medeltidsveckan 2026** (Visby, Gotland). The organiser drags
market stalls onto a scaled overhead image, then plans the electrical and water
distribution on top of the same layout.

Single self-contained HTML file, no framework, no server. Leaflet + SheetJS from CDN.

---

## Repo layout

Everything lives **flat in the repo root** — there are no `src/`, `data/`, `dist/`, or
`scripts/` directories.

```
planner.template.html          the app; contains the literal token __TENTS_JSON__
tents.json                     tent library extracted from the Excel workbook
extract_tents.py               xlsx  -> tents.json          (openpyxl)
build.py                       template + data -> marknad_tent_planner.html  (+ checks)
marknad_base_clean.png         the base plan image (published alongside the HTML)
.github/workflows/pages.yml    CI: build + publish to GitHub Pages
```

`marknad_tent_planner.html` is the **generated** artefact. It is **git-ignored, not
committed** — CI builds and publishes it (see *Deployment* below). Run `build.py`
locally to regenerate it when you want to open the app in a browser yourself.

**Always edit `planner.template.html`, never the generated `marknad_tent_planner.html`.**

```bash
python3 extract_tents.py Marknadsutstallare_2026-2.xlsx   # only when the sheet changes
python3 build.py                                          # after every edit
```

`build.py` runs `node --check` on the embedded script, warns on emoji, and warns on
duplicate tent ids. A build that prints warnings is a build that will misbehave.

---

## How to verify changes

There is no test suite and the app cannot be opened in this environment, so:

1. `python3 build.py` — must print `syntax OK` with no warnings.
2. For anything touching the electrical/water graph, **extract the pure functions and
   run them under node**. This has caught two real bugs that syntax checking missed
   (a `ReferenceError` from a deleted helper, and socket exhaustion). Pattern:
   pull `ratingType socketKey tentReq ampOf outputs complementMap usedOut freeCount
   pickOutput inputOf createsCycle nodeRatingAmp phaseLoads peakLoad` out of the
   script with a regex, append a small harness with fake `nodes`/`cables`/`tentAmp`,
   and assert the outcome.
3. `grep` for identifiers you renamed. Several regressions came from replacing a
   function while a call site elsewhere still referenced the old name.

---

## Deployment (GitHub Pages)

The app is published by CI, not by committing HTML. `.github/workflows/pages.yml`
builds `planner.template.html` + `tents.json` into HTML and pushes it to the
**`gh-pages`** branch, which Pages serves. Both the built `index.html` and
`marknad_base_clean.png` are published together, so the app's default
`meta.imageUrl` (relative `marknad_base_clean.png`) resolves next to the page.

- **Push to `main`** → the live site at the repo root
  (`https://<owner>.github.io/<repo>/`), via `peaceiris/actions-gh-pages`
  (`keep_files: true`, so it never wipes the preview directory).
- **Pull request** → a preview at `…/pr-preview/pr-<N>/`, via
  `rossjrw/pr-preview-action`. The action comments the URL on the PR and
  **deletes the preview when the PR closes** (the workflow also listens to the
  `closed` event for that cleanup). This is how you try a change before merging.

All deploys share one `concurrency` group with `cancel-in-progress: false` so
parallel jobs never race on `gh-pages`.

Both the live site and every preview share the **same origin**
(`https://<owner>.github.io`), so a single **Authorized JavaScript origin** on the
OAuth client covers all of them — paths don't matter for OAuth, only scheme+host.

One-time setup outside the code: in repo **Settings → Pages**, set the source to
**Deploy from a branch → `gh-pages` / `root`**. Preview deploys need the workflow's
`contents: write` + `pull-requests: write` permissions (already declared).
`pull_request` runs from forks get a read-only token and cannot deploy a preview;
branch PRs within this repo (the normal flow here) work.

---

## Data model

`tents.json` is an array of "placeable items" (tents, but also organiser
structures and custom objects). 150 entries currently.

```jsonc
{
  "id": 1937,              // number from column A, or "x_oltalt" for id-less rows,
                           // or "1945-3" for one structure of a multi-structure vendor
  "name": "Vartan Rulle",
  "placering": "MAT",      // short letter code shown under the name
  "nya": 0,                // 1 = new vendor -> pink diagonal stripes
  "length": 20, "width": 6,// METRES, null when the sheet has no size
  "color": "#F9CB9C",      // from the column-A cell FILL = category
  "electricity": "380v 16A",
  "water": true
}
```

Source of truth: `Utplaceringsdokument` sheet, header row 2. Column map and the
extraction rules are documented at the top of `extract_tents.py` — read it
before touching the data pipeline.

Three non-obvious rules, all of which caused bugs already:

- **Colour lives in a cell fill**, not a value. Only openpyxl can read it; the
  browser-side importer (SheetJS) cannot, so re-importing in-app keeps colours only
  for ids already in the baked-in data.
- **The `tents` column can hold several structures.** Seven vendors do (Urda
  Hantverk has 6). They are expanded into separate entries `1945-1 … 1945-6` named
  `Urda Hantverk (1/6)`. Round structures are drawn as a square of the diameter —
  the user explicitly approved this.
- **~24 rows have no id** (Öltält, Medeltidsveckans Taverna, Baldakin ×2, Gute
  Rosteri ×3, Biljettkassa …). They get synthetic ids `x_<slug>`. Without this they
  collapse onto one null id and placing one marks them all as placed.

---

## App architecture

Leaflet with `L.CRS.Simple`; coordinates are **image pixels**, `lat = y`, `lng = x`.
The base map is a user-uploaded `L.imageOverlay`. `ppm` (pixels per metre) comes from
a two-click calibration and converts metres to image pixels. **Nothing can be drawn to
scale until `ppm` is set.**

### Rendering — this part is load-bearing

Tents are **`L.polygon` in map coordinates**, not HTML markers. An earlier version used
fixed-pixel `divIcon`s and the footprints visibly drifted and resized while zooming,
which made the tool useless for checking fit. Do not revert to pixel-sized icons for
the footprint.

Each placed item is two layers:

| layer | pane | z | purpose |
|---|---|---|---|
| `t.poly` | overlayPane | 400 | the footprint, true metres, rotatable |
| cables | `cables` | 610 | wiring, drawn **over** footprints |
| `t.label` | `tentlabels` | 620 | name + code, **fixed pixel size**, over cables |
| `t.nyaPoly` | overlayPane | 400 | pink stripe overlay for `nya` items |
| nodes | `nodes` | 630 | cabinets, sources, brunn, handfat |

Labels stay a constant size deliberately: scaling them with zoom makes them unreadable,
and the user asked that names always show even when the tent is tiny.

Dragging a polygon is **hand-rolled** (`attachPolyHandlers`): `mousedown` →
`map.dragging.disable()` → track `mousemove` → `mouseup`. Leaflet has no polygon drag.
Related past bug: selecting a tent used to rebuild its icon mid-drag, which tore the
element out from under Leaflet's drag handler and the tent stopped following the
cursor. Selection now only toggles style (`applySelStyles`) — **never re-create a
layer during a drag.**

The `nya` stripe pattern is an SVG `<pattern id="nyaPat">` in a **standalone hidden
`<svg>` appended to `document.body`** (`ensureDefs`). It used to live in Leaflet's own
SVG, which Leaflet rebuilds on pan/zoom, silently destroying the pattern.

### Live data linking

`refOf(t)` resolves a placed item against the **current** library by id, then applies
per-item edits, falling back to the stored snapshot if the id is gone. This means
editing a tent or re-importing the sheet updates items already on the plan.
`applyEdits(x)` is the library-side equivalent. Use `refOf(t)` for anything placed —
never read `t.ref` directly.

---

## Electrical model (El tab)

The user corrected this twice. Get it right.

- A source or cabinet is rated **per phase**. A 63 A cabinet supplies 63 A on each of
  L1/L2/L3 — 189 A in total.
- **Every tent is fed from a single phase.** On connect, the tent is assigned to the
  least-loaded phase (`phaseLoads`). So two 32 A tents on a 63 A cabinet land on L1 and
  L2 and are *not* overloaded, and three 125 A tents fit a 125 A cabinet. Do **not**
  model `380v` loads as drawing on all three phases; that was the earlier, rejected
  behaviour.
- Cabinet→cabinet feeds *do* spread over all three phases, since the downstream
  cabinet redistributes its own loads.
- Overload = any single phase above the rating. It is **flagged, not blocked** (red
  node, dashed red cable) so the user can see the problem while planning.

Sockets are counted separately from capacity. `outputs(n)` gives the physical
complement; default for a cabinet is 6× 220V (9 at ≥125 A) plus **three** outlets of
each three-phase rating ≤ its own. A tent takes the smallest free outlet ≥ its
requirement, falling back to a larger one. Sources default to unlimited outlets
(capacity-limited only) but can be given explicit counts.

Graph: `nodes[] = {id, domain:'el'|'water', kind:'source'|'elskap'|'brunn'|'handfat',
rating, lat, lng, unl?, outs?}` and `cables[] = {src, dst, dstKind:'tent'|'node',
domain, otype, phase}`. One input per node, one supply per tent, cycles rejected
(`createsCycle`).

## Water model (Vatten tab)

Deliberately simpler: brunn (source) → handfat or any item with `water:true`, drawn as
blue pipes. No capacity maths. Water-capable items show a blue ring.

---

## UI conventions

- Three tabs: **Placering** (place/move/rotate), **El**, **Vatten**.
- Placing/moving is only possible in Placering. El and Vatten are read-only for layout.
- Wiring requires the **Wire** tool to be toggled on; otherwise clicks select and
  highlight. Clicking a tent in El highlights its whole upstream supply chain in gold;
  clicking a cabinet highlights upstream plus its own tents.
- Each tent is placed **once** and leaves the list; deleting returns it.
- El and Vatten sidebars list **"Without power"** / **"Without water"** — placed items
  still needing a supply. Rows are clickable and pan to the item.

### Product requirements the user has stated explicitly

- **No emoji anywhere.** Monochrome glyphs (`↺ ↻ ✕`) only. `build.py` warns.
- Footprints are always true-to-scale; the earlier fixed-size toggle was removed.
- Names are always drawn, even when unreadably small. Placement letters can be hidden
  via the **Letters** toggle.
- Tent list sorts by colour with **red last**, then by `placering`, then name.

## Persistence

`localStorage`, keys prefixed `mtvi_` (see `const LS` at the top of the script), is the
per-session cache: placements, nodes, cables, image, ppm, view, edits, removed, custom,
and the Sheet config (`LS.sheetCfg`) each live under their own key. Bump the version
suffix when a shape changes. The base image is embedded as a data URL and downscaled to
2600 px on upload; it is kept in `localStorage` but is **never** written to the Sheet
(only its hosted URL is — see below).

**Save/Load is Google Sheets** (see the section below) — the portable, shared unit of
work. The old one-JSON-file path has been removed.

---

## Google Sheets for saved state — the only save/load path

Built. Save/Load go to a shared Google Sheet; **the old local JSON file path has been
removed** (there is no `saveProjBtn`/`loadProjBtn` any more). The module lives under
the `/* Google Sheets sync */` banner in the script — `doSheetSave` / `doSheetLoad`,
the pure row helpers (`rowsToObjects nodeFromRow nodeToRow cableFromRow cableToRow
gnum gbool isBlank`), and the GIS token client (`getToken` / `ensureTokenClient`).
Config (spreadsheet id, OAuth client id, optional API key, base image URL) lives in
`localStorage` under `LS.sheetCfg`, prefilled from `SHEET_DEFAULTS`, edited via the
**Settings** modal. **Scope is deliberately narrow.**

The spreadsheet stores **only what the application saves**: placements, power and
water networks, and a little metadata. It does **not** hold the tent library.

The tent library keeps its current pipeline unchanged: the private
*Marknadsutställare 2026* workbook is exported to xlsx and imported manually via
`extract_tents.py`. This is what lets category colours survive (they are cell
fills, readable only by openpyxl) and it means the sheet never touches the
sensitive columns. Do not add a `tents` tab and do not use `IMPORTRANGE`.

**Tabs** (created by hand — they already exist in the live sheet; all app-written,
flat rows):

```
placements  tentId | x | y | rot
nodes       id | domain | kind | rating | x | y | unl |
            out220 | out16 | out32 | out63 | out125
cables      src | dst | dstKind | domain | otype | phase
meta        ppm | imageUrl | viewX | viewY | viewZoom | savedAt | savedBy
```

`meta` is a **single data row** (`A2:G2`), not key/value pairs. That keeps every tab
the same shape — header row plus data rows — so one `rowsToObjects()` helper parses
all four, and the whole of `meta` is written atomically as one range in the batch write.
`view` is split into three numeric columns rather than JSON-in-a-cell so the sheet
stays readable when debugging by eye.

`nodes.outs` is likewise **flattened into five columns**, not JSON. The socket key set
is closed and hard-coded in two places (`outputs()` and the source/cabinet modal):
`220V, 16A, 32A, 63A, 125A`. No cell in this spreadsheet holds JSON.

> **Careful:** `outs === null` means *"use the default complement for this rating"* and
> is NOT the same as an object of zeros, which means *"this unit has no sockets"*.
> Empty cells load back as `null`; a literal `0` loads as `0`. Conflating them
> turns every default cabinet into one with no outlets and nothing will connect.
> `nodeFromRow` / `nodeToRow` enforce this and are covered by the node tests — extend
> those tests before touching the mapping.

Reads are one `values.batchGet` with `valueRenderOption=UNFORMATTED_VALUE` (so numbers
and booleans come back typed and trailing empty cells are omitted — that omission is
what makes empty-vs-zero detectable). Writes are a `values:batchClear` of the data rows
(`A2:` down, headers kept) followed by one `values:batchUpdate` for all four tabs; the
clear is what removes stale rows when the plan shrinks. `tentId` joins to the baked-in
library and is resolved through `refOf()`, which handles a missing id by falling back
to a snapshot; on Sheet load a missing id gets a minimal stub `ref`.

**Auth**, verified against current Google docs:

- An API key **cannot write** and **cannot be scoped to one spreadsheet**; it only
  reads sheets that are already link-public. Restrictions are HTTP-referrer/IP plus
  API-service only. Public read therefore = API key + "Anyone with the link → Viewer".
- Admin writes = **OAuth 2.0 client ID** (Google Identity Services token client,
  scopes `https://www.googleapis.com/auth/spreadsheets` plus `userinfo.email` so
  `savedBy` can be filled from the signed-in account). The client ID is public by
  design; real enforcement is Drive sharing — only accounts with **Editor** on the
  sheet can write. Prefer an **Internal** consent screen if the admins share a
  Workspace domain, to skip verification.
- The OAuth client is a **web** client; its **Authorized JavaScript origins** must
  list the origin the HTML is served from. `file://` has a null origin and will fail —
  the app has to be hosted (e.g. GitHub Pages). The client *secret* is unused; the
  browser token flow needs only the client id.

**Constraints to design around:**

- The base image cannot live in a cell. Host the PNG alongside the HTML and put its
  URL in `meta.imageUrl`, together with `meta.ppm` — without both, a fresh browser can
  load coordinates but cannot draw anything to scale. On save the URL written is
  `sheetCfg().imageUrl` (default `marknad_base_clean.png`), **not** whatever image is
  currently loaded — a data-URL upload is never pushed to the sheet.
- `tentId` must stay stable across re-imports. Numeric ids are safe; the synthetic
  `x_<slug>` ids for organiser structures change if a row is renamed.
- Last write wins. `doSheetSave` re-reads `meta.savedAt` before writing and warns if it
  changed since load (`GS.lastSavedAt`), otherwise two admins silently clobber each
  other.
- Sheets API quotas are ~300 req/min per project, 60/min per user; batch and cache.

---

## Working style the user expects

- They test in a real browser and report symptoms plainly ("it's laggy", "connecting
  cabinets doesn't work"). Treat these as reproducible bugs and find the mechanism —
  every such report so far had a specific technical cause, not a misunderstanding.
- They know the domain (markets, Swedish market electrics) far better than you. When
  they say the model is wrong, it is wrong; implement what they describe.
- Keep answers short and concrete. State what changed and any caveat that affects
  their plan. No preamble.
