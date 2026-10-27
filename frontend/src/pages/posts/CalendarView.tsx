import { useEffect, useState, type DragEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import type { Publication } from "../../types.ts";
import { MEDIA_XL_UP } from "../../ui/breakpoints.ts";
import Button from "../../ui/Button.tsx";
import IconButton from "../../ui/IconButton.tsx";
import StatusBadge from "../../ui/StatusBadge.tsx";
import { useMediaQuery } from "../../ui/useMediaQuery.ts";
import { accountName, publicationTitle } from "../../utils.ts";
import {
  addWeeks,
  canDrag,
  dayKey,
  formatRange,
  isToday,
  mondayOf,
  moveToDay,
  parseWeek,
  postsByDay,
  scheduleAction,
  timeZoneLabel,
  type CalendarDay,
} from "./calendar.ts";
import ActionDialog from "./ActionDialog.tsx";
import { ACTION_LABELS } from "./post-actions.ts";

type ScheduleAction = NonNullable<ReturnType<typeof scheduleAction>>;

interface CalendarViewProps {
  /** The Posts shown (filtered). */
  posts: Publication[];
  /** Every Post of the project, for the dialog's guard. */
  allPosts: Publication[];
  paused: boolean;
  rowPath: (post: Publication) => string;
  selectedId: number | null;
  /** Reloads the list after a reschedule, successful or not. */
  onChanged: () => Promise<void>;
}

interface Scheduling {
  post: Publication;
  action: ScheduleAction;
  /** The date a drop proposes (target day + original local time). */
  initialAt?: string;
}

/** The only data a Calendar drag carries: the Post id (contracts/ui.md §4). */
const DRAG_TYPE = "application/x-autopublisher-post";
const INVALID_DROP_HINT = "Can't move here — that time has already passed.";

/** The Post being dragged in the week view, as it was when the drag started. */
interface Drag {
  postId: number;
  scheduledAt: string;
  /** "Now" of this drag, so every day keeps one classification meanwhile. */
  now: Date;
}

/** What the week view's days need to take part in a drag (none in agenda). */
interface DragProps {
  drag: Drag | null;
  over: string | null;
  onStart: (post: Publication, event: DragEvent<HTMLAnchorElement>) => void;
  onEnd: () => void;
  onOver: (day: CalendarDay, event: DragEvent<HTMLElement>) => void;
  onDrop: (day: CalendarDay, event: DragEvent<HTMLElement>) => void;
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
  onSchedule,
  dragging,
}: {
  day: CalendarDay;
  rowPath: (post: Publication) => string;
  selectedId: number | null;
  compact: boolean;
  onSchedule: (scheduling: Scheduling) => void;
  dragging: DragProps | null;
}) {
  const label = day.date.toLocaleDateString(undefined, {
    weekday: compact ? "short" : "long",
    day: "numeric",
    month: "short",
  });
  const headingId = `calendar-day-${day.key}`;
  const drag = dragging?.drag ?? null;
  const drop = drag
    ? moveToDay(drag.scheduledAt, day.date, drag.now).kind
    : null;
  const over = drag !== null && dragging?.over === day.key;
  return (
    <section
      className={
        isToday(day.date)
          ? "ap-calendar-day ap-calendar-day--today"
          : "ap-calendar-day"
      }
      aria-labelledby={headingId}
      data-drop={drop ?? undefined}
      data-drop-over={over ? "" : undefined}
      onDragOver={dragging ? (event) => dragging.onOver(day, event) : undefined}
      onDrop={dragging ? (event) => dragging.onDrop(day, event) : undefined}
    >
      <h3 id={headingId} className="ap-calendar-day__title">
        {label}
        {isToday(day.date) && <span className="ap-meta"> · Today</span>}
      </h3>
      {over && drop === "invalid" && (
        <p className="ap-calendar-day__hint">{INVALID_DROP_HINT}</p>
      )}
      {day.posts.length === 0 ? (
        compact ? null : (
          <p className="ap-meta">Nothing this day.</p>
        )
      ) : (
        <ul className="ap-calendar-day__posts">
          {day.posts.map(({ post, at }) => {
            const action = scheduleAction(post);
            const label = action
              ? `${ACTION_LABELS[action]}: ${publicationTitle(post)}`
              : "";
            const draggable = dragging !== null && canDrag(post);
            return (
              <li
                key={post.id}
                className={
                  action
                    ? "ap-calendar-entry ap-calendar-entry--schedulable"
                    : "ap-calendar-entry"
                }
              >
                <Link
                  to={rowPath(post)}
                  className="ap-calendar-item"
                  data-detail-id={post.id}
                  aria-current={post.id === selectedId ? "true" : undefined}
                  draggable={draggable || undefined}
                  data-dragging={drag?.postId === post.id ? "" : undefined}
                  onDragStart={
                    draggable
                      ? (event) => dragging.onStart(post, event)
                      : undefined
                  }
                  onDragEnd={draggable ? dragging.onEnd : undefined}
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
                {/* A sibling of the link, never inside it (Feature 024). */}
                {action &&
                  (compact ? (
                    <IconButton
                      icon="clock"
                      label={label}
                      className="ap-calendar-entry__schedule"
                      onClick={() => onSchedule({ post, action })}
                    />
                  ) : (
                    <Button
                      variant="ghost"
                      className="ap-calendar-entry__schedule"
                      aria-label={label}
                      onClick={() => onSchedule({ post, action })}
                    >
                      {ACTION_LABELS[action]}
                    </Button>
                  ))}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

/**
 * Calendar inside Posts (spec FR-066–FR-069): one week from Monday in the URL
 * (`?view=calendar&week=YYYY-MM-DD`). A week of day columns from 1280 px
 * (narrower, seven columns are unreadable), an agenda by day below. No Drafts,
 * no Cancelled. Scheduled, Missed and Failed Posts can be rescheduled in place
 * with the existing action dialog; in the week view an automatic schedule can
 * also be dragged to another day, which only opens that dialog (Feature 024).
 */
function CalendarView({
  posts,
  allPosts,
  paused,
  rowPath,
  selectedId,
  onChanged,
}: CalendarViewProps) {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const isLarge = useMediaQuery(MEDIA_XL_UP);
  const param = params.get("week");
  // "Today" of this view, read once (rendering stays pure).
  const [today] = useState(() => new Date());
  const { monday, valid } = parseWeek(param, today);
  const week = dayKey(monday);
  const [scheduling, setScheduling] = useState<Scheduling | null>(null);
  const [drag, setDrag] = useState<Drag | null>(null);
  const [over, setOver] = useState<string | null>(null);

  // A poll may remove or change the dragged Post: the drag is then dropped
  // (its `dragend` may never come once its link is gone, research R11).
  const dragged = drag
    ? posts.find((post) => post.id === drag.postId)
    : undefined;
  if (
    drag !== null &&
    (dragged === undefined ||
      !canDrag(dragged) ||
      dragged.scheduled_at !== drag.scheduledAt)
  ) {
    setDrag(null);
    setOver(null);
  }

  const endDrag = () => {
    setDrag(null);
    setOver(null);
  };
  const dragging: DragProps | null = isLarge
    ? {
        drag,
        over,
        onStart: (post, event) => {
          // The browser's link data (its URL) is replaced by the Post id only.
          event.dataTransfer.clearData();
          event.dataTransfer.setData(DRAG_TYPE, String(post.id));
          event.dataTransfer.effectAllowed = "move";
          setDrag({
            postId: post.id,
            scheduledAt: post.scheduled_at!,
            now: new Date(),
          });
        },
        onEnd: endDrag,
        onOver: (day, event) => {
          if (drag === null) {
            return; // Not a Calendar drag: the browser's default applies.
          }
          const kind = moveToDay(drag.scheduledAt, day.date, drag.now).kind;
          if (kind !== "invalid") {
            event.preventDefault(); // Allows the drop.
          }
          event.dataTransfer.dropEffect = kind === "valid" ? "move" : "none";
          if (over !== day.key) {
            setOver(day.key);
          }
        },
        onDrop: (day, event) => {
          if (drag === null) {
            return;
          }
          event.preventDefault();
          endDrag();
          // Checked again on the current list: a poll may have changed it.
          const post = posts.find((item) => item.id === drag.postId);
          if (
            post === undefined ||
            !canDrag(post) ||
            post.scheduled_at !== drag.scheduledAt
          ) {
            return;
          }
          const move = moveToDay(post.scheduled_at, day.date, new Date());
          if (move.kind === "valid") {
            // Only opens the dialog: nothing is sent until it is confirmed.
            setScheduling({
              post,
              action: "edit_schedule",
              initialAt: move.at,
            });
          }
        },
      }
    : null;

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
              onSchedule={setScheduling}
              dragging={dragging}
            />
          ))}
      </section>
      {scheduling && (
        <ActionDialog
          action={scheduling.action}
          post={scheduling.post}
          posts={allPosts}
          paused={paused}
          initialAt={scheduling.initialAt}
          onClose={() => setScheduling(null)}
          onDone={() => {
            setScheduling(null);
            void onChanged();
          }}
          onFailed={() => void onChanged()}
        />
      )}
    </div>
  );
}

export default CalendarView;
