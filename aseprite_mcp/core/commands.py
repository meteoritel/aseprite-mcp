import re
import subprocess
import tempfile
import os
import dotenv

_ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
dotenv.load_dotenv(dotenv_path=_ENV_PATH)


def lua_escape(s: str) -> str:
    """Escape a string for safe embedding inside a Lua double-quoted string literal."""
    return (
        s.replace("\\", "\\\\")
         .replace('"', '\\"')
         .replace("\n", "\\n")
         .replace("\r", "\\r")
         .replace("\0", "\\0")
    )


def parse_pixel_xy(pixel: dict) -> tuple[int, int] | None:
    """Coerce a pixel dict's x/y to integers, or None when invalid.

    `pixels` tool arguments are typed Dict[str, Any], so x/y values are
    not schema-validated before being interpolated into Lua scripts;
    they must be plain integers there.
    """
    try:
        return int(pixel.get("x", 0)), int(pixel.get("y", 0))
    except (TypeError, ValueError):
        return None


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


class AsepriteCommand:
    """Helper class for running Aseprite commands."""
    
    @staticmethod
    def run_command(args):
        """Run an Aseprite command with proper error handling.
        
        Args:
            args: List of command arguments
            
        Returns:
            tuple: (success, output) where success is a boolean and output is the command output
        """
        try:
            cmd = [os.getenv('ASEPRITE_PATH', 'aseprite')] + args
            # Aseprite writes UTF-8 to stdout/stderr. Decode explicitly:
            # text=True alone would use the Windows ANSI code page (GBK),
            # garbling any non-ASCII output (paths, layer names, errors).
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            return False, e.stderr
    
    @staticmethod
    def execute_lua_script(script_content, filename=None):
        """Execute a Lua script in Aseprite.
        
        Args:
            script_content: Lua script code to execute
            filename: Optional filename to open before executing script
            
        Returns:
            tuple: (success, output)
        """
        # Create a temporary file for the script. Aseprite reads Lua files
        # as UTF-8; without an explicit encoding the file would be written
        # in the Windows ANSI code page (GBK), so any non-ASCII path in the
        # script (e.g. Chinese filenames) would end up as mojibake and the
        # file would be saved to the wrong location.
        with tempfile.NamedTemporaryFile(
            suffix='.lua', delete=False, mode='w', encoding='utf-8'
        ) as tmp:
            tmp.write(script_content)
            script_path = tmp.name
        
        try:
            args = ["--batch"]
            if filename and os.path.exists(filename):
                args.append(filename)
            args.extend(["--script", script_path])
            
            success, output = AsepriteCommand.run_command(args)
            return success, output
        finally:
            # Clean up the temporary script file
            os.remove(script_path)

    @staticmethod
    def execute_lua_script_checked(script_content, filename=None):
        """Execute a Lua script and surface in-script errors.

        Scripts using this helper signal failure by printing a line
        starting with "ERROR:" (batch-mode scripts cannot affect the
        process exit code from Lua).

        Returns:
            tuple: (success, output) where output is the error message
            when an ERROR: line was printed, or the raw stdout otherwise.
        """
        success, output = AsepriteCommand.execute_lua_script(script_content, filename)
        if not success:
            return False, output
        for line in output.splitlines():
            if line.startswith("ERROR:"):
                return False, line[len("ERROR:"):]
        return True, output
