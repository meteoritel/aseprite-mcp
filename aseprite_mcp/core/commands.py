import asyncio
import json
import re
import signal
import subprocess
import tempfile
import os
from weakref import WeakKeyDictionary
import dotenv

from anyio import CancelScope
from mcp.server.mcpserver.exceptions import ToolError

_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
dotenv.load_dotenv(dotenv_path=_ENV_PATH)


def lua_escape(s: str) -> str:
    """Escape a string for safe embedding inside a Lua string literal.

    Both quote styles are escaped because tool scripts embed layer names in
    double quotes (`find_layer(spr, "...")`) and echo them back in
    single-quoted error text (`Layer '...' not found`). Lua accepts \\' and
    \\" in either style, so escaping both is safe for both.
    """
    if isinstance(s, list):
        s = json.dumps(s, ensure_ascii=False)
    return (
        s.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("'", "\\'")
         .replace("\n", "\\n")
         .replace("\r", "\\r")
         .replace("\0", "\\0")
    )


def parse_pixel_xy(pixel: dict) -> tuple[int, int] | None:
    """Require explicit integer coordinates for direct Python callers too."""
    x, y = pixel.get("x"), pixel.get("y")
    if type(x) is not int or type(y) is not int:
        return None
    return x, y


def reject_traversal(path: str) -> str | None:
    """Reject parent-directory traversal in a user-supplied path.

    Returns an error message string when the path contains a `..`
    component, or None when the path looks safe.

    The check runs on the RAW path split into components on both
    separators — normalizing first would let os.path.normpath collapse an
    embedded `..` and hide it. Filenames like `foo..bar.aseprite` (dots
    inside a component) are not false positives. Absolute paths and tilde
    expansion are not rejected here: this function targets traversal
    only, not access scoping.
    """
    components = [p for p in re.split(r"[\\/]+", path) if p not in ("", ".")]
    if ".." in components:
        return "Invalid filename: parent directory traversal not allowed"
    return None


PROCESS_TIMEOUT_SECONDS = 60
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
DEFAULT_MAX_CONCURRENCY = 4
MAX_CONCURRENCY_ENV_VAR = "ASEPRITE_MAX_CONCURRENCY"

_PROCESS_SEMAPHORES: WeakKeyDictionary[asyncio.AbstractEventLoop, tuple[int, asyncio.Semaphore]] = WeakKeyDictionary()


def _max_concurrency() -> int:
    raw = os.getenv(MAX_CONCURRENCY_ENV_VAR)
    if not raw:
        return DEFAULT_MAX_CONCURRENCY
    try:
        limit = int(raw)
    except ValueError:
        return DEFAULT_MAX_CONCURRENCY
    return max(1, min(limit, 32))


def _process_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    limit = _max_concurrency()
    cached = _PROCESS_SEMAPHORES.get(loop)
    if cached is None or cached[0] != limit:
        semaphore = asyncio.Semaphore(limit)
        _PROCESS_SEMAPHORES[loop] = (limit, semaphore)
        return semaphore
    return cached[1]


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if os.name == "nt":
        if process.returncode is None:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await killer.wait()
            if process.returncode is None:
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    await process.wait()


class AsepriteCommand:
    """Execute one owned Aseprite batch process with bounded resources."""

    @staticmethod
    async def run_command(args: list[str]) -> str:
        async with _process_semaphore():
            return await AsepriteCommand._run_command_unbounded(args)

    @staticmethod
    async def _run_command_unbounded(args: list[str]) -> str:
        cmd = [os.getenv("ASEPRITE_PATH", "aseprite"), *args]
        options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
                   if os.name == "nt" else {"start_new_session": True})
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, **options,
            )
        except OSError as exc:
            raise ToolError(f"Could not start Aseprite: {exc}") from exc

        stdout, stderr = bytearray(), bytearray()
        output_size = 0

        async def read_stream(stream, destination):
            nonlocal output_size
            while chunk := await stream.read(READ_CHUNK_BYTES):
                output_size += len(chunk)
                if output_size > MAX_OUTPUT_BYTES:
                    raise ToolError(f"Aseprite output exceeded {MAX_OUTPUT_BYTES} bytes; read a smaller region or print less data")
                destination.extend(chunk)

        tasks = [asyncio.create_task(read_stream(process.stdout, stdout)),
                 asyncio.create_task(read_stream(process.stderr, stderr)),
                 asyncio.create_task(process.wait())]
        try:
            async with asyncio.timeout(PROCESS_TIMEOUT_SECONDS):
                await asyncio.gather(*tasks)
        except BaseException as exc:
            # SDK cancellation uses an AnyIO scope; cleanup must finish before
            # that scope can cancel the next subprocess wait as well.
            with CancelScope(shield=True):
                await _terminate_process(process)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            if isinstance(exc, TimeoutError):
                raise ToolError(f"Aseprite timed out after {PROCESS_TIMEOUT_SECONDS} seconds") from exc
            raise

        output = stdout.decode("utf-8", errors="replace")
        diagnostic = stderr.decode("utf-8", errors="replace")
        if process.returncode:
            detail = "\n".join(part.strip() for part in (output, diagnostic) if part.strip())
            raise ToolError(f"Aseprite exited with code {process.returncode}: {detail}")
        return output

    @staticmethod
    async def execute_lua_script(script_content: str, filename: str | None = None) -> str:
        try:
            with tempfile.NamedTemporaryFile(suffix=".lua", delete=False, mode="w", encoding="utf-8") as script:
                script.write(script_content)
                script_path = script.name
            try:
                args = ["--batch"]
                if filename is not None:
                    args.append(filename)
                args.extend(["--script", script_path])
                return await AsepriteCommand.run_command(args)
            finally:
                os.unlink(script_path)
        except OSError as exc:
            raise ToolError(f"Could not prepare Aseprite script: {exc}") from exc

    @staticmethod
    async def execute_lua_script_checked(script_content: str, filename: str | None = None) -> str:
        output = await AsepriteCommand.execute_lua_script(script_content, filename)
        for line in output.splitlines():
            if line.startswith("ERROR:"):
                raise ToolError(line[len("ERROR:"):])
        return output
