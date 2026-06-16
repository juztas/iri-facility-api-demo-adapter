"""Filesystem domain demo adapter: ls/stat/head/tail/chmod/chown/mkdir/symlink/rm/mv/cp/compress/extract/upload/download.

All operations are confined to a sandbox directory (see .sandbox.PathSandbox)
so this is safe to run without a real facility filesystem behind it.
"""
import base64
import glob
import os
import pathlib
import subprocess

from fastapi import HTTPException

from app.routers.filesystem import facility_adapter, models as filesystem_models
from app.routers.status import models as status_models
from app.types.user import User

from ..common import DemoAuthMixin
from .sandbox import PathSandbox, file_to_model, run_command, validate_path


def _headtail(
    cmd: str,
    path: str,
    file_bytes: int | None,
    lines: int | None,
    skip_heading: bool = False,
    skip_trailing: bool = False,
) -> str:
    args = [cmd]

    if cmd == "tail" and skip_heading:
        if file_bytes is not None:
            args.extend(["-c", f"+{file_bytes + 1}"])
        elif lines is not None:
            args.extend(["-n", f"+{lines + 1}"])
    if cmd == "head" and skip_trailing:
        if file_bytes is not None:
            args.extend(["-c", f"-{file_bytes}"])
        elif lines is not None:
            args.extend(["-n", f"-{lines}"])
    else:
        if file_bytes is not None:
            args.extend(["-c", str(file_bytes)])
        elif lines is not None:
            args.extend(["-n", str(lines)])

    rp = validate_path(path)
    args.append(rp)

    result = run_command(args)
    return result.stdout


class FilesystemDemoAdapter(DemoAuthMixin, facility_adapter.FacilityAdapter):
    """Demo implementation of the filesystem domain, sandboxed to a local temp dir."""

    async def chmod(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, request_model: filesystem_models.PutFileChmodRequest) -> filesystem_models.PutFileChmodResponse:
        rp = validate_path(request_model.path)
        os.chmod(rp, int(request_model.mode, 8))
        return filesystem_models.PutFileChmodResponse(output=file_to_model(rp))

    async def chown(
        self: "FilesystemDemoAdapter",
        resource: status_models.Resource,
        user: User,
        request_model: filesystem_models.PutFileChownRequest,
    ) -> filesystem_models.PutFileChownResponse:
        rp = validate_path(request_model.path)
        os.chown(rp, request_model.owner, request_model.group)
        return filesystem_models.PutFileChownResponse(output=file_to_model(rp))

    async def ls(
        self: "FilesystemDemoAdapter",
        resource: status_models.Resource,
        user: User,
        path: str,
        show_hidden: bool,
        numeric_uid: bool,
        recursive: bool,
        dereference: bool,
    ) -> filesystem_models.GetDirectoryLsResponse:
        rp = validate_path(path)
        files = glob.glob(rp, recursive=recursive)
        return filesystem_models.GetDirectoryLsResponse(output=[file_to_model(f) for f in files])

    async def head(
        self: "FilesystemDemoAdapter",
        resource: status_models.Resource,
        user: User,
        path: str,
        file_bytes: int | None,
        lines: int | None,
        skip_trailing: bool = False,
    ) -> filesystem_models.GetFileHeadResponse:
        content = _headtail("head", path, file_bytes, lines, skip_trailing=skip_trailing)

        fc = filesystem_models.FileContent(
            content=content,
            content_type=(filesystem_models.ContentUnit.bytes
                          if file_bytes is not None
                          else filesystem_models.ContentUnit.lines),
            start_position=0,
            end_position=len(content))

        return filesystem_models.GetFileHeadResponse(output=fc)

    async def tail(
        self: "FilesystemDemoAdapter",
        resource: status_models.Resource,
        user: User,
        path: str,
        file_bytes: int | None,
        lines: int | None,
        skip_heading: bool = False,
    ) -> filesystem_models.GetFileTailResponse:
        content = _headtail("tail", path, file_bytes, lines, skip_heading=skip_heading)

        fc = filesystem_models.FileContent(
            content=content,
            content_type=(filesystem_models.ContentUnit.bytes
                          if file_bytes is not None
                          else filesystem_models.ContentUnit.lines),
            start_position=0,
            end_position=len(content))

        return filesystem_models.GetFileTailResponse(output=fc)

    async def view(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, path: str, size: int, offset: int) -> filesystem_models.GetViewFileResponse:
        rp = validate_path(path)
        result = run_command(f"tail -c +{offset + 1} {rp} | head -c {size}", shell=True)
        content = result.stdout
        return filesystem_models.GetViewFileResponse(
            output=filesystem_models.FileContent(
                content=content,
                content_type=filesystem_models.ContentUnit.bytes,
                start_position=offset,
                end_position=offset + len(content)
            ),
        )

    async def checksum(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, path: str) -> filesystem_models.GetFileChecksumResponse:
        rp = validate_path(path)
        result = run_command(["sha256sum", rp])
        checksum = result.stdout.split()[0]
        return filesystem_models.GetFileChecksumResponse(
            output=filesystem_models.FileChecksum(
                checksum=checksum,
            )
        )

    async def file(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, path: str) -> filesystem_models.GetFileTypeResponse:
        rp = validate_path(path)
        result = run_command(["file", "-b", rp])
        return filesystem_models.GetFileTypeResponse(
            output=result.stdout.strip(),
        )

    async def stat(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, path: str, dereference: bool) -> filesystem_models.GetFileStatResponse:
        rp = validate_path(path)
        if dereference:
            stat_info = os.stat(rp)
        else:
            stat_info = os.lstat(rp)
        return filesystem_models.GetFileStatResponse(
            output=filesystem_models.FileStat(
                mode=stat_info.st_mode,
                ino=stat_info.st_ino,
                dev=stat_info.st_dev,
                nlink=stat_info.st_nlink,
                uid=stat_info.st_uid,
                gid=stat_info.st_gid,
                size=stat_info.st_size,
                atime=int(stat_info.st_atime),
                ctime=int(stat_info.st_ctime),
                mtime=int(stat_info.st_mtime),
            )
        )

    async def rm(
        self: "FilesystemDemoAdapter",
        resource: status_models.Resource,
        user: User,
        path: str,
    ) -> filesystem_models.RemoveResponse:
        rp = validate_path(path)
        if rp == PathSandbox.get_base_temp_dir():
            raise HTTPException(status_code=400, detail="Cannot delete sandbox")
        run_command(["rm", "-rf", rp])
        return filesystem_models.RemoveResponse(output=f"Removed {rp}")

    async def mkdir(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, request_model: filesystem_models.PostMakeDirRequest) -> filesystem_models.PostMkdirResponse:
        rp = validate_path(request_model.path)
        args = ["mkdir"]
        if request_model.parent:
            args.append("-p")
        args.append(rp)
        run_command(args)
        return filesystem_models.PostMkdirResponse(output=file_to_model(rp))

    async def symlink(
        self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, request_model: filesystem_models.PostFileSymlinkRequest
    ) -> filesystem_models.PostFileSymlinkResponse:
        rp_src = validate_path(request_model.path)
        rp_dst = validate_path(request_model.link_path)
        run_command(["ln", "-s", rp_src, rp_dst])
        return filesystem_models.PostFileSymlinkResponse(output=file_to_model(rp_dst))

    async def download(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, path: str) -> filesystem_models.GetFileDownloadResponse:
        rp = validate_path(path)
        raw_content = pathlib.Path(rp).read_bytes()

        if len(raw_content) > facility_adapter.OPS_SIZE_LIMIT:
            raise Exception("File to download is too large.")

        return filesystem_models.GetFileDownloadResponse(
            output=base64.b64encode(raw_content).decode("utf-8"),
        )

    async def upload(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, path: str, content: str) -> filesystem_models.PutFileUploadResponse:
        rp = validate_path(path)
        if isinstance(content, bytes):
            pathlib.Path(rp).write_bytes(content)
        elif isinstance(content, str):
            pathlib.Path(rp).write_bytes(base64.b64decode(content))
        else:
            raise Exception(f"Don't know how to handle variable of type: {type(content)}")
        return filesystem_models.PutFileUploadResponse(output=f"Uploaded to {rp}")

    async def compress(
        self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, request_model: filesystem_models.PostCompressRequest
    ) -> filesystem_models.PostCompressResponse:
        src_rp = validate_path(request_model.path)
        dst_rp = validate_path(request_model.target_path)

        args = ["tar"]
        if request_model.compression == filesystem_models.CompressionType.gzip:
            args.append("-czf")
        elif request_model.compression == filesystem_models.CompressionType.bzip2:
            args.append("-cjf")
        elif request_model.compression == filesystem_models.CompressionType.xz:
            args.append("-cJf")
        args.append(dst_rp)
        if request_model.dereference:
            args.append("--dereference")
        if request_model.match_pattern:
            args.append(f"--include={request_model.match_pattern}")

        args.append("-C")
        args.append(PathSandbox.get_base_temp_dir())
        p = pathlib.Path(src_rp)
        args.append(p.relative_to(PathSandbox.get_base_temp_dir()))
        subprocess.run(args, check=True)

        return filesystem_models.PostCompressResponse(output=file_to_model(dst_rp))

    async def extract(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, request_model: filesystem_models.PostExtractRequest) -> filesystem_models.PostExtractResponse:
        src_rp = validate_path(request_model.path)
        dst_rp = validate_path(request_model.target_path)

        if os.path.exists(dst_rp):
            if os.path.isdir(dst_rp):
                raise Exception(f"Target path already exists: {request_model.target_path}")
            else:
                raise Exception(f"Target path already exists and is not a directory: {request_model.target_path}")
        os.makedirs(dst_rp)

        args = ["tar"]
        if request_model.compression == filesystem_models.CompressionType.gzip:
            args.append("-xzf")
        elif request_model.compression == filesystem_models.CompressionType.bzip2:
            args.append("-xjf")
        elif request_model.compression == filesystem_models.CompressionType.xz:
            args.append("-xJf")
        else:
            args.append("-xf")
        args.append(src_rp)
        args.append("-C")
        args.append(dst_rp)
        subprocess.run(args, check=True)

        return filesystem_models.PostExtractResponse(output=file_to_model(dst_rp))

    async def mv(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, request_model: filesystem_models.PostMoveRequest) -> filesystem_models.PostMoveResponse:
        src_rp = validate_path(request_model.path)
        dst_rp = validate_path(request_model.target_path)
        subprocess.run(["mv", src_rp, dst_rp], check=True)
        return filesystem_models.PostMoveResponse(output=file_to_model(dst_rp))

    async def cp(self: "FilesystemDemoAdapter", resource: status_models.Resource, user: User, request_model: filesystem_models.PostCopyRequest) -> filesystem_models.PostCopyResponse:
        src_rp = validate_path(request_model.path)
        dst_rp = validate_path(request_model.target_path)
        args = ["cp"]
        if request_model.dereference:
            args.append("-L")
        args.append(src_rp)
        args.append(dst_rp)
        subprocess.run(args, check=True)
        return filesystem_models.PostCopyResponse(output=file_to_model(dst_rp))
