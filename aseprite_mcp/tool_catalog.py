"""Tool membership, search terms and examples for MCP registration."""

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
        "draw_sprite_maps",
        "get_sprite_map",
    ),
    "review": (
        "review_frame",
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
        "draw_dither_detail",
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
    "sprite_map": (
        "create_layered_sprite",
    ),
    "export": (
        "export_spritesheet",
        "export_layers",
        "export_slices_to_minecraft",
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

TOOL_SEARCH_TERMS = {
    "draw_sprite_map": ("绘制", "修改", "擦除"),
    "draw_sprite_maps": ("绘制", "修改", "批量"),
    "create_layered_sprite": ("复合网格", "分层绘制", "分层创建"),
    "draw_dither_detail": ("抖动", "纹理", "质感"),
    "apply_dither_pattern": ("抖动", "纹理", "质感"),
    "apply_dither_gradient": ("抖动", "渐变", "过渡"),
    "adjust_hsl": ("色相", "色相偏移", "色相调整"),
    "review_frame": ("审阅", "预览", "复核"),
    "export_minecraft_texture": ("纹理导出", "导出"),
    "export_slices_to_minecraft": ("切片导出", "套装纹理"),
}

TOOL_EXAMPLES = {
    "create_canvas": [{
        "width": 16, "height": 16, "filename": "D:/art/coin.aseprite", "initial_layers": ["base", "shine"],
    }],
    "draw_sprite_maps": [{
        "palette": {"A": "#8B5A2B", "B": "#F2C48D"},
        "maps": [
            {"layer_name": "base", "frame_index": 1, "x": 6, "y": 6, "rows": [".AA.", "AAAA", ".AA."]},
            {"layer_name": "shine", "frame_index": 1, "x": 7, "y": 6, "rows": ["BB"]},
        ],
    }],
    "create_layered_sprite": [{
        "filename": "D:/art/coin.aseprite",
        "rows": [".SS.", "SBB.", ".OO."],
        "palette": {"B": "#8B5A2B", "S": "#F2C48D", "O": "#2A1810"},
        "layers": [
            {"name": "base", "mapping": {"B": "B", "S": "B"}},
            {"name": "shine", "mapping": {"S": "S"}},
            {"name": "outline", "mapping": {"O": "O"}},
        ],
    }],
    "draw_sprite_map": [{
        "layer_name": ["shine"], "frame_index": 1, "x": 7, "y": 6,
        "rows": ["B."], "palette": {"B": "#F2C48D"},
        "erase_transparent": True, "create_if_missing": False,
    }],
    "draw_dither_detail": [{
        "layer_name": "body", "frame_index": 1, "x": 4, "y": 4,
        "width": 8, "height": 8, "color": "#F2C48D", "density": 0.5,
    }],
    "review_frame": [{
        "frame_index": 1, "layer_name": ["shine"],
        "region": {"x": 7, "y": 6, "width": 2, "height": 1}, "palette": {"B": "#F2C48D"},
    }],
    "draw_text": [{"text": "A", "font": "DejaVu Sans", "x": 0, "y": 0, "layer_name": "label", "frame_index": 1}],
    "draw_on_tile": [{"layer_name": "tiles", "tile_index": 1, "pixels": [{"x": 0, "y": 0, "color": "#FFFFFF"}]}],
    "get_tile_at": [{"layer_name": "tiles", "frame_index": 1, "col": 0, "row": 0}],
    "tween_cel_positions": [{"layer_name": "ink", "start_frame": 1, "end_frame": 4, "start_x": 0, "start_y": 0, "end_x": 3, "end_y": 0}],
    "set_slice_center": [{"name": "panel", "x": 1, "y": 1, "width": 6, "height": 6}],
    "ensure_layers_present": [{"layer_names": ["ink"], "start_frame": 1}],
    "validate_scene": [{"required_layers": ["ink"], "start_frame": 1}],
    "export_layers": [{"output_directory": "D:/art/layers"}],
    "get_tilemap_info": [{"layer_name": "tiles"}],
    "audit_animation": [{"layer_frame_ranges": [{"layer": ["art", "ink"], "ranges": [[1, 4]]}], "report_cels": True}],
    "export_minecraft_texture": [
        {"output_filename": "D:/art/coin.png"},
        {"output_filename": "D:/art/texture.png", "tag_name": "loop"},
    ],
    "export_slices_to_minecraft": [{
        "filename": "D:/art/armor.aseprite",
        "output_directory": "D:/art/textures/item",
        "slice_names": ["cat_helmet", "cat_chestplate", "cat_leggings", "cat_boots"],
    }],
}
