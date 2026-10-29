# Analytics

How AutoPublisher reads, stores and shows the metrics of the posts it published
(Feature 027). Everything uses official APIs and the permissions AutoPublisher already
requests: there is no scraping, no unofficial API and no new scope.

The short version:

- metrics are shown with their **original names**, exactly as each platform returns them;
- a metric the platform did not return is **"Not available"**, never `0` (a real `0` is shown
  as `0`);
- metrics are **never added up, averaged, ranked or compared across platforms**;
- every reading is a real snapshot: nothing is interpolated, filled or predicted.

## What each platform can show

The **Analytics** page of a project starts with one row per account and its capability. It is
computed from local data only (the connection row and the permissions a `connected`
connection guarantees), with no network call.

| Platform | Capability | Why |
|---|---|---|
| YouTube | **Metrics available** | `videos.list` (`part=statistics`) with the granted `youtube.readonly` scope. |
| Instagram | **Metrics available** (public counters) · Insights: **permission needed** | `like_count` and `comments_count` with `instagram_business_basic`. Views, reach, shares, saves and interactions need `instagram_business_manage_insights`, which AutoPublisher does not request in this version. |
| Threads | **Permission needed** | Threads has no counters without `threads_manage_insights`, which is not requested. |
| TikTok | **Not supported yet** | Reading a video needs the `video.list` scope (not requested), and inbox uploads have no public post id. |
| Telegram | **Not supported yet** | Its MTProto API offers view counts, but there is no metrics adapter in this version. |
| X | **Not applicable** | AutoPublisher does not publish to X. |

An account that is not connected shows **Not connected**; one whose connection needs repair
shows **Reconnect needed** with a link to Accounts. Capability is also kept per metric group,
so Instagram shows both states at once.

## Which posts have metrics

Only **published** posts whose successful attempt recorded the platform's post id. The link is
never guessed from a title, caption, date or URL. A post without that link shows **why**
instead of metrics:

- the platform did not confirm the post id (`remote_identity_unavailable`);
- it was published by another account than the one connected now (`remote_identity_changed`);
- it was sent to the TikTok inbox, so there is no public post (`inbox_upload`);
- AutoPublisher has no remote id for it.

## Metrics and their definitions

| Platform | Metric | Common concept | Notes |
|---|---|---|---|
| YouTube | `viewCount` | Views | Since **2026-08-24** YouTube counts a view as soon as playback starts (autoplay and hover included), so an older video's total may span that change. AutoPublisher keeps the value as returned and never corrects it. |
| YouTube | `likeCount` | Likes | Omitted when the channel hides the like count. |
| YouTube | `commentCount` | Comments | Omitted when comments are disabled. |
| YouTube | `dislikeCount` | — | Only returned to the channel owner; listed only when returned. |
| Instagram | `like_count` | Likes | Omitted when the owner hides like counts. |
| Instagram | `comments_count` | Comments | |

YouTube `favoriteCount` is ignored on purpose: it was deprecated in 2015 and is always 0.

### Aligning is not comparing

Common concepts exist only to **line up** metrics visually. Only `likes` and `comments` can be
aligned; `views` and `shares` never are, because every platform counts them differently. An
aligned row keeps each platform's original name and definition, and carries the note "Not
quantitatively equivalent across platforms". No view sums, averages, subtracts, orders or
highlights values of different platforms.

### Engagement

Engagement is calculated by AutoPublisher when it is shown (it is never stored), with one
fixed formula per platform and only within that platform. In this version only YouTube has
one:

```text
(likeCount + commentCount) / viewCount
```

It is **Not available** when any component is missing in that reading or `viewCount` is 0.
The UI shows the formula and the component values. Instagram has no engagement in this
version (no views without insights).

## Refreshing

Reading metrics never blocks or delays publishing. A background refresher (separate from the
publishing scheduler) runs every 5 minutes, or right away after a manual request.

- **Automatic**: posts published in the last **90 days**, at most **once every 24 hours**
  each, whatever the outcome.
- **Manual**: **Refresh** on a post, or **Refresh project**; any age. A post read less than
  **15 minutes** ago is not queued again ("Updated recently", with the time it is available).
- **Publishing first**: no reading starts while an upload is running or an armed publication
  is due in the next 10 minutes (or inside its overdue window); queued requests wait.
- **YouTube quota**: analytics uses at most **200 units per Pacific day** of YouTube's general
  quota bucket (`videos.list` is 1 unit for up to 50 videos). It never uses the separate
  `videos.insert` upload quota.
- **Failures** keep the **last valid reading** next to the problem: *Out of date* (retried
  with a backoff from 1 h up to 24 h), *Paused by the platform* (rate limit; a YouTube daily
  quota waits for the Pacific midnight reset), *Reconnect needed*, *Permission needed*.
- **Deleted posts**: a first absence shows *Not found yet*; only a second absence at least
  1 hour later marks the post *Deleted on the platform*.
- **Pause automation** does not stop analytics.

## Views

- **Published posts**: every post, newest first, with its metrics, age, last valid update,
  state and refresh.
- **Ranking**: choose one account, a metric of its platform and optionally a publication
  period. Posts are ranked by that metric only, using each post's latest valid reading. Posts
  without it are listed apart under **Not ranked** (never as 0). Ties keep the newest
  publication first. A ranking always stays within one platform; the API rejects one without
  a platform (`422 ranking_requires_single_platform`).
- **By content type**: for the chosen account, the median of each metric per image, video and
  text, over the posts that have that metric (a real 0 counts). Below 3 posts it reads
  **Insufficient sample** instead of a median. The median age is shown as context; nothing is
  normalized by age.
- **Media side by side**: one media's publications (linked only by the media itself), with
  likes and comments aligned and every other metric inside its own publication. No totals,
  winners or differences.
- **Evolution**: a post's real readings over time. Dots are readings; a dashed line only
  links two consecutive readings that both have the metric and is not a measurement. A
  reading without the metric leaves a gap (never 0). A table lists every value with its exact
  time.

## Known limitations

- Instagram insights (views, reach, shares, saves) and every Threads metric need permissions
  AutoPublisher does not request in this version.
- TikTok and Telegram metrics are not read in this version.
- The YouTube 200-unit daily budget and the platform rate-limit pauses are kept in memory:
  a restart resets them (Google's own quota still applies).
- The refresher does not run a cycle at start-up: after a restart, the first automatic
  reading happens about 5 minutes later (a manual request wakes it at once).
- AutoPublisher must be running to read metrics, like it must be to publish.
- The posts list has no pagination; it is meant for hundreds of posts per project.

## API

See [contracts/analytics-api.md](../specs/027-analytics-performance/contracts/analytics-api.md):
`GET /api/analytics/catalog`, `GET /api/projects/{id}/analytics/accounts`,
`GET /api/projects/{id}/analytics/posts` (with `sort`/`order` for rankings),
`GET /api/projects/{id}/analytics/content-types`, `GET /api/contents/{id}/analytics`,
`GET /api/publications/{id}/analytics` (with `history` and `series`), and the refresh
requests `POST /api/publications/{id}/analytics/refresh` and
`POST /api/projects/{id}/analytics/refresh`.
