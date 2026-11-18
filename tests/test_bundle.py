"""Lambda bundling: packages come from the hashed lockfile for the Lambda's platform, are cached, and fail loudly."""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from infra import bundle


def lockfile(tmp_path: Path, text: str = "cryptography==1 --hash=sha256:00\n") -> Path:
    path = tmp_path / "requirements-lambda.txt"
    path.write_text(text)
    return path


def fake_pip(monkeypatch: pytest.MonkeyPatch, calls: list[list[str]], returncode: int = 0) -> None:
    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        target = Path(command[command.index("--target") + 1])
        target.mkdir(parents=True, exist_ok=True)
        (target / "cryptography").mkdir()
        return subprocess.CompletedProcess(command, returncode, "", "pip said no" if returncode else "")

    monkeypatch.setattr(bundle.subprocess, "run", run)


def test_installs_for_the_lambda_platform_from_the_hashed_lockfile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    fake_pip(monkeypatch, calls)
    target = bundle.install_dependencies(lockfile(tmp_path), tmp_path / "cache")
    assert (target / "cryptography").is_dir() and not target.name.endswith(".tmp")
    (command,) = calls
    for expected in ("--require-hashes", "--only-binary=:all:", "--no-deps", "--no-compile"):
        assert expected in command
    assert command[command.index("--python-version") + 1] == "3.14"
    assert [command[i + 1] for i, c in enumerate(command) if c == "--platform"] == list(bundle.PLATFORMS)
    assert all(p.endswith("aarch64") for p in bundle.PLATFORMS)


def test_a_second_call_with_the_same_lockfile_uses_the_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    fake_pip(monkeypatch, calls)
    first = bundle.install_dependencies(lockfile(tmp_path), tmp_path / "cache")
    assert bundle.install_dependencies(lockfile(tmp_path), tmp_path / "cache") == first
    assert len(calls) == 1


def test_a_changed_lockfile_installs_again(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    fake_pip(monkeypatch, calls)
    one = bundle.install_dependencies(lockfile(tmp_path), tmp_path / "cache")
    two = bundle.install_dependencies(lockfile(tmp_path, "cryptography==2 --hash=sha256:11\n"), tmp_path / "cache")
    assert one != two and len(calls) == 2


def test_a_failed_install_raises_and_leaves_no_half_built_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_pip(monkeypatch, [], returncode=1)
    with pytest.raises(RuntimeError, match="pip said no"):
        bundle.install_dependencies(lockfile(tmp_path), tmp_path / "cache")
    assert list((tmp_path / "cache").iterdir()) == []


def test_local_bundling_copies_the_packages_and_the_code_without_pycache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "backend"
    (source / "ingest" / "__pycache__").mkdir(parents=True)
    (source / "ingest" / "handler.py").write_text("x = 1\n")
    (source / "ingest" / "__pycache__" / "handler.cpython-314.pyc").write_bytes(b"\0")
    packages = tmp_path / "packages"
    (packages / "cryptography").mkdir(parents=True)
    monkeypatch.setattr(bundle, "install_dependencies", lambda requirements: packages)
    out = tmp_path / "out"
    out.mkdir()
    assert bundle.LocalDependencies(source, tmp_path / "req.txt").try_bundle(str(out), {"image": "unused"}) is True
    assert (out / "cryptography").is_dir() and (out / "ingest" / "handler.py").read_text() == "x = 1\n"
    assert not (out / "ingest" / "__pycache__").exists()


def test_the_lockfile_pins_cryptography_with_hashes() -> None:
    text = Path("requirements-lambda.txt").read_text()
    assert "cryptography==" in text and "--hash=sha256:" in text


def test_the_cache_key_covers_the_platforms_and_python_version(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []
    fake_pip(monkeypatch, calls)
    one = bundle.install_dependencies(lockfile(tmp_path), tmp_path / "cache")
    monkeypatch.setattr(bundle, "PYTHON_VERSION", "3.15")
    two = bundle.install_dependencies(lockfile(tmp_path), tmp_path / "cache")
    assert one != two and len(calls) == 2


def test_a_parallel_build_that_finishes_first_is_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache = tmp_path / "cache"
    requirements = lockfile(tmp_path)
    wanted = requirements.read_bytes() + repr((bundle.PLATFORMS, bundle.PYTHON_VERSION)).encode()

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        (Path(command[command.index("--target") + 1]) / "cryptography").mkdir(parents=True, exist_ok=True)
        winner = cache / bundle.hashlib.sha256(wanted).hexdigest()[:16]
        winner.mkdir()  # another synth got there first
        (winner / "cryptography").mkdir()
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(bundle.subprocess, "run", run)
    target = bundle.install_dependencies(requirements, cache)
    assert (target / "cryptography").is_dir()
    assert [p.name for p in cache.iterdir()] == [target.name]  # our own temporary folder was removed
