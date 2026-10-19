import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api.ts";
import AutosaveRegistry from "./AutosaveRegistry.tsx";
import { useAutosaveRegistry } from "./autosave-registry.ts";
import { useAutosave } from "./useAutosave.ts";

/** A save whose requests settle only when the test says so. */
function controlledSave() {
  const calls: {
    value: string;
    resolve: (result: string) => void;
    reject: (error: unknown) => void;
  }[] = [];
  const save = (value: string) =>
    new Promise<string>((resolve, reject) =>
      calls.push({ value, resolve, reject }),
    );
  return { calls, save };
}

const failure = new ApiError(500, "server_error", "The server failed.");

describe("useAutosave", () => {
  it("sends changes made during a flight once, with the latest value, in order", async () => {
    const { calls, save } = controlledSave();
    const saved: string[] = [];
    const { result } = renderHook(() =>
      useAutosave(save, { onSaved: (value) => saved.push(value) }),
    );

    act(() => result.current.schedule("a"));
    expect(result.current.status).toBe("saving");
    act(() => {
      result.current.schedule("b");
      result.current.schedule("c");
    });
    expect(calls.map((call) => call.value)).toEqual(["a"]);

    await act(async () => calls[0].resolve("saved a"));
    expect(calls.map((call) => call.value)).toEqual(["a", "c"]);
    await act(async () => calls[1].resolve("saved c"));

    expect(result.current.status).toBe("saved");
    // The response of "a" arrived while "c" was waiting: it was stale.
    expect(saved).toEqual(["saved c"]);
  });

  it("never lets a stale failure hide a later successful save", async () => {
    const { calls, save } = controlledSave();
    const { result } = renderHook(() => useAutosave(save));

    act(() => result.current.schedule("a"));
    act(() => result.current.schedule("b"));
    await act(async () => calls[0].reject(failure));
    expect(result.current.status).toBe("saving");
    await act(async () => calls[1].resolve("ok"));

    expect(result.current.status).toBe("saved");
    expect(result.current.error).toBeNull();
  });

  it("keeps the error and resends the last value on retry", async () => {
    const { calls, save } = controlledSave();
    const { result } = renderHook(() => useAutosave(save));

    act(() => result.current.schedule("a"));
    await act(async () => calls[0].reject(failure));
    expect(result.current.status).toBe("error");
    expect(result.current.error).toBe("The server failed.");

    act(() => result.current.retry());
    expect(calls.map((call) => call.value)).toEqual(["a", "a"]);
    await act(async () => calls[1].resolve("ok"));
    expect(result.current.status).toBe("saved");
  });

  it("flush waits for pending saves and reports a failure", async () => {
    const { calls, save } = controlledSave();
    const { result } = renderHook(() => useAutosave(save));

    act(() => {
      result.current.schedule("a");
      result.current.schedule("b");
    });
    let flushed: boolean | undefined;
    const flushing = result.current.flush().then((ok) => (flushed = ok));
    await act(async () => calls[0].resolve("ok"));
    expect(flushed).toBeUndefined();
    await act(async () => calls[1].reject(failure));
    await act(() => flushing);
    expect(flushed).toBe(false);

    // Nothing pending: resolves at once.
    expect(await result.current.flush()).toBe(false);
  });

  it("flushAll covers every card of the registry", async () => {
    const first = controlledSave();
    const second = controlledSave();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <AutosaveRegistry>{children}</AutosaveRegistry>
    );
    const { result } = renderHook(
      () => ({
        youtube: useAutosave(first.save, { registryKey: "youtube" }),
        tiktok: useAutosave(second.save, { registryKey: "tiktok" }),
        registry: useAutosaveRegistry()!,
      }),
      { wrapper },
    );

    act(() => {
      result.current.youtube.schedule("a");
      result.current.tiktok.schedule("b");
    });
    let flushed: boolean | undefined;
    const flushing = result.current.registry
      .flushAll()
      .then((ok) => (flushed = ok));
    await act(async () => first.calls[0].resolve("ok"));
    expect(flushed).toBeUndefined();
    await act(async () => second.calls[0].reject(failure));
    await act(() => flushing);

    expect(flushed).toBe(false);
    await waitFor(() => expect(result.current.registry.errorCount).toBe(1));
  });
});
