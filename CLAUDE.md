# Marknad Tent Planner — agent instructions

Site-layout planner for **Medeltidsveckan 2026** (Visby, Gotland). The organiser drags
market stalls onto a scaled overhead image, then plans the electrical and water
distribution on top of the same layout.

Single self-contained HTML file, no framework, no server. Leaflet + Google Identity
Services from CDN. (SheetJS was dropped when the in-app Excel import was removed.)

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
  "water": true,
  "stand": 0               // COUNT of organiser-rented marknadsstånd (the workbook's
                           // `stall_rental` column); >0 -> darker brown border
}
```

Source of truth: `Utplaceringsdokument` sheet, header row 2. Column map and the
extraction rules are documented at the top of `extract_tents.py` — read it
before touching the data pipeline.

Three non-obvious rules, all of which caused bugs already:

- **Colour lives in a cell fill**, not a value. Only openpyxl can read it — which is
  the reason the library is baked in at build time via `extract_tents.py` and there is
  no in-app Excel import.
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
The base map is the committed `marknad_base_clean.png` as an `L.imageOverlay` (loaded on
startup via `DEFAULT_IMG` / the Sheet's `meta.imageUrl`; there is no in-app upload).
`ppm` (pixels per metre) converts metres to image pixels and comes from the Sheet's
`meta.ppm` — the in-app two-click calibration was removed. **Nothing can be drawn to
scale until `ppm` is set**, so a Sheet with an empty `meta.ppm` renders tents at token
size.

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
editing a tent (or rebuilding the baked-in library) updates items already on the plan.
`applyEdits(x)` is the library-side equivalent. Use `refOf(t)` for anything placed —
never read `t.ref` directly.

---

## Electrical model (El tab)

The user has corrected this four times (most recently 2026-07, reversing the
220V=16A clamp; before that the single-phase-per-tent model). Get it right.

- A source or cabinet is rated **per phase**. A 63 A cabinet supplies 63 A on each of
  L1/L2/L3 — 189 A in total.
- **A 3-phase tent (`380v` 16 A/32 A/63 A/125 A) draws its rated amps on ALL THREE
  phases at once** — it counts against L1 AND L2 AND L3 of every node on its feed path
  (cable `phase` stays 0 = all). Only **220 V tents are single-phase**; `rebalanceEl`
  places each on the least-loaded phase along its whole feed path (LPT, on top of the
  3-phase base load). The earlier one-phase-per-tent model undercounted 3-phase loads
  and was rejected.
- **A 220 V tent counts its STATED amps** on its one phase (`tentAmp` goes through
  `tentReq`): `220v 6A` is 6 A, `220v 16A` is 16 A, a bare `220v` defaults to 6 A. The
  earlier clamp that counted every 220 V tent as 16 A overcounted the 6 A tents and was
  reversed by the user 2026-07. The socket is a 220 V schuko outlet either way.
- Cabinet→cabinet feeds carry the downstream cabinet's per-phase aggregate.
- Load bands per phase vs rating (`loadLevel`, replaced the earlier flat +3 A rule):
  **green** ≤100%; **amber** 100–130% (fine in practice — an MCB holds 113% of In
  indefinitely per IEC 60898, a gG fuse 125% per IEC 60269, and real coincident draw
  at a market is well under nameplate); **red** >130% (`OVER_RED`) — a busy hour can
  trip the cabinet's main breaker. Flagged, never blocked: red = red node text/dashed
  red cable, amber = amber text and the cable keeps its colour but goes dashed.

Sockets are counted separately from capacity. `outputs(n)` gives the physical
complement; default for a cabinet is 6× 220V (9 at ≥125 A) plus **three** outlets of
each three-phase rating ≤ its own. A cable only fits an outlet of its **exact** socket
type (CEE plugs are rating-specific) — when that type is exhausted the connection is
refused, **never** moved to a larger free outlet (the earlier fallback let a cabinet
with one 16 A outlet accept two 16 A cables via its 32 A outlet; the user rejected
that). Sources default to unlimited outlets (capacity-limited only) but can be given
explicit counts. The source/cabinet modal hides three-phase outlet rows above the
entered rating (live, `srcClampOuts`) and the save handler zeroes them — a unit never
has outlets bigger than its incoming feed.

Graph: `nodes[] = {id, domain:'el'|'water', kind:'source'|'elskap'|'brunn'|'handfat',
rating, lat, lng, unl?, outs?, color?}` and `cables[] = {src, dst, dstKind:'tent'|'node',
domain, otype, phase, color?}`. One input per node, one supply per tent, cycles rejected
(`createsCycle`).

### Cabinet designations (A1, A1N1 …)

Sources and cabinets carry **reference designations** in the Swedish central-marking
style (IEC 81346 / SEK Handbok 419): each source is `A1, A2 …` (creation order), each
cabinet is `N1, N2 …` within its parent (wiring order), and the full designation
concatenates the feed path — `A1N1N2` is cabinet 2 fed from cabinet 1 fed from source 1.
Source numbers are **global across the areas** (in `AREAS` order — `srcNumBase()`), so
designations are unique event-wide: with one source per area they read A1 (Marknad),
A2 (Arena), A3 (Camping). Other areas' source counts come from their local cache when
that area has unsaved edits, else the `sheetAll` snapshot (`areaSrcCount`) — so adding
a source to an earlier area shifts the later areas' numbers (derived names, by design).
They are **derived from the wiring by `elNames()`, never stored** — rewiring renames.
A cabinet with no path to a source shows `?`. Surfaced in four places: a name badge on
the map node (the **Names** toggle in the El toolbar, `LS.cabnames`, global like
`letters`); the El legend rows; the **Cabinets** sub-view of the El sidebar
(`Overview | Cabinets` seg → `renderElTree()`, a clickable distribution tree); and the
`elskap` placements column (below).

### Colours (both optional, both persisted)

- **Node middle fill** (`n.color`): the source/cabinet modal has a colour picker for the
  *middle* only — the **border stays the rating colour** (`ratingColor`, drawn as an inline
  `border-color`). `color` absent means *use the CSS default* (`#181b22` cabinet /
  `#0e2033` source); "Reset to default" clears it. Like `outs`, absent ≠ a stored value —
  `nodeFromRow`/`nodeToRow` keep the column blank when unset. **New cabinets** are created
  with `NEW_CAB_COLOR` (`#831100`, the dark red the user paints cabinets, e.g. A1N5N2)
  stored on the node — existing cabinets are untouched, and Reset on an existing cabinet
  still clears to the CSS default.
- **Wire colour** (`c.color`): default is the output's rating colour (`cableColor` →
  `otypeColor`: 32A orange, 16A yellow, 63A/125A red, 220V light blue; water blue). Every
  wire is drawn as two polylines — a black **casing** underneath for a clean outline, then
  the colour on top. Right-clicking a wire **with the Wire tool on** (admin) opens a small
  modal to recolour or remove it; "Use default" clears the override. Overload still wins
  visually (red dashed).

Editing a node is **double-click** → `openSrcModal`. `renderNode` must not rebuild the
marker's DOM on a plain select click — selection/highlight are class toggles applied to the
live element, and `setIcon` only fires when the cached `m._html` actually changes. Rebuilding
the element between the two clicks used to swallow the dblclick, so the node became
un-editable (same failure mode as the tent-drag bug above).

### Cable routing dots, curves and lengths

**All wire editing lives in wire mode** — with the Wire tool off, wire clicks are inert
(no surprise popups while browsing/highlighting). With the **Wire tool on**: clicking a
wire inserts a draggable **dot** at that spot (`c.pts`, ordered waypoints between source
and destination) — deferred ~280 ms so a **double-click on the wire** opens the
recolour/remove modal (`openCabModal`) instead of spawning dots (right-click does too).
On a dot: **double-click toggles sharp ↔ curve** (the fast path the user asked to keep)
and **right-click opens the dot modal** (`openDotModal` — Sharp bend / Curve / Koppling
(water) / Remove). A dot is **square = sharp bend** or **round = curve**. Curve runs are drawn as a Catmull-Rom
spline sampled between hard anchors (`pathFromAnchors`), so sharp corners and smooth
curves coexist on one wire. Dots are only rendered in wire mode (admin); the bent/curved
path always is. **Dragging a dot must never rebuild layers** — `liveUpdate` only
`setLatLngs`s the two polylines and moves the length label; the full redraw happens on
`dragend` (same rule as tent drag).

Every wire shows its **length in metres** at its midpoint (needs `ppm`; follows the
drawn path, curves included), toggleable via the **Lengths** buttons in the El and
Vatten toolbars (`LS.lengths`, one shared global state like `letters`). The El legend
totals cable metres **per socket type**; the Vatten legend totals pipe metres. Pure
helpers: `cableAnchors pathFromAnchors catmullRom pathPixLen pathMidpoint distToSeg
cableLenM ptsToStr ptsFromStr` — covered by the node harness pattern below.

## Water model (Vatten tab)

Deliberately simpler: brunn (source) → handfat or any item with `water:true`, drawn as
blue pipes. No capacity maths. Water-capable items show a blue ring.

Water pipes get the same blue bend/curve dots, plus a third kind: the gray **koppling**
— a junction dot (drawn a bit larger than the pipe, kind `'koppling'` in `nodes`) that
other pipes can branch FROM. Create one by Alt-clicking a pipe in wire mode, or via the
dot modal (click a blue dot → Koppling). The koppling is a real water
node referenced from the host cable's `pts` as `{k:'n',nid}` — its position lives on
the node, so dragging it bends the host pipe. It has no input cable: `inputOf()` falls
through to the host cable's `src` (cycle detection works through it). Wiring **into** a
koppling is refused; double-click converts it back to a bend dot (only when nothing
branches from it); deleting a pipe cascades through its kopplingar and their branches
(`removeCableCascade`).

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
- **Undo/redo**: Ctrl+Z / Ctrl+Shift+Z (also Ctrl+Y; Cmd on Mac), admin only, all tabs.
  Snapshot-based (`HIST`): `histMark()` fires from `savePlaced`/`saveNet`/`saveRemoved`/
  the list edits, coalesced on a 0 ms timer so one user action (which may save placements
  AND cables) is ONE entry; `histApply` restores through the same full-rebuild path a
  Sheet load uses and queues a normal sheet save. History is capped (60), never fires
  mid-drag (`pointerDown`), and **resets** on `applySheetState` and on area switch —
  undoing across a remote save or another area would silently clobber it. Stack
  semantics are covered by the same node-harness pattern as the row helpers.

### Product requirements the user has stated explicitly

- **No emoji anywhere.** Monochrome glyphs (`↺ ↻ ✕`) only. `build.py` warns.
- Footprints are always true-to-scale; the earlier fixed-size toggle was removed.
- Names are always drawn, even when unreadably small. Placement letters can be hidden
  via the **Letters** toggle; tent sizes (metres) show on the label under a **Sizes**
  toggle of the same kind (`LS.sizes`, global).
- Tent list sorts by colour with **red last**, then by `placering`, then name.

## Public view vs admin view

The app boots in a **public, map-only view** and is flipped to the full editing UI by
signing in. State lives in one boolean, `ADMIN` (persisted in `LS.admin`,
`mtvi_admin_v1`), and one function, `applyMode()`, which toggles `document.body`
between the `public` and `admin` classes.

- **Public (default, no login):** the sidebar (`#sidebar`) is hidden by `body.public`
  CSS; the map with the tents fills the window. The `#topbar` **stays** visible and
  now carries a public-only tab switcher (`#pubTabs`, hidden in admin where the
  sidebar tabs exist), so **public can view all three tabs**. El/Vatten are strictly
  read-only there: the El group's editing buttons (`.ela`, the `cabinet` label, Wire)
  are CSS-hidden leaving only the **Names** toggle, the whole Vatten group is hidden,
  node dragging / dblclick-edit / Delete-key removal are gated on `ADMIN`, and
  clicking a tent or cabinet in El only highlights the supply chain (`wireMode` is
  unreachable in public). `applyMode()` keeps the current tab and re-runs `setTab`'s
  wire/selection resets instead of forcing Placering. The topbar is anchored **top-right**
  (`right:10px`), not top-left, so it clears Leaflet's top-left zoom control. Auto-sync
  still runs read-only (startup pull + 15 s poll), so a shared link stays current.
  `<body>` ships
  with `class="public"` and an early inline `if(ADMIN) document.body.className='admin'`
  so a fresh viewer **never flashes the editing tools** (a persisted admin sees a brief
  public flash instead — the safe direction).
- **Admin (unlocked by sign-in):** the full UI. `enterAdmin()` / `exitAdminMode()` set
  the flag and call `applyMode()`. `applyMode()` keeps the current tab (public views
  all three) and defers `map.invalidateSize()` (the sidebar showing/hiding resizes the
  map).
- **The admin entry is deliberately "somewhat hidden":** a faint `⋮` corner button
  (`#adminBtn`, bottom-right of the map, opacity .3 → 1 on hover). It's written as the
  HTML entity `&#8942;` in the template so `build.py`'s emoji check never sees a raw
  glyph — **do not** paste a literal padlock/key/gear character; U+1F512, U+26BF and
  U+2699 all fall inside that regex's ranges and would warn. **Exit admin** is a button
  next to `#syncStatus` (only visible in admin, since the sidebar is hidden in public).
- **Every tent mutation is gated on `ADMIN`**, not just hidden by CSS: `tentClick`
  (early return), the polygon `mousedown` drag and `dblclick` edit, the token-mode
  marker's drag-enable and `dblclick`, and the rotate/delete `keydown`. Public viewers
  can pan/zoom but cannot select, move, rotate, edit, or delete anything.
- Admin mode is **UI only** — the real write gate is unchanged (Google Drive Editor
  sharing; see the sync section). Flipping to admin without a valid Editor token reveals
  the tools but writes still fail.

> **Public read needs an API key.** Anonymous read of the Sheet requires
> `SHEET_DEFAULTS.apiKey` to be set (a browser key restricted to the Pages origin + the
> Sheets API) **and** the Sheet shared "Anyone with the link → Viewer". A restricted key
> **is now filled in** (referrer-locked to `https://itz9am.github.io/*`, Sheets-API-only,
> so it is safe to commit), so a fresh/incognito browser can read the plan without
> signing in. The read path (`sheetBatchGet` / `autoLoadStartup` / `pollRemote`) uses the
> key whenever no token is present. If public read ever 403s, check the Sheet is still
> link-Viewer and the key's referrer/API restrictions still match the serving origin.

## Areas (Marknad / Arena)

Two independent plans — **Marknad** (the market) and **Arena** — selected by a `Marknad |
Arena` segmented toggle in its own box (`#areaBar`, top-right). Each area has its own tents,
wiring, scale (`ppm`), saved view and base image. `AREAS` holds the `{key,label,img,ppm?}`
for each; `area` is the active key (persisted in `LS.area`, global). The tools bar
(`#topbar`: Letters / El / Vatten) sits top-left, offset (`left:52px`) to clear Leaflet's
zoom control — the area toggle is deliberately a separate control from the Letters toggle.

- **The tent LIST is shared across areas.** `custom` (added objects) and `removed` are
  **global**, so the sidebar shows the same tents in both areas; each area just tracks its
  own placement coordinates. **A tent is placed once for the whole event** — `otherPlaced`
  holds ids placed in the *other* area(s) (read from their namespaced `LS.placed`), and
  `placedAnywhere(id)` gates the available list / counts / drop, so a vendor dropped on
  Marknad no longer shows as available on Arena. `refreshOtherPlaced()` runs inside
  `loadPlaced()`, so it refreshes on every area load/switch. `AREA_SCOPED` (the namespaced keys) is therefore placed, img, ppm, size,
  view, edits, nodes, cables, dirty — NOT custom/removed. `nsKey()` suffixes those with
  `::<area>` — **except** for `marknad`, which keeps the ORIGINAL key names, so pre-area data
  loads unchanged. `letters`, `admin`, `area`, `custom`, `removed` stay global. All
  `lsGet`/`lsSet` go through `nsKey`; only two direct `localStorage` writes were pointed at
  `nsKey` by hand (`setImage`, and the `LS.area` write which is intentionally un-namespaced).
- **Scale.** Marknad's `ppm` is now **baked into its `AREAS` entry** (`ppm:5.09`,
  `ppmFixed:true` — measured 2026-07: at a trial `5.71` a map distance reading 33 m was
  37 m in reality, so `5.71 × 33/37 = 5.09`; the older Sheet-tuned `4.3923` showed more
  room than the market really has). `fixedPpm()` makes a
  `ppmFixed` code constant win over BOTH the localStorage cache and the Sheet `meta` row
  at every seed/load site — without the lock a constant change is silently overridden by
  the synced meta on the next load. Re-tune = edit the `AREAS` entry, nothing to clear.
  Arena (`ppm:4.39` default) and Camping (`ppm:3.0` default, measured to `3.459` with the
  measure tool) stay un-locked: their Sheet `meta` still overrides the old way.
- **Switching** (`switchArea`) tears down the current render, cancels any pending autosave
  (the `dirty` flag persists per-area, so nothing is lost), flips `area`, reloads every
  per-area global from localStorage (`reloadAreaState`), swaps the base image (which restores
  that area's saved view), and re-renders, then pulls that area from the Sheet.
- **Both areas sync to the same Sheet, via a trailing `area` column** on every tab (blank ==
  `marknad`, so pre-area rows load unchanged — **no manual sheet change**, the columns
  already exist). `meta` is now **one row per area**. Read: `currentAreaObjs()` keeps only the
  active area's rows; `setSheetAll()` caches the full raw snapshot of ALL areas (persisted
  globally as `mtvi_sheetall_v1`). Write: `sheetData()` emits the active area's rows (with
  `area` appended) **plus `otherAreaRows()`** — the other areas' rows verbatim from the
  snapshot — so saving one area never wipes the other. `runAutoSave` seeds the snapshot
  (`loadSnapshot`) before its first write if needed, snapshots the row set *before* the
  awaits, and only clears `dirty`/updates `lastSavedAt` if `area` didn't flip mid-write.
  `pollRemote` reads the meta rows: if the **current** area's `savedAt` changed it reloads;
  if only **another** area changed it refreshes the snapshot (so the next save preserves it).
  - **Stale-snapshot caveat:** two browsers editing *different* areas concurrently can still
    clobber each other's area between polls (the writer re-emits the other area from a
    possibly-stale snapshot). Same "last write wins, silently" spirit as concurrent
    same-area edits; the 15 s poll narrows the window but doesn't close it.
- The base images are committed PNGs (`marknad_base_clean.png`, `arena_base.png`) and
  **both** are copied into `_site/` by `pages.yml`.

## Persistence

`localStorage`, keys prefixed `mtvi_` (see `const LS` at the top of the script), is the
per-session cache: placements, nodes, cables, image, ppm, view, edits, removed, custom,
and the `LS.dirty` sync flag each live under their own key. Bump the version
suffix when a shape changes. The base image is the committed PNG (kept in `localStorage`
as its URL after first load); it is **never** written to the Sheet
(only its hosted URL is — see below).

**The Google Sheet syncs automatically** (see the section below) — it is the portable,
shared unit of work. There are no Save/Load buttons and no local JSON file path.

---

## Google Sheets for saved state — the only save/load path (automatic sync)

Built, and **fully automatic — there are no Save/Load buttons**. Every change writes to
the shared Sheet on a debounce, and the plan is pulled from the Sheet on startup. The
only Sheet control left in the UI is the **Settings** button plus a small
`#syncStatus` indicator (`Synced` / `Saving…` / `Sign in to sync` / `Sync error`). The
module lives under the `/* automatic sync */` and `/* Google Sheets sync */` banners:

- `queueSheetSave()` — called from `savePlaced` / `saveNet`; debounced
  (2.5 s) and coalesced so a burst of edits is one write. Guarded by `SYNC.loading` so
  applying a load doesn't echo back a save. Never triggers an auth popup.
- `runAutoSave()` — silently refreshes the token (`getToken(false)`, `prompt:'none'`);
  if that can't happen it shows *Sign in to sync* and leaves the change pending. Writes
  `values:batchClear` + `values:batchUpdate`. Retries with backoff, capped.
- `autoLoadStartup()` — pulls the four tabs on startup / after sign-in, silently
  (API key or silent token, never a popup). **Unsynced local edits win**: if
  `LS.dirty` is set it pushes the local state instead of overwriting from the Sheet.
- `pollRemote()` / `remoteReload()` — live reload. Every 15 s (and on tab refocus) it
  reads only `meta!A2:G`; if `savedAt` differs from `GS.lastSavedAt` (someone else
  saved) it pulls the whole plan. `reloadBlocked()` suppresses it while the user has
  pending edits, is mid-drag (`pointerDown` — reloading would tear a layer out from
  under Leaflet's drag handler), or the tab is hidden. `applySheetState(…,keepView)`
  keeps the local pan/zoom and skips the image reflash when the URL is unchanged.
- pure row helpers (`rowsToObjects nodeFromRow nodeToRow cableFromRow cableToRow gnum
  gbool isBlank`) and the GIS token client (`getToken` / `ensureTokenClient`).

`LS.dirty` is a flag set on every queued save and cleared on a successful save/load;
it is what stops a stale startup load from clobbering edits made while offline.
**It is admin-only.** A public device cannot edit, so `queueSheetSave` no-ops when
`!ADMIN`, `autoLoadStartup` only honours dirty-wins in admin, and startup clears every
area's dirty flag on a public device. (Earlier, the one-time Camping/Arena seeds set
dirty unconditionally: a logged-out viewer then skipped the Sheet pull and queued a
save that could never run without a token — which also left `SYNC.pending` stuck,
killing `pollRemote` for the whole session, so the device froze on cached data.)
Config (spreadsheet id, OAuth client id, optional API key, base image URL) is
**hard-coded** in `SHEET_DEFAULTS` — there is no settings UI. The only Sheet control in
the app is the `#syncStatus` indicator, which doubles as the sign-in button (clicking it
runs the interactive consent — needed once, from a user gesture, before silent
auto-sync can take over). **Scope is deliberately narrow.**

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
placements  tentId | x | y | rot |
            name | placering | length | width | color | electricity | water | nya | shape
            (+ trailing area | elskap — see below)
nodes       id | domain | kind | rating | x | y | unl |
            out220 | out16 | out32 | out63 | out125 | color
cables      src | dst | dstKind | domain | otype | phase | color
            (+ trailing area | pts)
meta        ppm | imageUrl | viewX | viewY | viewZoom | savedAt | savedBy
```

`pts` (cable waypoints) is a trailing column AFTER `area`, for the same positional-
parsing reason as `elskap`. It is not JSON: a `;`-separated list of `x y b` (bend),
`x y c` (curve) or `n <nodeId>` (koppling junction — position lives on the node row).
Blank reads back as no waypoints (`ptsFromStr`). An old client's `A2:H` clear can leave
stale `I` cells behind; unlike `elskap` this column IS read back, so a save from a
still-open old tab can misalign waypoints onto the wrong cables — cosmetic only, fixed
by re-dragging, and gone once every tab runs the current build.

`elskap` is **write-only, informational**: the designation of the cabinet feeding that
tent (`A1N1`, blank = not connected, `?` = fed from a cabinet with no source), refreshed
on every save so the electricians can read hook-ups straight off the sheet. It is never
read back — the cables tab stays the source of truth. It is deliberately the **last**
column (after `area`), NOT next to `electricity`: rows are parsed positionally and other
areas' rows are re-emitted verbatim, so a mid-row insert would shift `water/nya/shape/
area` under any still-open tab running the previous version — the mechanism that once
leaked Arena rows into Marknad. As a trailing column, old and new clients coexist: old
ones ignore it (their `A2:N` clear leaves stale `O` cells, harmless for a write-only
column) and no read-time migration exists or is needed.

Custom objects (user-added items, not from the Excel library) live only in the app, so a
placed custom carries its full definition inline in cols `name…shape`; for library tents
those cols are blank and `tentId` resolves against the baked-in library as before. On load a
placed custom is rebuilt into the library (`customFromRow`) so `refOf()` finds it and it
returns to the list on delete. A custom is placed at most once (placing removes it from the
list), so one row per custom is enough — unplaced custom templates still stay local-only.

The same def cols also carry **edits to a placed library tent** (rename/resize/colour):
`placementRow` fills them whenever `edits[id]` is set (not just for customs), while an
**unedited** library tent still leaves them blank so re-importing the Excel library keeps
updating it live. A library tent is re-resolved from the library every render, so its
override can't ride on the placed `ref` — it travels through the local `edits` map:
`reconcileEdits(P)` (called from `applySheetState` before the items are built) rebuilds
`edits[id]` from the def cols of library-tent placements — **set** when present, **cleared**
when the author reverted (blank name). Custom placements are skipped there (handled by
`customFromRow`). Only **placed** library edits sync (edits to unplaced tents stay local, by
design). **`mSave` calls `queueSheetSave()`** so an edit pushes immediately — without it the
change only touched `localStorage` and never re-synced until the next placement move.

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
- Last write wins, **silently** — auto-save no longer runs the interactive
  "overwrite?" confirm (it can't block on every keystroke). `meta.savedAt`/`savedBy`
  and `GS.lastSavedAt` are still written/tracked, so a concurrency check can be
  reinstated, but two admins editing the same Sheet at once will clobber each other.
- Sheets API quotas are ~300 req/min per project, 60/min per user; the 2.5 s debounce
  plus coalescing keeps a burst of edits to one `batchClear`+`batchUpdate` pair, and the
  15 s live-reload poll is a single small `meta` read (~4/min). View (pan/zoom) changes
  deliberately do **not** trigger a save — the current view is captured on the next real
  edit — so idle panning doesn't burn quota.

---

## Working style the user expects

- They test in a real browser and report symptoms plainly ("it's laggy", "connecting
  cabinets doesn't work"). Treat these as reproducible bugs and find the mechanism —
  every such report so far had a specific technical cause, not a misunderstanding.
- They know the domain (markets, Swedish market electrics) far better than you. When
  they say the model is wrong, it is wrong; implement what they describe.
- Keep answers short and concrete. State what changed and any caveat that affects
  their plan. No preamble.
