@tool
extends EditorPlugin

var dock : Control

func _enter_tree() -> void:
	#laod custom ui scene
	dock =  preload("res://addons/Talos_local/Talos_dock.tscn").instantiate()
	# add the control to the left hand dock slot
	add_control_to_dock(EditorPlugin.DOCK_SLOT_LEFT_BR, dock)
	


func _exit_tree() -> void:
	remove_control_from_docks(dock)
	dock.queue_free()
