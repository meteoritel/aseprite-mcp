"""Stable tool membership and ordering for runtime assembly and documentation."""

DISCOVERY_TOOLS = ("search_tools", "call_tool")

CORE_TOOLS = {
    "canvas": (
        "create_canvas",
        "add_layer",
        "add_group",
        "add_frame",
        "set_frame_duration",
    ),
    "drawing": (
        "draw_pixels_at",
        "draw_line_at",
        "draw_rectangle_at",
        "draw_circle_at",
        "fill_area_at",
        "draw_polygon",
        "draw_path",
        "apply_gradient_rect",
        "draw_ellipse_at",
    ),
    "export": (
        "export_sprite",
        "copy_sprite",
        "export_frame",
        "export_tag",
        "export_minecraft_texture",
        "import_image_as_layer",
    ),
    "animation": (
        "add_frames",
        "set_frame_duration_all",
        "set_layer_visibility",
        "set_layer_opacity",
        "get_sprite_info",
        "duplicate_frame_range",
        "set_cel_position",
        "create_cel",
        "clear_cel",
        "copy_cel",
        "copy_frame",
        "propagate_frame_to_range",
        "set_tag",
        "propagate_cels",
        "delete_frame",
        "delete_tag",
        "set_cel_opacity",
    ),
    "palette": (
        "get_palette",
        "set_palette",
        "remap_colors_in_cel_range",
        "list_palette_presets",
        "apply_palette_preset",
        "generate_color_ramp",
        "quantize_to_palette",
        "set_color_mode",
    ),
    "pixel_read": (
        "get_pixel_color",
        "get_pixels_rect",
        "get_composite_pixel",
        "get_composite_rect",
    ),
    "sprite_map": (
        "draw_sprite_map",
        "get_sprite_map",
    ),
    "transform": (
        "flip_layer",
        "rotate_layer",
        "resize_canvas",
        "crop_canvas",
    ),
    "layers": (
        "delete_layer",
        "rename_layer",
        "duplicate_layer",
        "reorder_layer",
        "set_layer_blend_mode",
        "merge_layer_down",
        "flatten_sprite",
    ),
    "selection": (
        "move_region",
        "copy_region",
        "erase_region",
        "erase_color",
    ),
    "fx": (
        "replace_color",
    ),
    "analysis": (
        "render_onion_skin",
        "compare_frames",
        "get_color_stats",
    ),
    "script": (
        "run_lua_script",
    ),
    "native_fx": (
        "extract_palette",
    ),
}

EXTENSION_TOOLS = {
    "export": (
        "export_spritesheet",
        "export_layers",
    ),
    "animation": (
        "tween_cel_positions",
        "offset_cel_positions",
        "tween_cel_positions_eased",
        "oscillate_cel_positions",
        "tween_cel_opacity_eased",
        "tween_cel_scale_eased",
    ),
    "preview": (
        "start_preview_server",
        "stop_preview_server",
    ),
    "scene": (
        "copy_layers_between_sprites",
    ),
    "quality": (
        "ensure_layers_present",
        "validate_scene",
        "audit_animation",
        "animation_sanitize",
    ),
    "fx": (
        "outline_cel",
        "adjust_hsl",
        "apply_dither_gradient",
        "apply_dither_pattern",
    ),
    "slices": (
        "create_slice",
        "set_slice_center",
        "set_slice_pivot",
        "list_slices",
        "delete_slice",
    ),
    "tilemap": (
        "create_tilemap_layer",
        "draw_on_tile",
        "set_tiles",
        "get_tile_at",
        "get_tilemap_info",
    ),
    "text": (
        "list_text_fonts",
        "measure_text",
        "draw_text",
    ),
    "native_fx": (
        "outline_native",
        "adjust_hsl_native",
        "adjust_brightness_contrast",
        "invert_colors",
        "apply_convolution",
        "list_convolution_matrices",
    ),
}
