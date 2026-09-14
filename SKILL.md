# Aseprite MCP — Usage Guide for AI Assistants

Read this once at session start. It explains how file handling works so you
never have to guess where files land or when `filename` is required.

## The `filename` parameter is optional almost everywhere

Every tool that touches a sprite file accepts a `filename` parameter, and it
is **optional**. The session keeps track of one *active file*:

1. `create_canvas` — or any tool with an explicit `filename` — anchors that
   file as the active file.
2. Later calls may **omit `filename`** entirely; they act on the active file.
3. To switch files mid-session, just pass `filename` explicitly again.

If you call a file tool with no `filename` before anything was anchored, you
get a friendly error — call `create_canvas` first, or pass `filename`.

## `create_canvas` requires an absolute path

`create_canvas` is the one exception: its `filename` is **required** and must
be an **absolute path** (e.g. `"D:/art/sprites/coin.aseprite"`). Relative
paths are rejected with an error. This guarantees the new canvas lands
exactly where the user intends instead of silently inside the MCP server's
own folder. Decide the destination before calling and spell it out in full.

## Where files are written

- Passing an **absolute path** always writes exactly there. This is the most
  predictable option — prefer it whenever you know the target directory
  (and it is mandatory for `create_canvas`).
- Passing a **relative path** to any other tool resolves against the
  server's workspace directory:
  - `ASERITE_MCP_WORKSPACE` environment variable, if the client set one
    (usually your project folder);
  - otherwise the server's working directory. Relative export paths can
    therefore end up inside the server folder — prefer absolute paths here
    too.
- Parent-directory traversal (`..`) is rejected everywhere.
- Export/copy outputs (`output_filename`, `data_filename`) follow the same
  rule, so pass absolute paths to control where exports land.

## Recommended workflow

```
create_canvas(width, height, filename="D:/art/sprites/coin.aseprite")  # anchors
add_layer(...)              # filename omitted — uses the active file
draw_pixels_at(...)         # filename omitted
export_sprite(output_filename="D:/art/sprites/coin.png")   # absolute → exact spot
```

Useful extras:

- `get_sprite_info(filename)` shows size, frames, layers and tags of a file.
- Tools that only read (analysis, pixel_read, quality) also fall back to the
  active file, so you can inspect without repeating the path.
- `run_lua_script(filename=...)` opens the active file too when `filename`
  is omitted.

## Error messages are self-correcting

When something is wrong (no active file, file not found, bad path) the tool
returns a plain-text message that tells you exactly what to do next. Read the
message and retry; do not guess alternative paths.
