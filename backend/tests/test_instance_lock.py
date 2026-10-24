"""Stable instance locks M → A → B (Feature 020, research §9).

Every conflict here happens inside one process on purpose: `flock` locks taken
through two different opens conflict, while POSIX `lockf` locks would not.
"""

import os
import signal
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, instance_lock
from app.deployment import DataLayout, is_inside
from app.instance_lock import (
    LockBusy,
    LockKind,
    LockRootUnsafe,
    hold,
    lock_file,
    locks_dir,
    observe,
)
from app.main import create_app
from tests.fakes import InMemoryCredentialStore

DATA = LockKind.DATA
DB = LockKind.DB
MAINT = LockKind.MAINTENANCE


def _server(data_dir: Path, db_path: Path) -> list[instance_lock.LockRequest]:
    return instance_lock.server_locks(data_dir, db_path)


def test_same_data_dir_conflicts(tmp_path: Path) -> None:
    with hold(_server(tmp_path / "data", tmp_path / "one.db")):
        with pytest.raises(LockBusy) as raised:
            with hold(_server(tmp_path / "data", tmp_path / "two.db")):
                pass

    assert raised.value.kind is DATA
    assert raised.value.exit_code == 75


def test_same_database_through_overrides_conflicts(tmp_path: Path) -> None:
    db_path = tmp_path / "shared.db"
    with hold(_server(tmp_path / "one", db_path)):
        with pytest.raises(LockBusy) as raised:
            with hold(_server(tmp_path / "two", db_path)):
                pass

    assert raised.value.kind is DB
    assert "database" in str(raised.value)


def test_separate_installations_do_not_collide(tmp_path: Path) -> None:
    with hold(_server(tmp_path / "one", tmp_path / "one" / "autopublisher.db")):
        with hold(_server(tmp_path / "two", tmp_path / "two" / "autopublisher.db")):
            pass


def test_released_on_exit_and_reusable(tmp_path: Path) -> None:
    requests = _server(tmp_path / "data", tmp_path / "data.db")
    with hold(requests):
        assert observe(DATA, tmp_path / "data").held
    assert not observe(DATA, tmp_path / "data").held
    with hold(requests):
        pass


def test_partial_failure_releases_what_was_taken(tmp_path: Path) -> None:
    db_path = tmp_path / "shared.db"
    with hold([(DB, db_path)]):
        with pytest.raises(LockBusy):
            with hold(_server(tmp_path / "data", db_path)):
                pass
        assert not observe(DATA, tmp_path / "data").held


@pytest.mark.parametrize(
    "kinds",
    [(DB, DATA), (DATA, MAINT), (DB, MAINT), (DATA, DATA), (MAINT, DB, DATA)],
)
def test_out_of_order_requests_are_rejected(
    tmp_path: Path, kinds: tuple[LockKind, ...]
) -> None:
    with pytest.raises(ValueError, match="M → A → B"):
        with hold([(kind, tmp_path / kind.value) for kind in kinds]):
            pass
    assert not list(locks_dir().glob("*.lock"))


def test_restore_order_takes_all_three(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOPUBLISHER_DATA_DIR", str(tmp_path / "data"))
    layout = DataLayout.resolve()

    assert [kind for kind, _ in instance_lock.restore_locks(layout)] == [
        MAINT,
        DATA,
        DB,
    ]
    with hold(instance_lock.restore_locks(layout)):
        for requests in (
            instance_lock.maintenance_locks(layout),
            _server(layout.data_dir, layout.db_path),
        ):
            with pytest.raises(LockBusy):
                with hold(requests):
                    pass


def test_maintenance_does_not_block_the_server(tmp_path: Path) -> None:
    data = tmp_path / "data"
    with hold([(MAINT, data)]):
        with hold(_server(data, data / "autopublisher.db")):
            pass


def test_symlinked_path_cannot_bypass_the_lock(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)

    with hold(_server(real, real / "autopublisher.db")):
        with pytest.raises(LockBusy) as raised:
            with hold(_server(link, tmp_path / "other.db")):
                pass
        with pytest.raises(LockBusy):
            with hold(_server(tmp_path / "other", link / "autopublisher.db")):
                pass

    assert raised.value.resource == real


def test_message_names_the_path_and_the_process(tmp_path: Path) -> None:
    data = tmp_path / "data"
    with hold(_server(data, tmp_path / "data.db")):
        with pytest.raises(LockBusy) as raised:
            with hold(_server(data, tmp_path / "other.db")):
                pass
        seen = observe(DATA, data)

    message = str(raised.value)
    assert str(data) in message
    assert f"process {os.getpid()}" in message
    assert "systemctl --user stop autopublisher" in message
    assert seen.held and seen.pid == os.getpid()


def test_lock_files_live_outside_the_data_dir(
    tmp_path: Path, isolate_lock_root: Path
) -> None:
    data = tmp_path / "data"
    data.mkdir()
    locks = locks_dir()
    assert locks == isolate_lock_root
    assert not is_inside(locks, data)
    with hold([(MAINT, data), (DATA, data), (DB, data / "autopublisher.db")]):
        files = sorted(path.name for path in locks.iterdir())

    assert list(data.iterdir()) == []
    assert [name.split("-")[0] for name in files] == ["data", "db", "maint"]
    assert all(
        len(name.split("-")[1]) == len("0123456789abcdef.lock") for name in files
    )
    assert lock_file(DATA, data) == locks / files[0]
    assert stat.S_IMODE(locks.stat().st_mode) == 0o700
    assert all(stat.S_IMODE((locks / n).stat().st_mode) == 0o600 for n in files)


def test_observe_never_creates_a_lock_file(tmp_path: Path) -> None:
    assert observe(DB, tmp_path / "nothing.db").held is False
    assert not lock_file(DB, tmp_path / "nothing.db").exists()


def test_server_retry_absorbs_a_handover(tmp_path: Path) -> None:
    """Like `--reload`: the old worker releases while the new one waits."""
    requests = _server(tmp_path / "data", tmp_path / "data.db")
    old = hold(requests)
    old.__enter__()
    sleeps: list[float] = []

    def release_old(seconds: float) -> None:
        sleeps.append(seconds)
        old.__exit__(None, None, None)

    with hold(requests, retry_seconds=5.0, sleep=release_old):
        pass

    assert sleeps == [instance_lock.RETRY_INTERVAL_SECONDS]


def test_a_killed_process_releases_its_lock(tmp_path: Path) -> None:
    """The child runs with a different environment and still meets us; after a
    SIGKILL its `.lock` file stays, but no longer excludes anyone."""
    data = tmp_path / "data"
    home = tmp_path / "home"
    holder = textwrap.dedent(
        f"""
        import time
        from pathlib import Path
        from app import instance_lock
        instance_lock._passwd_home = lambda uid: Path({str(home)!r})
        with instance_lock.hold(
            instance_lock.server_locks(Path({str(data)!r}), Path({str(data)!r}) / "x")
        ):
            print("ready", flush=True)
            time.sleep(60)
        """
    )
    env = os.environ | {name: str(tmp_path / "child" / name) for name in ENV_NAMES}
    child = subprocess.Popen(
        [sys.executable, "-c", holder],
        cwd=config.BACKEND_DIR,
        env=env,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        with pytest.raises(LockBusy) as raised:
            with hold(_server(data, tmp_path / "other.db")):
                pass
        assert raised.value.pid == child.pid
    finally:
        child.send_signal(signal.SIGKILL)
        child.wait(10)

    assert lock_file(DATA, data).exists()
    with hold(_server(data, tmp_path / "other.db")):
        pass


# --- One root per user, independent of the environment -------------------------------

# Variables that must never change where locks live.
ENV_NAMES = [
    "XDG_STATE_HOME",
    "XDG_RUNTIME_DIR",
    "HOME",
    "TMPDIR",
    "AUTOPUBLISHER_DATA_DIR",
    "AUTOPUBLISHER_CONFIG",
]


def test_root_is_under_the_password_database_home(isolate_lock_root: Path) -> None:
    assert locks_dir() == isolate_lock_root


@pytest.mark.parametrize("name", ENV_NAMES)
def test_root_ignores_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    before = locks_dir()
    monkeypatch.setenv(name, str(tmp_path / "elsewhere"))
    assert locks_dir() == before


@pytest.mark.parametrize("name", ENV_NAMES)
@pytest.mark.parametrize("same", ["data_dir", "database"])
def test_another_environment_cannot_bypass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same: str, name: str
) -> None:
    shared = tmp_path / "shared"
    first = _server(shared, tmp_path / "one.db")
    second = (
        _server(shared, tmp_path / "two.db")
        if same == "data_dir"
        else _server(tmp_path / "other", tmp_path / "one.db")
    )
    monkeypatch.setenv(name, str(tmp_path / "env-a"))
    with hold(first):
        monkeypatch.setenv(name, str(tmp_path / "env-b"))
        with pytest.raises(LockBusy) as raised:
            with hold(second):
                pass

    assert raised.value.kind is (DATA if same == "data_dir" else DB)


def test_symlinked_home_is_canonicalized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolate_lock_root: Path
) -> None:
    link = tmp_path / "home-link"
    link.symlink_to(tmp_path / "home")
    monkeypatch.setattr(instance_lock, "_passwd_home", lambda uid: link)

    assert locks_dir() == isolate_lock_root


def _unsafe_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    if case == "no_passwd_entry":

        def missing(uid: int) -> Path:
            raise KeyError(uid)

        monkeypatch.setattr(instance_lock, "_passwd_home", missing)
    elif case == "relative_home":
        monkeypatch.setattr(instance_lock, "_passwd_home", lambda uid: Path("home"))
    elif case == "missing_home":
        monkeypatch.setattr(
            instance_lock, "_passwd_home", lambda uid: tmp_path / "gone"
        )
    elif case == "other_owner":
        # The home belongs to the real user, not to the effective one we pretend.
        monkeypatch.setattr(os, "geteuid", lambda: os.getuid() + 1)
    elif case == "world_writable_home":
        os.chmod(tmp_path / "home", 0o777)
    elif case == "open_root":
        root = locks_dir()
        root.mkdir(parents=True)
        os.chmod(root, 0o750)
    elif case == "symlinked_root":
        root = locks_dir()
        root.parent.mkdir(parents=True)
        (tmp_path / "elsewhere").mkdir(mode=0o700)
        root.symlink_to(tmp_path / "elsewhere")


@pytest.mark.parametrize(
    "case",
    [
        "no_passwd_entry",
        "relative_home",
        "missing_home",
        "other_owner",
        "world_writable_home",
        "open_root",
        "symlinked_root",
    ],
)
def test_unsafe_root_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    _unsafe_home(tmp_path, monkeypatch, case)

    with pytest.raises(LockRootUnsafe):
        with hold([(DATA, tmp_path / "data")]):
            pass
    assert not (tmp_path / "elsewhere").exists() or not any(
        (tmp_path / "elsewhere").iterdir()
    )


def test_swapping_the_data_dir_does_not_move_the_lock(tmp_path: Path) -> None:
    """What a restore will do: rename the directory away and put another in place."""
    data = tmp_path / "data"
    data.mkdir()
    requests = _server(data, data / "autopublisher.db")
    with hold(requests):
        before = sorted(locks_dir().iterdir())
        data.rename(tmp_path / "data.old")
        data.mkdir()
        with pytest.raises(LockBusy):
            with hold(requests):
                pass
        assert sorted(locks_dir().iterdir()) == before
    with hold(requests):
        pass


# --- Server lifespan (T006) ---------------------------------------------------------


def _app(db_path: Path) -> TestClient:
    return TestClient(
        create_app(
            db_path,
            db_path.parent / "media",
            tiktok_credential_store=InMemoryCredentialStore(),
            instagram_credential_store=InMemoryCredentialStore(),
            threads_credential_store=InMemoryCredentialStore(),
        )
    )


@pytest.fixture
def no_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(instance_lock, "SERVER_RETRY_SECONDS", 0.0)


@pytest.mark.usefixtures("no_retry")
def test_second_server_on_the_same_database_fails_at_startup(db_path: Path) -> None:
    with _app(db_path) as first:
        assert first.get("/health").status_code == 200
        with pytest.raises(LockBusy, match="already running"):
            with _app(db_path):
                pass
        assert first.get("/health").status_code == 200


@pytest.mark.usefixtures("no_retry")
def test_second_server_on_the_same_db_via_another_data_dir_fails(
    tmp_path: Path, db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTOPUBLISHER_DATA_DIR", str(tmp_path / "one"))
    first = _app(db_path)
    monkeypatch.setenv("AUTOPUBLISHER_DATA_DIR", str(tmp_path / "two"))
    second = _app(db_path)

    with first:
        with pytest.raises(LockBusy) as raised:
            with second:
                pass

    assert raised.value.kind is DB
    assert str(db_path) in str(raised.value)


def test_sequential_servers_work(db_path: Path) -> None:
    for _ in range(2):
        with _app(db_path) as client:
            assert client.get("/health").status_code == 200
    assert not observe(DB, db_path).held
