@tool
extends EditorPlugin

var dock : Control

func _enter_tree() -> void:
	#laod custom ui scene
	dock =  preload("res://")
