import subprocess

import pytest

from bambu_filament_profiles import fetch
from bambu_filament_profiles.fetch import FetchError, Source, fetch_all, fetch_source, read_lock, write_lock


def git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def upstream(tmp_path):
    repo = tmp_path / "upstream"
    (repo / "data").mkdir(parents=True)
    (repo / "data" / "a.json").write_text("{}", encoding="utf-8")
    (repo / "other.txt").write_text("do not fetch", encoding="utf-8")
    git("init", "-q", "-b", "main", cwd=repo)
    git("add", ".", cwd=repo)
    git("commit", "-q", "-m", "one", cwd=repo)
    git("config", "uploadpack.allowFilter", "true", cwd=repo)
    git("config", "uploadpack.allowAnySHA1InWant", "true", cwd=repo)
    return repo


def head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def test_fetch_source_sparse_and_pinned(upstream, tmp_path):
    source = Source("demo", upstream.as_uri(), "MIT", ("/data/*.json",), "Test")
    first = head(upstream)
    commit = fetch_source(source, tmp_path / "cache", "HEAD")
    assert commit == first
    checkout = tmp_path / "cache" / "demo"
    assert (checkout / "data" / "a.json").exists()
    assert not (checkout / "other.txt").exists()
    (upstream / "data" / "b.json").write_text("{}", encoding="utf-8")
    git("add", ".", cwd=upstream)
    git("commit", "-q", "-m", "two", cwd=upstream)
    assert fetch_source(source, tmp_path / "cache", first) == first  # pinned commit
    assert not (checkout / "data" / "b.json").exists()
    assert fetch_source(source, tmp_path / "cache", "HEAD") == head(upstream)
    assert (checkout / "data" / "b.json").exists()


def test_fetch_all_uses_lock(monkeypatch, upstream, tmp_path):
    monkeypatch.setattr(fetch, "SOURCES", {"demo": Source("demo", upstream.as_uri(), "MIT", ("/data/*.json",), "Test")})
    logs = []
    lock = fetch_all(tmp_path / "cache", {}, log=logs.append)
    assert lock["demo"]["commit"] == head(upstream) and lock["demo"]["license"] == "MIT"
    assert "@ HEAD" in logs[0]
    again = fetch_all(tmp_path / "cache", lock, log=logs.append)
    assert again == lock and lock["demo"]["commit"][:12] in logs[-1]
    assert fetch_all(tmp_path / "cache", lock, names={"andere"}, log=logs.append) == lock


def test_fetch_error(tmp_path):
    source = Source("broken", (tmp_path / "does-not-exist").as_uri(), "MIT", ("/x",), "Test")
    with pytest.raises(FetchError, match="failed"):
        fetch_source(source, tmp_path / "cache", "HEAD")


def test_lock_roundtrip(tmp_path):
    path = tmp_path / "lock.json"
    assert read_lock(path) == {}
    write_lock(path, {"b": {"commit": "2"}, "a": {"commit": "1"}})
    assert read_lock(path) == {"a": {"commit": "1"}, "b": {"commit": "2"}}
    assert path.read_text(encoding="utf-8").index('"a"') < path.read_text(encoding="utf-8").index('"b"')


def test_all_sources_have_licenses():
    assert set(fetch.SOURCES) == {"bambu", "orca", "ofd", "prusa", "spoolman", "cura"}
    assert all(s.license and s.patterns for s in fetch.SOURCES.values())


def test_missing_git_is_explained(tmp_path):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    with pytest.raises(FetchError, match="install Git"):
        fetch._git(["status"], tmp_path, run=no_git)


def test_write_lock_creates_folder(tmp_path):
    path = tmp_path / "new" / "lock.json"
    write_lock(path, {"a": {"commit": "1"}})
    assert read_lock(path) == {"a": {"commit": "1"}}
