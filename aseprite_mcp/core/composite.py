"""Aseprite visible-layer composition shared by reads and review."""

COMPOSE_FRAME = """
local function visible_clone(spr)
    local clone = Sprite(spr)

    -- flatten() needs a layer to produce, and this also keeps the sprite from
    -- reaching zero layers while the hidden ones are being deleted.
    local keep = clone:newLayer()
    keep.name = "__visible_only__"

    local doomed = {}
    local function scan(layers)
        for _, layer in ipairs(layers) do
            if not layer.isVisible then
                doomed[#doomed + 1] = layer
            elseif layer.isGroup then
                -- A hidden group takes its children with it, so do not descend
                -- into it: they would be collected twice and the second delete
                -- would fail.
                scan(layer.layers)
            end
        end
    end
    scan(clone.layers)
    for _, layer in ipairs(doomed) do clone:deleteLayer(layer) end

    clone:flatten()
    return clone
end

local function compose_frame(spr, frame_idx, bg)
    local clone = visible_clone(spr)
    local img = Image(spr.width, spr.height, ColorMode.RGB)
    if bg then
        for py = 0, img.height - 1 do
            for px = 0, img.width - 1 do
                img:putPixel(px, py, bg)
            end
        end
    end
    local layer = clone.layers[#clone.layers]
    local cel = layer:cel(clone.frames[frame_idx])
    if cel then
        img:drawImage(cel.image, cel.position)
    end
    return img
end
"""
