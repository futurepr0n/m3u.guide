# Jellyfin integration direction

This document records how m3u.guide should prepare its editable provider data
for native Jellyfin ingestion. The source M3U/XMLTV pair may contain live TV,
movies, and episodes together; that source is never itself the Jellyfin export.

The corresponding Jellyfin server investigation is in
`../../jellyfin/docs/m3u-guide-integration-plan.md` when both repositories are
checked out as siblings.

## Existing m3u.guide workflow

The current application already provides most of the authoring side:

- `tv.m3u` is the protected provider source.
- `tv_edited.m3u` is created as a working copy and is changed by the playlist
  editor.
- The editor lazily loads groups, lets users hide groups/channels, and writes the
  visible entries back to `tv_edited.m3u` in UI order.
- Analysis parses `tvg-id`, `tvg-name`, `tvg-logo`, `group-title`, name, and URL;
  correlates guide IDs; and separates URL shapes into live, movie, and series
  reports.
- Xtream ingestion can include live, VOD, and per-series episode data.
- The optimizer can write `cleaned.m3u8` and a trimmed `cleaned.xml`.
- Tokenized endpoints already publish source and edited M3U plus source XMLTV.

## Gaps in the current implementation

The current optimizer is not yet the same thing as “export my edited playlist
for Jellyfin”:

- `/optimize-playlist` reads immutable `tv.m3u`, not `tv_edited.m3u`.
- Inclusion is reconstructed from analysis `channel_ids`; it does not use the
  full saved group/channel visibility and ordering state.
- Analysis-derived IDs cover EPG-associated live channels, not a complete
  editable live/VOD catalog.
- `Group` and `Channel` database models define visibility and sort order, but the
  editor primarily reconstructs state from the M3U file rather than persisting a
  normalized catalog into those tables.
- Content kind is inferred repeatedly from URL/title patterns rather than stored
  as editable metadata.
- Movie/episode metadata is not rich enough for native Jellyfin library items.
- The writer can emit `tvh-chnum`; Jellyfin consumes `tvg-chno`.
- Optimized artifacts are not available through the tokenized public route.
- Large analysis and editor code paths duplicate M3U parsing rules.

## Target model: Jellyfin export profile

A playlist can have one or more export profiles. A profile stores:

- name and enabled state;
- included content kinds: live, movies, series;
- visible group IDs and their order;
- per-entry visibility, order, rename, category override, and artwork override;
- EPG matching override and channel number;
- refresh/publication schedule;
- immutable stable m3u.guide IDs independent of title, URL, and `tvg-id`;
- last generated revision, counts, validation warnings, and artifact ETags.

Provider refresh updates the normalized source catalog. User overrides remain
separate, keyed by stable identity, and are re-applied. Export generation reads
the normalized catalog plus overrides; it must not scrape state back from an
HTML report.

## Export artifacts

Each Jellyfin profile should generate a revision atomically:

```text
exports/jellyfin/<profile>/
|-- live.m3u8
|-- epg.xml
|-- vod.json
|-- validation.json
`-- manifest.json
```

`live.m3u8` is a standard Jellyfin tuner playlist containing only selected live
entries. It preserves `tvg-id` for XMLTV matching and emits `tvg-name`,
`tvg-logo`, `group-title`, deterministic `tvg-chno`, and a namespaced stable
item ID.

`epg.xml` contains one channel declaration per used `tvg-id` and only the
relevant programmes. A live entry without guide data remains in the M3U; it is
reported as no-EPG rather than discarded.

`vod.json` contains selected movies and episodes with stable IDs, title, kind,
series/season/episode hierarchy, year, plot, genres/categories, artwork, runtime,
stream URL, provider IDs when known, and source revision. A Jellyfin importer
uses this to create native Movies, Series, Seasons, and Episodes with normal
navigation, metadata, resume, and watched state.

`validation.json` provides actionable diagnostics. `manifest.json` identifies
the revision and artifact URLs/checksums/ETags for a Jellyfin plugin or scheduled
sync.

## Editing and quality-of-life scope

The profile editor should build on the existing UI and add:

- editable content kind with confidence/reason from automatic classification;
- rename and category/group reassignment;
- drag ordering for groups and entries;
- multi-select/bulk hide, move, rename-prefix cleanup, and categorization;
- EPG match search/override and duplicate/shared-ID indication;
- series-title, season, and episode correction;
- movie/series artwork and metadata overrides;
- “preview as Jellyfin” sections for Live TV, Movies, and Shows;
- validation filters for missing IDs, no programmes, duplicate stream URLs,
  missing artwork, malformed season/episode names, and unsupported schemes;
- diff preview before publishing after a provider refresh;
- retained overrides when provider URLs or display names change.

## Native Jellyfin responsibilities

m3u.guide owns source acquisition, classification, authoring, and export.
Jellyfin owns playback and native presentation:

- Live TV tuner/guide ingestion from `live.m3u8` and `epg.xml`.
- Server persistence/API support for M3U group/category and source ordering.
- jellyfin-web grouping, filtering, searching, and administrative editing where
  server-side changes should feed back to the m3u.guide profile.
- VOD import into native library item types, initially through a plugin unless
  public APIs prove insufficient.

Edits made in Jellyfin need an explicit ownership rule. The recommended model is
that m3u.guide remains authoritative and Jellyfin either deep-links to its editor
or sends supported override changes back through an authenticated m3u.guide API.
Otherwise a refresh would overwrite Jellyfin-only edits.

## Implementation slices

1. Refactor one shared streaming M3U parser/classifier used by analysis, editor,
   refresh, and export. Add the retained private feed as a non-CI scale fixture.
2. Normalize groups/items and persist stable identities plus user overrides.
3. Add a Jellyfin export profile and generate `live.m3u8`, trimmed `epg.xml`,
   validation, and manifest from edited state.
4. Publish artifacts through tokenized endpoints and add a Jellyfin setup panel
   with copyable tuner/guide URLs.
5. Add contract tests that parse the generated pair with Jellyfin's actual M3U
   and XMLTV code.
6. Persist/expose channel grouping in Jellyfin and implement client navigation.
7. Define `vod.json`, prototype the importer plugin, and validate native movie and
   series behavior at production scale.

## Development prototype status

The first local prototype is implemented on branch
`dev/m3u-guide-jellyfin-integration`:

- `jellyfin_export.py` streams the saved edited M3U (falling back to the source
  for an initial preview), recognizes direct and proxied Xtream content paths,
  and emits a live-only Jellyfin M3U.
- The output preserves edited names/groups/order, adds sequential `tvg-chno`,
  and includes a provisional URL-derived `x-m3uguide-id`.
- XMLTV is streamed, filtered to the live IDs, case-normalized to the M3U IDs,
  and duplicate channel declarations are removed.
- `validation.json` and `manifest.json` report counts, warnings, hashes, sizes,
  and public artifact URLs.
- The playlist card exposes a **Jellyfin Export** action and copy buttons for the
  generated JF M3U and JF EPG URLs.
- Tokenized routes serve the generated artifacts.

The retained StreamvisionTV fixture generated the prototype artifacts in about
6.7 seconds on the development workstation:

| Result | Count/size |
| --- | ---: |
| Source entries | 346,968 |
| Exported live entries | 17,405 |
| Excluded movie entries | 36,632 |
| Excluded series entries | 292,931 |
| Live output | 7,218,872 bytes |
| Trimmed XMLTV output | 14,115,923 bytes |
| Exported XMLTV channels | 958 |
| Exported programmes | 46,597 |
| Duplicate XMLTV declarations removed | 1,355 |

This is deliberately a contract prototype, not the final normalized profile
model. In particular, URL-derived IDs must be replaced by persisted stable IDs,
content-kind overrides are not yet exposed in the editor, and `vod.json` is not
yet generated.

### Verified Jellyfin categorization behavior

The generated pair was loaded into an isolated Jellyfin server. Jellyfin
materialized all 17,405 live entries, preserved the generated channel numbers,
and retained artwork. The companion Jellyfin development branch now maps
`group-title` to persisted, searchable channel tags and exposes a `Tags` query
on `/LiveTv/Channels`.

The StreamvisionTV source uses hierarchical group labels such as
`CA| NEWS EN`. Jellyfin also uses `|` internally as an array delimiter, so the
native parser normalizes both `|` and `,` into distinct trimmed tags. Verified
queries returned 72 `4K`, 1,035 `CA`, and 31 `NEWS EN` channels. This provides
useful country/category facets without changing the standard M3U contract.

For future export profiles, model these facets explicitly rather than relying
forever on punctuation. A profile should be able to emit a primary display
group plus multiple labels (country, language, content category, quality, and
provider). Standard clients can receive a flattened `group-title`; the enhanced
Jellyfin path can consume the labels as tags or a future namespaced field.

Channel genres are intentionally not synthesized from every group label. Values
such as `CA` and `4K` are navigation facets, not genres, while XMLTV programme
categories already populate programme genres. Add a separate editable content
genre field/profile mapping if genre-based client compatibility is required.

The source StreamvisionTV XMLTV has no `<category>` elements. The Jellyfin export
therefore enriches each retained programme with the edited channel's raw group
facets and inferred canonical categories: `Movie`, `Sports`, `Kids`, and `News`.
Raw facets populate programme genres; canonical categories activate Jellyfin's
existing Programs rows and boolean filters. The export reports the number of
category elements added (`132,488` for the retained fixture).

Category inference is a compatibility fallback. The normalized editor/profile
model should expose explicit, user-editable content classifications and show the
inferred reason before publication. Geographic and quality facets remain useful
genres/labels but do not themselves set Jellyfin's four special programme flags.

The Jellyfin XMLTV dashboard should be configured with only the canonical
categories emitted by the profile: `Movie`, `Kids`, `News`, and `Sports`.
Broad defaults such as `documentary` must not be placed in News Categories:
Jellyfin applies those rules to programmes and will otherwise classify every
documentary as news. Canadian sports-provider groups (including TSN, Sportsnet,
DAZN, Fubo, CFL, WHL, Victory+, soccer, and sports PPV groups) are explicitly
mapped to `Sports`; `CA| KIDS *`, `CA| NEWS *`, and `CA| CINEMA *` map to their
corresponding canonical categories.

## Native VOD library prototype

`jellyfin_vod_export.py` proves the separate-library approach using standard
Jellyfin `.strm` and NFO artifacts. The bounded retained-feed fixture exports 25
movies from `EN - NEW RELEASE` and three parsed shows/24 episodes from
`NETFLIX  SERIES`. Jellyfin scanned the artifacts as exactly 25 `Movie`, three
`Series`, and 24 `Episode` objects in dedicated Movies and Shows libraries; none
became Live TV channels or DVR recordings.

PlaybackInfo for a test movie resolved the `.strm` to the protected HTTPS
m3u.guide proxy, detected an MKV container, and reported both direct-play and
transcoding support. A direct FFprobe verified H.264 1920x804 video, AAC stereo,
and a duration of 8,425 seconds. This establishes functional remote VOD playback
through the native Jellyfin library model.

The exporter now repairs the observed double-marker form where a truncated
series name precedes one `SxxExx` marker and the provider repeats the complete
name before a second marker. Every exported episode is recorded in
`parse-report.json` with the source title, parsed hierarchy, and parse reason.
For ambiguous provider naming, pass a JSON override file containing stable
aliases, for example:

```json
{
  "series_aliases": {
    "and Boogaloo (2026) (CO)": "Salcedo (2026) (CO)"
  }
}
```

The generated `vod-fixture.zip` contains `Movies/`, `Shows/`, their `.strm` and
NFO sidecars, and the parse report. A Jellyfin library cannot read this ZIP
directly; deploy it as follows:

1. Download the package from the token-protected m3u.guide artifact URL and
   extract it to persistent storage on the Jellyfin host.
2. For a native install, use paths such as
   `D:\Jellyfin\m3u-guide-vod\Movies` and `...\Shows` on Windows, or
   `/srv/jellyfin/m3u-guide-vod/{Movies,Shows}` on Linux.
3. For Docker, bind-mount the extracted root read-only, for example host
   `/srv/jellyfin/m3u-guide-vod` to container `/media/m3u-guide-vod:ro`.
   Jellyfin must be configured with the *container* path.
4. In Dashboard > Libraries, add a Movies library pointed at its `Movies`
   folder and a Shows library pointed at `Shows`. Enable local NFO metadata.
5. Scan both libraries. Subsequent exports should retain the same folder and
   filename for unchanged provider IDs so watched state remains associated.

Do not copy the original M3U into a media library. The `.strm` files are the
small pointer files Jellyfin scans; their URLs must be reachable from the
production Jellyfin host. Treat the package URL and its embedded stream URLs as
credentials.

Sports classification deliberately does not equate every `PPV` label with
sports: movie and subscription providers also use it. The canonical `Sports`
category includes explicit UFC, boxing, MMA, Matchroom, Triller, Fight Pass,
WWE/AEW, ESPN+ PPV, sports PPV, and PPV Event terms, in addition to the Canadian
DAZN/Fubo/CFL/WHL/Sportsnet/TSN/Victory+ mappings. XMLTV programmes receive the
canonical category; channels retain their source group as tags.

Run locally with:

```powershell
.\.venv\Scripts\python.exe -m unittest test_jellyfin_export.py -v
.\.venv\Scripts\python.exe app.py
```

## Retained investigation data

## Jellyfin plugin API

The separate `Jellyfin.Plugin.M3uGuide` integration does not require users to
copy the permanent stream token. Its configuration page submits username and
password once to `POST /api/jellyfin/auth`. m3u.guide returns a dedicated,
revocable integration token; only its SHA-256 digest is retained in the
m3u.guide database, while Jellyfin stores the raw token for scheduled syncs.
The password is never persisted by the plugin.

The Bearer-authenticated API includes account/playlist discovery, server-side
export generation, artifact downloads, and token revocation. These routes and
the automatically created `integration_token` database table must be deployed
before the plugin can connect to production. Production must terminate TLS at
the application or reverse proxy and should rate-limit credential exchange.

For pre-production testing, `dev_seed_jellyfin.py` creates the disposable
`jellyfin-dev` account and registers the retained `StreamvisionTV` fixture.
The plugin permits `http://127.0.0.1` and `http://localhost` only; HTTP URLs for
LAN or public hosts remain rejected. The local Flask development port is 4444.

The local m3u.guide server also publishes a Jellyfin repository manifest and
versioned plugin ZIP under `/static/plugin-repository/`. This lets Jellyfin Web
correlate the installed assembly with package metadata; a manually copied DLL
without a matching repository entry otherwise displays a repository-details
warning. Production must publish the equivalent manifest, packages, and
checksums over HTTPS.

After artifact synchronization, the plugin creates or updates one named M3U
tuner, one XMLTV provider scoped to that tuner, and native `m3u.guide Movies`
and `m3u.guide Shows` libraries. Saved tuner/provider IDs make synchronization
idempotent, with exact-name/path fallback for restored plugin configurations.

## Production VOD catalog

The bounded ZIP remains only as a legacy development artifact. Production VOD
uses `jellyfin_profiles.json`, `vod.manifest.json`, and a streamed
`vod.catalog.jsonl`. Profiles select exact movie/series groups and may set
staged rollout limits; omitted limits export the complete selected catalog.

The authenticated paginated endpoint accepts a byte cursor and returns at most
1,000 projection instructions. Records contain stable IDs, safe relative
paths, NFO XML, and the user's protected source/proxy URL. m3u.guide does not
download or host the media. The plugin writes into a staging tree, rejects path
traversal, and atomically replaces only its plugin-owned VOD root after every
page succeeds. This makes an interrupted synchronization non-destructive and
removes items absent from a completed revision without touching unrelated
Jellyfin libraries.

The supplied private source files are retained locally at:

```text
testdata/private/StreamvisionTV/tv.m3u
testdata/private/StreamvisionTV/epg.xml
```

They are ignored by the repository's `*.m3u` and `*.xml` rules and must never be
committed, uploaded as CI artifacts, logged, or included in public bug reports.
Use sanitized, minimal derived fixtures for committed unit and contract tests.
