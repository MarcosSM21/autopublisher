import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import type { Publication } from "../../types.ts";
import { MEDIA_XL_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { accountName, publicationTitle } from "../../utils.ts";
import {
  addWeeks,
  dayKey,
  formatRange,
  isToday,
  mondayOf,
  parseWeek,
  postsByDay,
  timeZoneLabel,
  type CalendarDay,
} from "./calendar.ts";

interface CalendarViewProps {
  posts: Publication[];
  rowPath: (post: Publication) => string;
  selectedId: number | null;
}

function time(date: Date): string {
  return date.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function Day({
  day,
  rowPath,
  selectedId,
  compact,
}: {
  day: CalendarDay;
  rowPath: (post: Publication) => string;
  selectedId: number | null;
  compact: boolean;
}) {
  const label = day.date.toLocaleDateString(undefined, {
    weekday: compact ? "short" : "long",
    day: "numeric",
    month: "short",
  });
  const headingId = `calendar-day-${day.key}`;
  return (
    <section
      className={
        isToday(day.date)
          ? "ap-calendar-day ap-calendar-day--today"
          : "ap-calendar-day"
      }
      aria-labelledby={headingId}
    >
      <h3 id={headingId} className="ap-calendar-day__title">
        {label}
        {isToday(day.date) && <span className="ap-meta"> · Today</span>}
      </h3>
      {day.posts.length === 0 ? (
        compact ? null : (
          <p className="ap-meta">Nothing this day.</p>
        )
      ) : (
        <ul className="ap-calendar-day__posts">
          {day.posts.map(({ post, at }) => (
            <li key={post.id}>
              <Link
                to={rowPath(post)}
                className="ap-calendar-item"
                data-detail-id={post.id}
                aria-current={post.id === selectedId ? "true" : undefined}
              >
                <span className="ap-calendar-item__time">{time(at)}</span>
                <span className="ap-calendar-item__title">
                  {publicationTitle(post)}
                </span>
                <span className="ap-meta ap-calendar-item__account">
                  {accountName(post.account)}
                </span>
                <StatusBadge post={post.display_state} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Calendar inside Posts (spec FR-066–FR-069): read-only, one week from Monday
 * in the URL (`?view=calendar&week=YYYY-MM-DD`). A week of day columns from
 * 1280 px (narrower, seven columns are unreadable), an agenda by day below.
 * No Drafts, no Cancelled.
 */
function CalendarView({ posts, rowPath, selectedId }: CalendarViewProps) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const isLarge = useMediaQuery(MEDIA_XL_UP);
  const param = params.get("week");
  // "Today" of this view, read once (rendering stays pure).
  const [today] = useState(() => new Date());
  const { monday, valid } = parseWeek(param, today);
  const week = dayKey(monday);

  const pathFor = (target: Date) => {
    const next = new URLSearchParams(params);
    next.set("view", "calendar");
    next.set("week", dayKey(target));
    return `?${next.toString()}`;
  };
  // An invalid or missing week is written as the current one (no history).
  const fix = valid ? null : pathFor(monday);
  useEffect(() => {
    if (fix !== null) {
      void navigate(fix, { replace: true });
    }
  }, [fix, navigate]);

  const days = postsByDay(posts, monday);
  const empty = days.every((day) => day.posts.length === 0);
  return (
    <div className="ap-calendar">
      <div className="ap-calendar__nav">
        <h2 className="ap-section-title ap-calendar__range" aria-live="polite">
          {formatRange(monday)}
        </h2>
        <div className="ap-calendar__buttons" role="group" aria-label="Week">
          <Button as="link" to={pathFor(addWeeks(monday, -1))} icon="back">
            Previous week
          </Button>
          <Button as="link" to={pathFor(mondayOf(today))}>
            Today
          </Button>
          <Button as="link" to={pathFor(addWeeks(monday, 1))}>
            Next week
          </Button>
        </div>
        <p className="ap-meta">Times in {timeZoneLabel()}</p>
      </div>
      {empty && <p className="ap-meta">No posts this week.</p>}
      <section
        className={isLarge ? "ap-calendar-week" : "ap-calendar-agenda"}
        aria-label={`Week of ${formatRange(monday)}`}
        data-week={week}
      >
        {days
          .filter((day) => isLarge || day.posts.length > 0)
          .map((day) => (
            <Day
              key={day.key}
              day={day}
              rowPath={rowPath}
              selectedId={selectedId}
              compact={isLarge}
            />
          ))}
      </section>
    </div>
  );
}

export default CalendarView;
