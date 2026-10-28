// The state and orchestration of one Publish task (plan §5): a reducer for the
// phases and the Posts of the set, the URL `?posts=` as the set's identity,
// and the actions that write (Continue, add/remove destination, final action).
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from "react";
import { useLocation, useNavigate } from "react-router";
import {
  ApiError,
  cancelPublication,
  createPublications,
  createTextPublications,
  getAccountHealth,
  getContentUsage,
  getPublication,
  listDistributionPresets,
  listPlatforms,
  reactivatePublication,
  updatePublication,
  type PublicationUpdate,
} from "../../api.ts";
import type { AutosaveRegistryValue } from "../../components/platform/autosave-registry.ts";
import type { DeclarationAcceptance } from "../../components/platform/tiktok-declaration.ts";
import type {
  AccountHealth,
  AssetPublication,
  Content,
  DistributionPreset,
  PlatformAvailability,
  PostDisplayState,
  Project,
  Publication,
} from "../../types.ts";
import {
  fromDateTimeLocalValue,
  parseHashtags,
  POLL_INTERVAL_MS,
  toApiError,
} from "../../utils.ts";
import {
  destinations as listDestinations,
  type Destination,
} from "./destinations.ts";
import {
  DESTINATIONS_ID,
  TEXT_ID,
  prevalidate,
  runSet,
  type RunKind,
  type SummaryItem,
} from "./final-action.ts";
import {
  parsePostsParam,
  partition,
  serializePostsParam,
  validateMembers,
  withId,
  withoutId,
  type PublishMode,
  type SetScope,
} from "./publish-set.ts";
import {
  buildCreateBody,
  commonFromMedia,
  snapshotFor,
  type CommonText,
  type CustomText,
} from "./snapshot.ts";

export type Phase = "loading" | "composing" | "creating" | "task";

export interface SkippedDestination {
  accountId: number;
  name: string;
  reason: string;
}

export interface PresetNotice {
  preset: string;
  skipped: SkippedDestination[];
}

export interface ComposeState {
  /** Account ids, in destination-list order. */
  selected: number[];
  common: CommonText;
  /** Dirty fields per destination only. */
  custom: Record<number, CustomText>;
  presetNotice: PresetNotice | null;
  /** The rejected create request (nothing was created). */
  createError: ApiError | null;
}

/** What the last final action did to one Post. */
export interface PostStep {
  run: RunKind;
  status: "running" | "done" | "error";
  message: string | null;
  /** Results already showed its Published emphasis (Feature 026): never again. */
  emphasized?: boolean;
}

export interface TaskState {
  phase: Phase;
  /** Posts loaded for this task, by id (the URL decides which are members). */
  posts: Record<number, Publication>;
  notice: string | null;
  compose: ComposeState;
  steps: Record<number, PostStep>;
  /** Account → the Post removed from this task (React state only, FR-035). */
  removed: Record<number, number>;
  running: RunKind | null;
  /** Focus goes to the Review heading once (after Continue). */
  focusReview: boolean;
  /** Focus goes to the Results heading once (after the final action). */
  focusResults: boolean;
}

export type TaskAction =
  | { type: "compose"; common: CommonText }
  | {
      type: "compose_change";
      changes: Partial<
        Pick<ComposeState, "selected" | "common" | "custom" | "presetNotice">
      >;
    }
  | { type: "create_start" }
  | { type: "create_failed"; error: ApiError }
  | { type: "created"; posts: Publication[] }
  | {
      type: "members_loaded";
      posts: Publication[];
      notice: string | null;
      common: CommonText;
    }
  | { type: "post_updated"; post: Publication }
  | { type: "post_removed"; post: Publication }
  | { type: "run_start"; run: RunKind; ids: number[] }
  | {
      type: "run_event";
      id: number;
      post: Publication | null;
      error: string | null;
    }
  | { type: "run_end" }
  | { type: "focus_done" }
  | { type: "emphasis_shown"; id: number };

export function emptyCompose(common: CommonText): ComposeState {
  return {
    selected: [],
    common,
    custom: {},
    presetNotice: null,
    createError: null,
  };
}

export function initialTaskState(): TaskState {
  return {
    phase: "loading",
    posts: {},
    notice: null,
    compose: emptyCompose({ description: "", hashtags: "" }),
    steps: {},
    removed: {},
    running: null,
    focusReview: false,
    focusResults: false,
  };
}

function byId(posts: Publication[]): Record<number, Publication> {
  return Object.fromEntries(posts.map((post) => [post.id, post]));
}

export function taskReducer(state: TaskState, action: TaskAction): TaskState {
  switch (action.type) {
    case "compose":
      return {
        ...state,
        phase: "composing",
        compose: emptyCompose(action.common),
      };
    case "compose_change":
      return {
        ...state,
        compose: { ...state.compose, ...action.changes, createError: null },
      };
    case "create_start":
      return {
        ...state,
        phase: "creating",
        compose: { ...state.compose, createError: null },
      };
    case "create_failed":
      // Nothing was created: back to Compose with every input kept.
      return {
        ...state,
        phase: "composing",
        compose: { ...state.compose, createError: action.error },
      };
    case "created":
      return {
        ...state,
        phase: "task",
        posts: { ...state.posts, ...byId(action.posts) },
        focusReview: true,
      };
    case "members_loaded": {
      const phase =
        action.posts.length > 0
          ? "task"
          : state.phase === "task"
            ? "task"
            : "composing";
      return {
        ...state,
        phase,
        posts: { ...state.posts, ...byId(action.posts) },
        notice: action.notice ?? state.notice,
        compose:
          state.phase === "loading" && phase === "composing"
            ? emptyCompose(action.common)
            : state.compose,
      };
    }
    case "post_updated":
      return {
        ...state,
        posts: { ...state.posts, [action.post.id]: action.post },
      };
    case "post_removed": {
      const posts = { ...state.posts };
      delete posts[action.post.id];
      const steps = { ...state.steps };
      delete steps[action.post.id];
      return {
        ...state,
        posts,
        steps,
        removed: { ...state.removed, [action.post.account_id]: action.post.id },
      };
    }
    case "run_start":
      return {
        ...state,
        running: action.run,
        // Each action starts clean: results of an earlier one are replaced.
        steps: Object.fromEntries(
          action.ids.map((id) => [
            id,
            { run: action.run, status: "running", message: null },
          ]),
        ),
      };
    case "run_event": {
      const step = state.steps[action.id];
      return {
        ...state,
        posts: action.post
          ? { ...state.posts, [action.id]: action.post }
          : state.posts,
        steps: {
          ...state.steps,
          [action.id]: {
            run: step?.run ?? state.running ?? "now",
            status: action.error === null ? "done" : "error",
            message: action.error,
          },
        },
      };
    }
    case "run_end":
      return { ...state, running: null, focusResults: true };
    case "focus_done":
      return { ...state, focusReview: false, focusResults: false };
    case "emphasis_shown": {
      const step = state.steps[action.id];
      if (step === undefined || step.emphasized) {
        return state;
      }
      return {
        ...state,
        steps: { ...state.steps, [action.id]: { ...step, emphasized: true } },
      };
    }
  }
}

/** The members of the set in URL order, partitioned (never stored). */
export function selectMembers(state: TaskState, ids: readonly number[]) {
  const members = ids
    .map((id) => state.posts[id])
    .filter((post): post is Publication => post !== undefined);
  return { members, ...partition(members) };
}

/**
 * Rows of Results: every member that left Draft, plus the Drafts the last
 * action could not start or schedule (they also stay in Still to finish).
 */
export function selectResultRows(
  state: TaskState,
  members: readonly Publication[],
): Publication[] {
  return members.filter(
    (post) =>
      post.display_state !== "draft" ||
      state.steps[post.id]?.status === "error",
  );
}

export interface PublishContext {
  health: AccountHealth[];
  platforms: PlatformAvailability[];
  presets: DistributionPreset[];
  /** The Media's Posts (media mode; none for a text post). */
  usage: AssetPublication[];
}

function droppedNotice(count: number): string {
  return count === 1
    ? "1 post couldn't be included."
    : `${count} posts couldn't be included.`;
}

/** Not found posts are dropped from the set; other failures are errors. */
async function loadPost(id: number): Promise<Publication | null> {
  try {
    return await getPublication(id);
  } catch (caught) {
    if (caught instanceof ApiError && caught.status === 404) {
      return null;
    }
    throw caught;
  }
}

interface UsePublishTaskInput {
  project: Project;
  /** The Media of the task; null for a text post (`/posts/new`). */
  media: Content | null;
}

/**
 * The task's search for a set: `?posts=…`, plus the Library return `from` of
 * the current search when there is one (research R10). Nothing else is kept.
 */
export function postsSearch(ids: readonly number[], current: string): string {
  const from = new URLSearchParams(current).get("from");
  const posts = `?posts=${serializePostsParam(ids)}`;
  return from === null ? posts : `${posts}&from=${encodeURIComponent(from)}`;
}

/**
 * One controller for both Publish tasks: a Media (`/library/:mid/publish`) or
 * a text post (`/posts/new`). Only Compose's create call, the destinations'
 * rule and the set's membership differ by mode.
 */
export function usePublishTask({ project, media }: UsePublishTaskInput) {
  const mode: PublishMode = media === null ? "text" : "media";
  const mediaId = media?.id ?? null;
  const location = useLocation();
  const navigate = useNavigate();
  const postsParam = new URLSearchParams(location.search).get("posts");
  const ids = useMemo(() => parsePostsParam(postsParam), [postsParam]);
  const [state, dispatch] = useReducer(
    taskReducer,
    undefined,
    initialTaskState,
  );
  const [context, setContext] = useState<PublishContext | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [declarations, setDeclarations] = useState<
    Record<number, DeclarationAcceptance | null>
  >({});
  const [when, setWhen] = useState<RunKind>("now");
  const [at, setAt] = useState("");
  const [summary, setSummary] = useState<SummaryItem[]>([]);
  const [validating, setValidating] = useState(false);
  const scope: SetScope = useMemo(
    () => ({ projectId: project.id, mode, mediaId }),
    [project.id, mode, mediaId],
  );

  // Async work started here may outlive the page (SPA navigation): it only
  // updates the page while it is mounted.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // Latest values for async work and for the effects below (synced first).
  const stateRef = useRef(state);
  const idsRef = useRef(ids);
  const contextRef = useRef(context);
  const mediaRef = useRef(media);
  const searchRef = useRef(location.search);
  // Layout effect: synced before the browser can deliver the next click, so a
  // quick "Publish to…" never acts on the previous set.
  useLayoutEffect(() => {
    stateRef.current = state;
    idsRef.current = ids;
    contextRef.current = context;
    mediaRef.current = media;
    searchRef.current = location.search;
  });

  const replaceIds = useCallback(
    (next: readonly number[]) => {
      if (!mounted.current) {
        return;
      }
      idsRef.current = [...next];
      void navigate(
        {
          pathname: location.pathname,
          search: postsSearch(next, searchRef.current),
        },
        { replace: true },
      );
    },
    [navigate, location.pathname],
  );

  // Account health, platforms, presets and the Media's Posts: once per task.
  const loadContext = useCallback(() => {
    Promise.all([
      getAccountHealth(project.id),
      listPlatforms(),
      listDistributionPresets(project.id),
      mediaId === null
        ? Promise.resolve([])
        : getContentUsage(mediaId).then((loaded) => loaded.publications),
    ])
      .then(
        ([health, platforms, presets, usage]) =>
          mounted.current && setContext({ health, platforms, presets, usage }),
      )
      .catch(
        (caught: unknown) =>
          mounted.current && setLoadError(toApiError(caught).message),
      );
  }, [project.id, mediaId]);
  useEffect(() => {
    loadContext();
  }, [loadContext]);

  const setPresets = useCallback(
    (presets: DistributionPreset[]) =>
      setContext((current) => (current ? { ...current, presets } : current)),
    [],
  );

  const reloadUsage = useCallback(async () => {
    if (mediaId === null) {
      return;
    }
    const usage = (await getContentUsage(mediaId)).publications;
    if (mounted.current) {
      setContext((current) => (current ? { ...current, usage } : current));
    }
  }, [mediaId]);

  // The set comes from the URL alone. Without `posts`: Resume the Media's
  // Drafts, or Compose. With `posts`: exactly those ids, validated.
  const [setVersion, setSetVersion] = useState(0);
  const contextReady = context !== null;
  useEffect(() => {
    // Read, not watched: a later usage reload must not resolve the set again.
    const loadedContext = contextRef.current;
    if (!contextReady || loadedContext === null) {
      return;
    }
    const common = commonFromMedia(mediaRef.current);
    const wanted = parsePostsParam(postsParam);
    if (postsParam === null) {
      const drafts = loadedContext.usage
        .filter((row) => row.display_state === "draft")
        .map((row) => row.publication_id)
        .sort((a, b) => a - b);
      if (drafts.length > 0) {
        replaceIds(drafts);
      } else {
        dispatch({ type: "members_loaded", posts: [], notice: null, common });
      }
      return;
    }
    let active = true;
    const known = stateRef.current.posts;
    Promise.all(wanted.map((id) => known[id] ?? loadPost(id)))
      .then((loaded) => {
        if (!active || !mounted.current) {
          return;
        }
        const found = loaded.filter(
          (post): post is Publication => post !== null,
        );
        const { members, dropped } = validateMembers(found, scope);
        const droppedCount = wanted.length - found.length + dropped.length;
        if (droppedCount > 0) {
          replaceIds(members.map((post) => post.id));
        }
        dispatch({
          type: "members_loaded",
          posts: members,
          notice: droppedCount > 0 ? droppedNotice(droppedCount) : null,
          common,
        });
      })
      .catch((caught: unknown) => {
        if (active && mounted.current) {
          setLoadError(toApiError(caught).message);
        }
      });
    return () => {
      active = false;
    };
  }, [contextReady, postsParam, setVersion, scope, replaceIds]);

  const { members, review, results } = selectMembers(state, ids);
  const resultRows = selectResultRows(state, members);

  // Poll only the members being published, every 2 s, until none is left.
  const publishingKey = members
    .filter((post) => post.display_state === "publishing")
    .map((post) => post.id)
    .join(",");
  useEffect(() => {
    if (publishingKey === "") {
      return;
    }
    const timer = window.setInterval(() => {
      for (const id of publishingKey.split(",").map(Number)) {
        getPublication(id)
          .then(
            (post) =>
              mounted.current && dispatch({ type: "post_updated", post }),
          )
          .catch(() => {
            // The row keeps its last known state until the next tick.
          });
      }
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [publishingKey]);

  /** What this task knows better than the usage loaded at mount. */
  const known = useMemo(() => {
    const map = new Map<number, PostDisplayState>();
    for (const post of Object.values(state.posts)) {
      map.set(post.id, post.display_state);
    }
    for (const id of Object.values(state.removed)) {
      map.set(id, "cancelled");
    }
    return map;
  }, [state.posts, state.removed]);

  const destinationList: Destination[] = useMemo(
    () =>
      context === null
        ? []
        : listDestinations({
            projectId: project.id,
            mode,
            mediaType: media?.media_type ?? null,
            health: context.health,
            platforms: context.platforms,
            usage: context.usage,
            setIds: ids,
            known,
          }),
    [context, project.id, mode, media?.media_type, ids, known],
  );

  // --- Compose ---------------------------------------------------------------

  const changeCompose = useCallback(
    (changes: Extract<TaskAction, { type: "compose_change" }>["changes"]) =>
      dispatch({ type: "compose_change", changes }),
    [],
  );

  /** Continue: one all-or-nothing create with the explicit snapshot. */
  const continueToReview = useCallback(async () => {
    const { compose } = stateRef.current;
    const selected = destinationList.filter((destination) =>
      compose.selected.includes(destination.accountId),
    );
    const missing = [
      ...(mode === "text" && compose.common.description.trim() === ""
        ? [{ target: TEXT_ID, text: "Write the text of the post." }]
        : []),
      ...(selected.length === 0
        ? [
            {
              target: DESTINATIONS_ID,
              text: "Choose at least one destination.",
            },
          ]
        : []),
    ];
    if (missing.length > 0) {
      setSummary(missing);
      return false;
    }
    setSummary([]);
    dispatch({ type: "create_start" });
    try {
      // Text posts: one common text, saved as each Post's own (plan C3).
      const created =
        media === null
          ? await createTextPublications(project.id, {
              account_ids: selected.map((destination) => destination.accountId),
              description: compose.common.description,
              hashtags: parseHashtags(compose.common.hashtags),
            })
          : await createPublications(
              media.id,
              buildCreateBody(
                selected.map((destination) => ({
                  accountId: destination.accountId,
                  platform: destination.platform,
                })),
                compose.common,
                compose.custom,
                media,
              ),
            );
      if (!mounted.current) {
        return true;
      }
      // Selection order, whatever order the response has.
      const ordered = selected
        .map((destination) =>
          created.find((post) => post.account_id === destination.accountId),
        )
        .filter((post): post is Publication => post !== undefined);
      dispatch({ type: "created", posts: ordered });
      replaceIds(ordered.map((post) => post.id));
      return true;
    } catch (caught) {
      if (mounted.current) {
        dispatch({ type: "create_failed", error: toApiError(caught) });
      }
      return false;
    }
  }, [destinationList, media, mode, project.id, replaceIds]);

  // --- Review: the set's destinations ----------------------------------------

  /** Add to this task: an existing Draft of this Media joins the set (no write). */
  const addToTask = useCallback(
    (postId: number) => {
      replaceIds(withId(idsRef.current, postId));
    },
    [replaceIds],
  );

  /**
   * Add a destination in Review: reactivate exactly the Post removed from this
   * task for that account, else create one Draft with the Media's values as
   * explicit overrides (a text post copies the text of the task's first
   * Draft, or Compose's). Returns an error message, or null.
   */
  const addDestination = useCallback(
    async (destination: Destination): Promise<string | null> => {
      const removedId = stateRef.current.removed[destination.accountId];
      try {
        const textSource =
          selectMembers(stateRef.current, idsRef.current).review[0] ?? null;
        const post =
          removedId !== undefined
            ? await reactivatePublication(removedId)
            : media === null
              ? (
                  await createTextPublications(project.id, {
                    account_ids: [destination.accountId],
                    description:
                      textSource?.description ??
                      stateRef.current.compose.common.description,
                    hashtags:
                      textSource?.hashtags ??
                      parseHashtags(stateRef.current.compose.common.hashtags),
                  })
                )[0]
              : (
                  await createPublications(media.id, {
                    account_ids: [destination.accountId],
                    targets: {
                      [destination.accountId]: snapshotFor(
                        {
                          accountId: destination.accountId,
                          platform: destination.platform,
                        },
                        commonFromMedia(media),
                        undefined,
                        media,
                      ),
                    },
                  })
                )[0];
        if (mounted.current) {
          dispatch({ type: "post_updated", post });
          replaceIds(withId(idsRef.current, post.id));
        }
        return null;
      } catch (caught) {
        const error = toApiError(caught);
        if (error.code === "duplicate") {
          void reloadUsage().catch(() => {});
        }
        return error.message;
      }
    },
    [media, project.id, replaceIds, reloadUsage],
  );

  /**
   * Remove a Draft from the task (after its confirmation): cancel it and drop
   * its id. A Post that is no longer a Draft is not cancelled: it stays in the
   * set with its current state. Returns a message when nothing was cancelled.
   */
  const removeDestination = useCallback(
    async (post: Publication): Promise<string | null> => {
      try {
        const current = await getPublication(post.id);
        if (current.display_state !== "draft") {
          if (mounted.current) {
            dispatch({ type: "post_updated", post: current });
          }
          return "This post is no longer a draft, so it wasn't removed.";
        }
        const cancelled = await cancelPublication(post.id);
        if (mounted.current) {
          dispatch({ type: "post_removed", post: cancelled });
          replaceIds(withoutId(idsRef.current, post.id));
        }
        return null;
      } catch (caught) {
        return toApiError(caught).message;
      }
    },
    [replaceIds],
  );

  /** Content by destination: one explicit PATCH per chosen Post. */
  const updateContent = useCallback(
    async (postIds: number[], changes: PublicationUpdate) => {
      for (const id of postIds) {
        const post = await updatePublication(id, changes);
        if (mounted.current) {
          dispatch({ type: "post_updated", post });
        }
      }
    },
    [],
  );

  // --- Final action ----------------------------------------------------------

  const declarationControl = useCallback(
    (postId: number) => ({
      accepted: declarations[postId] ?? null,
      onChange: (accepted: DeclarationAcceptance | null) =>
        setDeclarations((current) => ({ ...current, [postId]: accepted })),
    }),
    [declarations],
  );

  /**
   * Validate every Draft first (no writes); if all are ready, run them one by
   * one. Returns the summary items (empty when the action ran).
   */
  const submit = useCallback(
    async (
      registry: Pick<AutosaveRegistryValue, "flushAll" | "failedKeys">,
    ): Promise<SummaryItem[]> => {
      const drafts = selectMembers(stateRef.current, idsRef.current).review;
      setValidating(true);
      setSummary([]);
      const { items, consents } = await prevalidate({
        drafts,
        declarations,
        run: when,
        at,
        registry,
      });
      if (mounted.current) {
        setValidating(false);
        setSummary(items);
      }
      if (items.length > 0) {
        return items;
      }
      const run = when;
      const draftIds = drafts.map((post) => post.id);
      if (mounted.current) {
        dispatch({ type: "run_start", run, ids: draftIds });
        // Every new action starts with the declarations unchecked.
        setDeclarations({});
      }
      await runSet({
        ids: draftIds,
        consents,
        run,
        scheduledAt: run === "schedule" ? fromDateTimeLocalValue(at) : null,
        onEvent: (event) => {
          if (mounted.current) {
            dispatch({
              type: "run_event",
              id: event.id,
              post: event.post,
              error: event.error,
            });
          }
        },
      });
      if (mounted.current) {
        dispatch({ type: "run_end" });
      }
      return [];
    },
    [declarations, when, at],
  );

  const emphasisShown = useCallback(
    (id: number) => dispatch({ type: "emphasis_shown", id }),
    [],
  );

  const retryLoad = useCallback(() => {
    setLoadError(null);
    if (context === null) {
      loadContext();
    } else {
      setSetVersion((version) => version + 1);
    }
  }, [context, loadContext]);

  return {
    state,
    dispatch,
    ids,
    context,
    setPresets,
    loadError,
    retryLoad,
    mode,
    members,
    review,
    results,
    resultRows,
    destinations: destinationList,
    changeCompose,
    continueToReview,
    addToTask,
    addDestination,
    removeDestination,
    updateContent,
    declarationControl,
    when,
    setWhen,
    at,
    setAt,
    summary,
    setSummary,
    validating,
    submit,
    emphasisShown,
  };
}

export type PublishTaskController = ReturnType<typeof usePublishTask>;
