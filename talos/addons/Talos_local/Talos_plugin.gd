@tool
extends EditorPlugin

var dock : Control

func _enter_tree() -> void:
	#load custom ui scene
	if not ResourceLoader.exists("res://addons/Talos_local/TTalos_dock.tscn"):
		push_error("Talos Error: cannot find Talos_dock.tscn! Check your folder names")
		return
	var dock_scene =  preload("res://addons/Talos_local/Talos_dock.tscn")
	dock = dock_scene.instantiate()
	
	if dock:
		add_control_to_dock(DOCK_SLOT_RIGHT_BL, dock)
		print("Talos dock suceesfully added to the editor panel!")
	else:
		push_error("Talos error: fails to instantiate the dock scene.")
	
	


func _exit_tree() -> void:
	if dock:
		remove_control_from_docks(dock)
		dock.queue_free()
