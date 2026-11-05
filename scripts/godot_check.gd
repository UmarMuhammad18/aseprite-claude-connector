extends SceneTree

# Run by check_godot.py inside a real project: reports what Godot itself loaded.


func _init() -> void:
	var report := {"animations": {}}
	var frames: SpriteFrames = load("res://sprites/hero.tres")
	for animation in frames.get_animation_names():
		var cells := []
		for n in frames.get_frame_count(animation):
			var texture: AtlasTexture = frames.get_frame_texture(animation, n)
			var sheet := Image.load_from_file(
				ProjectSettings.globalize_path(texture.atlas.resource_path)
			)
			var region := texture.region
			var color := sheet.get_pixelv(Vector2i(region.position + region.size / 2))
			cells.append({
				"duration": frames.get_frame_duration(animation, n),
				"size": [int(region.size.x), int(region.size.y)],
				"color": color.to_html(false),
			})
		report["animations"][animation] = {
			"fps": frames.get_animation_speed(animation),
			"loop": frames.get_animation_loop(animation),
			"frames": cells,
		}
	var tileset: TileSet = load("res://sprites/terrain.tres")
	if tileset:
		var layer := TileMapLayer.new()
		layer.tile_set = tileset
		var cells: Array[Vector2i] = []
		for y in range(3):
			for x in range(4):
				cells.append(Vector2i(x, y))
		cells.append(Vector2i(5, 1))
		layer.set_cells_terrain_connect(cells, 0, 0)
		var painted := []
		for c in cells:
			var at := layer.get_cell_atlas_coords(c)
			painted.append([c.x, c.y, at.x, at.y])
		report["tiles"] = {"count": tileset.get_source(0).get_tiles_count(), "cells": painted}
		layer.free()
	print("GODOT_REPORT=" + JSON.stringify(report))
	quit()
