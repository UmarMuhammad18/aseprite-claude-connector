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
	print("GODOT_REPORT=" + JSON.stringify(report))
	quit()
