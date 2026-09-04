from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from .models import AcquiredRepository, SourceError, SourceSpec


DEFAULT_MAX_FILES = 20_000
DEFAULT_MAX_BYTES = 250 * 1024 * 1024
DEFAULT_DOWNLOAD_BYTES = 100 * 1024 * 1024
_GITHUB_COMPONENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_SHA = re.compile(r"^[0-9a-fA-F]{40}$")


def parse_source(value: str, explicit_ref: str | None = None) -> SourceSpec:
    value = value.strip()
    local = Path(value).expanduser()
    if local.exists():
        resolved = local.resolve()
        if not resolved.is_dir():
            raise SourceError(f"local source is not a directory: {value}")
        return SourceSpec(
            original=value,
            kind="local",
            canonical_url=resolved.as_uri(),
            ref=explicit_ref,
            local_path=resolved,
        )

    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or parsed.hostname is None or parsed.hostname.lower() != "github.com":
        raise SourceError("source must be an existing local directory or an https://github.com/owner/repo URL")
    if parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise SourceError("GitHub URL must not contain credentials, a port, query, or fragment")
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise SourceError("GitHub URL must include both owner and repository")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo or not _GITHUB_COMPONENT.fullmatch(owner) or not _GITHUB_COMPONENT.fullmatch(repo):
        raise SourceError("GitHub owner and repository contain unsupported characters")
    if owner in {".", ".."} or repo in {".", ".."}:
        raise SourceError("GitHub owner and repository may not be traversal segments")

    url_ref: str | None = None
    subpath: str | None = None
    if len(parts) > 2:
        if len(parts) < 4 or parts[2] != "tree":
            raise SourceError("only repository-root and /tree/<ref>/<path> GitHub URLs are supported")
        url_ref = parts[3]
        remainder = parts[4:]
        if any(part in {".", ".."} for part in remainder):
            raise SourceError("GitHub tree path may not contain traversal segments")
        subpath = "/".join(remainder) or None

    ref = explicit_ref or url_ref
    if ref and ("\x00" in ref or ref.startswith("-") or ".." in ref.split("/")):
        raise SourceError("unsafe Git ref")
    canonical = f"https://github.com/{owner}/{repo}"
    return SourceSpec(
        original=value,
        kind="github",
        canonical_url=canonical,
        owner=owner,
        repo=repo,
        ref=ref,
        subpath=subpath,
    )


@contextlib.contextmanager
def acquire_repository(
    source: SourceSpec,
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Iterator[AcquiredRepository]:
    if source.kind == "local":
        assert source.local_path is not None
        revision = _local_revision(source.local_path)
        yield AcquiredRepository(source.local_path, source, revision, "local")
        return

    with tempfile.TemporaryDirectory(prefix="skill-hunter-") as temp_name:
        temp = Path(temp_name)
        extracted = temp / "repo"
        warnings: list[str] = []
        try:
            revision, git_warnings = _acquire_with_git(source, temp / "git", extracted, max_files, max_bytes)
            warnings.extend(git_warnings)
            method = "git-no-checkout"
        except SourceError as git_error:
            warnings.append(f"git acquisition unavailable; used bounded GitHub archive fallback ({git_error})")
            if extracted.exists():
                shutil.rmtree(extracted, ignore_errors=True)
            try:
                revision = _acquire_with_github_archive(source, extracted, max_files, max_bytes)
            except SourceError as archive_error:
                raise SourceError(
                    f"git acquisition failed ({git_error}); GitHub archive fallback failed ({archive_error})"
                ) from archive_error
            method = "github-archive"

        if source.subpath:
            candidate = _lexical_join(extracted, source.subpath)
            if not candidate.exists():
                raise SourceError(f"GitHub tree subpath does not exist at revision {revision}: {source.subpath}")
        yield AcquiredRepository(extracted, source, revision, method, warnings)


def _git_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
        env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    return env


def _run_git(args: list[str], *, cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-c", "core.hooksPath=/dev/null", *args],
            cwd=cwd,
            env=_git_environment(),
            text=True,
            encoding="utf-8",
            errors="surrogateescape",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SourceError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise SourceError("git operation timed out") from exc


def _acquire_with_git(
    source: SourceSpec,
    git_dir: Path,
    extracted: Path,
    max_files: int,
    max_bytes: int,
) -> tuple[str, list[str]]:
    assert source.owner and source.repo
    remote = f"https://github.com/{source.owner}/{source.repo}.git"
    clone_args = ["clone", "--no-checkout", "--depth", "1"]
    direct_sha = bool(source.ref and _SHA.fullmatch(source.ref))
    if source.ref and not direct_sha:
        clone_args.extend(["--branch", source.ref])
    clone_args.extend(["--", remote, str(git_dir)])
    result = _run_git(clone_args)
    if result.returncode != 0:
        reason = _safe_git_error(result.stderr)
        raise SourceError(f"git clone failed: {reason}")

    revision_ref = "HEAD"
    if direct_sha:
        assert source.ref
        fetch = _run_git(["fetch", "--depth", "1", "origin", source.ref], cwd=git_dir)
        if fetch.returncode != 0:
            raise SourceError(f"git fetch failed: {_safe_git_error(fetch.stderr)}")
        revision_ref = "FETCH_HEAD"

    revision_result = _run_git(["rev-parse", f"{revision_ref}^{{commit}}"], cwd=git_dir)
    revision = revision_result.stdout.strip().lower()
    if revision_result.returncode != 0 or not _SHA.fullmatch(revision):
        raise SourceError("could not resolve an immutable commit SHA")

    warnings = _materialize_git_tree(git_dir, revision, extracted, max_files=max_files, max_bytes=max_bytes)
    return revision, warnings


def _materialize_git_tree(
    git_dir: Path,
    revision: str,
    extracted: Path,
    *,
    max_files: int,
    max_bytes: int,
) -> list[str]:
    """Read exact Git objects without checkout filters, hooks, or export-ignore rules."""
    listing = _run_git(["ls-tree", "-rz", "--full-tree", revision], cwd=git_dir)
    if listing.returncode != 0:
        raise SourceError(f"git tree listing failed: {_safe_git_error(listing.stderr)}")
    entries: list[tuple[str, str, str]] = []
    warnings: list[str] = []
    for record in listing.stdout.split("\0"):
        if not record:
            continue
        try:
            metadata, name = record.split("\t", 1)
            mode, object_type, object_id = metadata.split(" ", 2)
        except ValueError as exc:
            raise SourceError("git returned a malformed tree entry") from exc
        _safe_member_parts(name)
        if object_type == "commit" or mode == "160000":
            warnings.append(f"submodule content was not fetched: {name}")
            continue
        if object_type != "blob" or mode not in {"100644", "100755", "120000"}:
            raise SourceError(f"unsupported Git tree entry: {name} ({mode} {object_type})")
        entries.append((mode, object_id, name))
        if len(entries) > max_files:
            raise SourceError(f"repository exceeds file limit ({max_files})")

    extracted.mkdir(parents=True, exist_ok=False)
    command = ["git", "-c", "core.hooksPath=/dev/null", "-C", str(git_dir), "cat-file", "--batch"]
    try:
        process = subprocess.Popen(
            command,
            env=_git_environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise SourceError(f"could not start git object reader: {exc}") from exc
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    total = 0
    try:
        for mode, object_id, name in entries:
            process.stdin.write(object_id.encode("ascii") + b"\n")
            process.stdin.flush()
            header = process.stdout.readline()
            parts = header.rstrip(b"\n").split(b" ")
            if len(parts) != 3 or parts[1] != b"blob":
                raise SourceError(f"could not read Git blob for {name}")
            try:
                size = int(parts[2])
            except ValueError as exc:
                raise SourceError(f"Git returned an invalid blob size for {name}") from exc
            total += size
            if total > max_bytes:
                raise SourceError(f"repository exceeds extracted byte limit ({max_bytes})")
            destination = extracted.joinpath(*_safe_member_parts(name))
            _ensure_no_symlink_parent(extracted, destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if mode == "120000":
                payload = _read_exact(process.stdout, size)
                try:
                    link_target = payload.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise SourceError(f"symlink target is not UTF-8: {name}") from exc
                os.symlink(link_target, destination)
            else:
                remaining = size
                with destination.open("xb") as output:
                    while remaining:
                        chunk = process.stdout.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise SourceError(f"truncated Git blob for {name}")
                        output.write(chunk)
                        remaining -= len(chunk)
                os.chmod(destination, 0o755 if mode == "100755" else 0o644)
            if process.stdout.read(1) != b"\n":
                raise SourceError(f"malformed Git blob framing for {name}")
        process.stdin.close()
    except (OSError, SourceError) as exc:
        process.kill()
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass
        if isinstance(exc, SourceError):
            raise
        raise SourceError(f"Git object materialization failed: {type(exc).__name__}") from exc
    stderr = process.stderr.read().decode("utf-8", errors="replace")
    returncode = process.wait()
    process.stdout.close()
    process.stderr.close()
    if returncode != 0:
        raise SourceError(f"git object reader failed: {_safe_git_error(stderr)}")
    return warnings


def _read_exact(stream: object, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise SourceError("truncated Git object stream")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _safe_git_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    message = lines[-1] if lines else "unknown error"
    message = re.sub(r"https://[^@\s]+@", "https://[redacted]@", message)
    return "".join(char for char in message if ord(char) >= 32)[:300]


def _safe_member_parts(name: str) -> tuple[str, ...]:
    if "\x00" in name or "\\" in name or any(ord(char) < 32 or 0xD800 <= ord(char) <= 0xDFFF for char in name):
        raise SourceError(f"unsafe archive path: {name!r}")
    pure = PurePosixPath(name)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise SourceError(f"unsafe archive path: {name!r}")
    if pure.parts and re.match(r"^[A-Za-z]:", pure.parts[0]):
        raise SourceError(f"unsafe archive drive path: {name!r}")
    return pure.parts


def _lexical_join(root: Path, relative: str) -> Path:
    parts = _safe_member_parts(relative)
    return root.joinpath(*parts)


def _ensure_no_symlink_parent(root: Path, destination: Path) -> None:
    current = root
    for part in destination.relative_to(root).parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise SourceError(f"archive entry would traverse a symlink parent: {destination.relative_to(root)}")


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "skill-hunter/0.1"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _read_bounded_response(response: object, limit: int) -> bytes:
    stream = response
    content_length = getattr(response, "headers", {}).get("Content-Length")
    if content_length and int(content_length) > limit:
        raise SourceError(f"download exceeds byte limit ({limit})")
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = stream.read(min(1024 * 1024, limit - total + 1))
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise SourceError(f"download exceeds byte limit ({limit})")
        chunks.append(chunk)
    return b"".join(chunks)


def _acquire_with_github_archive(
    source: SourceSpec,
    extracted: Path,
    max_files: int,
    max_bytes: int,
) -> str:
    assert source.owner and source.repo
    ref = source.ref or "HEAD"
    encoded_ref = urllib.parse.quote(ref, safe="")
    api_url = f"https://api.github.com/repos/{source.owner}/{source.repo}/commits/{encoded_ref}"
    try:
        request = urllib.request.Request(api_url, headers=_github_headers())
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(_read_bounded_response(response, 2 * 1024 * 1024))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        raise SourceError(f"GitHub commit lookup failed: {type(exc).__name__}") from exc
    if not isinstance(payload, dict):
        raise SourceError("GitHub commit lookup returned an unexpected response")
    revision = str(payload.get("sha", "")).lower()
    if not _SHA.fullmatch(revision):
        raise SourceError("GitHub did not return a valid commit SHA")

    archive_url = f"https://codeload.github.com/{source.owner}/{source.repo}/zip/{revision}"
    try:
        request = urllib.request.Request(archive_url, headers=_github_headers())
        with urllib.request.urlopen(request, timeout=60) as response:
            archive_bytes = _read_bounded_response(response, DEFAULT_DOWNLOAD_BYTES)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SourceError(f"GitHub archive download failed: {type(exc).__name__}") from exc

    extracted.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            _extract_zip_safely(archive, extracted, max_files=max_files, max_bytes=max_bytes)
    except (zipfile.BadZipFile, OSError, UnicodeError) as exc:
        raise SourceError(f"GitHub archive extraction failed: {type(exc).__name__}") from exc
    return revision


def _extract_zip_safely(archive: zipfile.ZipFile, destination: Path, *, max_files: int, max_bytes: int) -> None:
    infos = archive.infolist()
    if len(infos) > max_files:
        raise SourceError(f"archive exceeds file limit ({max_files})")
    total = sum(info.file_size for info in infos)
    if total > max_bytes:
        raise SourceError(f"archive exceeds extracted byte limit ({max_bytes})")

    roots = {PurePosixPath(info.filename).parts[0] for info in infos if PurePosixPath(info.filename).parts}
    prefix = next(iter(roots)) if len(roots) == 1 else None
    for info in infos:
        raw_parts = _safe_member_parts(info.filename.rstrip("/"))
        parts = raw_parts[1:] if prefix and raw_parts and raw_parts[0] == prefix else raw_parts
        if not parts:
            continue
        target = destination.joinpath(*parts)
        _ensure_no_symlink_parent(destination, target)
        mode = (info.external_attr >> 16) & 0xFFFF
        is_directory = info.is_dir()
        is_symlink = stat.S_IFMT(mode) == stat.S_IFLNK
        if is_directory:
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        data = archive.read(info)
        if is_symlink:
            try:
                link_target = data.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise SourceError(f"archive symlink target is not UTF-8: {info.filename}") from exc
            os.symlink(link_target, target)
            continue
        with target.open("xb") as output:
            output.write(data)
        if mode:
            os.chmod(target, mode & 0o777)


def _local_revision(root: Path) -> str:
    result = _run_git(["-C", str(root), "rev-parse", "HEAD"])
    revision = result.stdout.strip().lower()
    if result.returncode == 0 and _SHA.fullmatch(revision):
        return revision

    digest = hashlib.sha1()
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(name for name in directories if name != ".git")
        for name in list(directories):
            path = Path(current) / name
            if path.is_symlink():
                relative = path.relative_to(root).as_posix()
                digest.update(relative.encode())
                digest.update(b"L")
                digest.update(os.readlink(path).encode())
                directories.remove(name)
        for name in sorted(files):
            path = Path(current) / name
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode())
            if path.is_symlink():
                digest.update(os.readlink(path).encode())
            elif path.is_file():
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
    return f"local-tree:{digest.hexdigest()}"
