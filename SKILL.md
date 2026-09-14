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

## Layers and frames: what gets auto-created

Drawing tools create what they need, so you rarely have to prepare the
sprite by hand first:

- **Drawing tools auto-create both the layer and the cel** when
  `create_if_missing=true` (the default). This covers `draw_pixels_at`,
  `draw_line_at`, `draw_rectangle_at`, `draw_circle_at`, `draw_ellipse_at`,
  `fill_area_at`, `draw_polygon`, `draw_path`, `apply_gradient_rect` and
  `draw_text`. You can draw straight onto a name that does not exist yet:

  ```
  create_canvas(32, 32, filename="D:/art/coin.aseprite")
  draw_circle_at(layer_name="coin", frame_index=1, center_x=16, center_y=16, radius=8)
  # layer "coin" and its cel are created on the way in
  ```

  Auto-create only handles **top-level** layer names. A name containing `/`
  is read as a `group/child` path and is never fabricated — call
  `add_layer(group=...)` / `add_group(...)` first.

- **Non-drawing tools require the layer to already exist.** Effects,
  transforms, selections, pixel reads, palettes, tilemaps and most
  animation operations (`set_cel_opacity`, `clear_cel`, tween tools, …) do
  **not** create layers. Call `add_layer(layer_name=...)` first, or check
  `get_sprite_info()` for the exact names.

- **`copy_cel` grows the sprite when needed.** If `target_frame` is past
  the last frame and `create_target_frame=true` (the default), the missing
  frames are appended automatically; the reply says how many were added.
  Pass `create_target_frame=false` to get an error instead.

- Frame indexes are **1-based** everywhere.

## Recommended workflow

```
create_canvas(width, height, filename="D:/art/sprites/coin.aseprite")  # anchors
draw_pixels_at(layer_name="coin", frame_index=1, pixels=[...])  # layer + cel auto-created
add_frames(count=3)         # a second frame only if you need one
set_tag(name="spin", from_frame=1, to_frame=4)
export_sprite(output_filename="D:/art/sprites/coin.png")   # absolute → exact spot
```

Useful extras:

- `get_sprite_info(filename)` shows size, frames, layers and tags of a file.
  Call it whenever a name or frame index is uncertain — it is cheaper than
  guessing and retrying.
- Tools that only read (analysis, pixel_read, quality) also fall back to the
  active file, so you can inspect without repeating the path.
- `run_lua_script(filename=...)` opens the active file too when `filename`
  is omitted.

## Error messages are self-correcting

When something is wrong (no active file, file not found, bad path, unknown
layer, frame out of range) the tool returns a plain-text message that tells
you what to do next. Layer and frame errors include the sprite's **current
state** so you can correct yourself in one step:

```
Failed to draw circle: Layer 'coin' not found. Existing layers: [Layer 1, body].
Tip: call add_layer first; drawing tools auto-create top-level layers when
create_if_missing=true.
```

```
Failed to copy cel: Target frame 5 out of range (sprite has 2 frame(s), 1-based).
Tip: call add_frame first or pass create_target_frame=true.
```

Read the message and retry; do not guess alternative paths.
