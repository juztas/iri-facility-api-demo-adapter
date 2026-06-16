"""Sandbox + subprocess helpers backing the filesystem domain demo adapter.

All filesystem operations are confined to a single temp directory
(PathSandbox) so the demo is safe to run without a real facility filesystem
behind it.
"""
import datetime
import grp
import os
import pwd
import stat
import subprocess

from fastapi import HTTPException

from app.apilogger import get_stream_logger
from app.config import LOG_LEVEL
from app.routers.filesystem import models as filesystem_models

logger = get_stream_logger(__name__, LOG_LEVEL)


class CommandError(RuntimeError):
    """Raised when an external subprocess command fails."""

    def __init__(self, cmd, returncode=None, stdout=None, stderr=None):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

        super().__init__(f"Command failed: {cmd} (rc={returncode})")


class PathSandbox:
    """A simple sandbox for file operations."""
    _base_temp_dir = None

    @classmethod
    def get_base_temp_dir(cls):
        """Get the base temporary directory for the sandbox."""
        if cls._base_temp_dir is None:
            # Create in system temp with a fixed name
            cls._base_temp_dir = os.path.join(os.getcwd(), "iri_sandbox")
            os.makedirs(cls._base_temp_dir, exist_ok=True)

            # create a test file
            with open(f"{cls._base_temp_dir}/test.txt", encoding="utf-8", mode="w") as f:
                f.write("hello world")
            logger.info(f"Created test file in sandbox: {cls._base_temp_dir}/test.txt")
        return cls._base_temp_dir


def validate_path(path: str, allow_symlinks: bool = True) -> str:
    """Validate that the given path is within the sandbox base directory and optionally check for symlinks."""
    basedir = PathSandbox.get_base_temp_dir()
    real_path = os.path.realpath(os.path.join(basedir, path))

    # Check within sandbox
    if not real_path.startswith(basedir + os.sep) and real_path != basedir:
        raise HTTPException(status_code=400, detail=f"Path outside sandbox: {path}")

    # Optionally block symlinks that point outside sandbox
    if not allow_symlinks and os.path.islink(os.path.join(basedir, path)):
        link_target = os.readlink(os.path.join(basedir, path))
        if os.path.isabs(link_target):
            raise HTTPException(status_code=400, detail=f"Absolute symlink not allowed: {path}")

    return real_path


def run_command(args, *, shell: bool = False, timeout: int | None = 3600, text: bool = True) -> subprocess.CompletedProcess:
    """
    Run a subprocess command and catch exceptions.
    Raises CommandError on failure with captured diagnostics.
    """
    try:
        return subprocess.run(args, shell=shell, capture_output=True, text=text, check=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        logger.warning(f"Command timed out: {args} (after {timeout} seconds)")
        raise CommandError(cmd=args, returncode=None, stdout=exc.stdout, stderr=exc.stderr) from exc
    except subprocess.CalledProcessError as exc:
        logger.warning(f"Command failed: {args} (rc={exc.returncode})\nstdout: {exc.stdout}\nstderr: {exc.stderr}")
        raise CommandError(cmd=args, returncode=exc.returncode, stdout=exc.stdout, stderr=exc.stderr) from exc
    except OSError as exc:
        logger.warning(f"OS error running command: {args}\nError: {exc}")
        raise CommandError(cmd=args, returncode=None, stdout=None, stderr=str(exc)) from exc


def file_to_model(path: str) -> filesystem_models.File:
    """Validate path and build a filesystem_models.File describing it."""
    rp = validate_path(path)
    file_stat = os.stat(rp)  # Use lstat to not follow symlinks

    # Get file type
    if stat.S_ISDIR(file_stat.st_mode):
        file_type = "directory"
    elif stat.S_ISLNK(file_stat.st_mode):
        file_type = "symlink"
    elif stat.S_ISREG(file_stat.st_mode):
        file_type = "file"
    else:
        file_type = "other"

    # Get link target if it's a symlink
    link_target = None
    if stat.S_ISLNK(file_stat.st_mode):
        link_target = os.readlink(rp)

    # Get user and group names
    user = pwd.getpwuid(file_stat.st_uid).pw_name
    group = grp.getgrgid(file_stat.st_gid).gr_name

    # Get permissions in rwxrwxrwx format
    permissions = stat.filemode(file_stat.st_mode)

    # Get last modified time
    last_modified = datetime.datetime.fromtimestamp(file_stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    # Get size
    size = str(file_stat.st_size)
    data = dict(
        name=os.path.basename(rp),
        type=file_type,
        user=user,
        group=group,
        permissions=permissions,
        last_modified=last_modified,
        size=size,
    )

    if link_target is not None:
        data["link_target"] = link_target

    return filesystem_models.File(**data)
