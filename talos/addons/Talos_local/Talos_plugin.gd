@tool
extends EditorPlugin

var dock : VBoxContainer
var output_box : TextEdit
var input_line : LineEdit
var send_button : Button
var cancel_button : Button
var auto_insert_checkbox : CheckBox
var http_node: HTTPRequest
var model_select_menu : OptionButton
var status_label : Label
var progression_bar : ProgressBar
var progression_timer :Timer

const OLLAMA_URL = "http://localhost:11434/api/generate"
const OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
var selected_model_name = "qwen2.5-coder:3b"
const LOCAL_XML_DOCS_PATH = "res://doc_classes/"
const CACHE_DIR = "user://Talos_cache/"
const SETTING_SHORCUT = "plugins/talos/shortcut_key"

var running_request_hash = ""


func _enter_tree() -> void:
	dock = VBoxContainer.new()
	dock.name = "T.A.L.O.S"
	
	dock.custom_minimum_size = Vector2(250, 400)
	dock.size_flags_vertical = Control.SIZE_EXPAND_FILL
	dock.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	
	output_box = TextEdit.new()
	output_box.editable = false
	output_box.placeholder_text = " talos output will appear here.."
	output_box.size_flags_vertical = Control.SIZE_EXPAND_FILL
	
	progression_bar = ProgressBar.new()
	progression_bar.min_value = 0
	progression_bar.max_value = 10
	progression_bar.step = 1.0 # creates segments
	progression_bar.value = 0
	progression_bar.show_percentage = false
	progression_bar.custom_minimum_size = Vector2(0, 16)
	_apply_segmented_style(progression_bar)
	
	var model_box = HBoxContainer.new()
	var model_label = Label.new()
	model_label.text = "Model: "
	model_select_menu = OptionButton.new()
	model_select_menu.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	model_select_menu.add_item(selected_model_name)
	model_select_menu.item_selected.connect(_on_model_selected)
	model_box.add_child(model_label)
	model_box.add_child(model_select_menu)
	
	var button_box = HBoxContainer.new()
	send_button = Button.new()
	send_button.text = "offer to T.A.L.O.S"
	send_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	
	cancel_button = Button.new()
	cancel_button.text = "ABORT Forging"
	cancel_button.disabled = true
	
	button_box.add_child(send_button)
	button_box.add_child(cancel_button)
	
	status_label = Label.new()
	status_label.text = "Status: IDLE"
	status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD
	_set_status_color(Color(0.6 ,0.6 ,0.6))
	
	progression_timer = Timer.new()
	progression_timer.wait_time = 0.15
	progression_timer.one_shot = false
	
	auto_insert_checkbox = CheckBox.new()
	auto_insert_checkbox.text = "auto insert at cursor position"
	auto_insert_checkbox.button_pressed = false
	
	input_line = LineEdit.new()
	input_line.placeholder_text = "Request a offering to T.A.L.O.S for a creation"
	
	http_node = HTTPRequest.new()
	
	#ui assembly hierarchy
	dock.add_child(output_box)
	dock.add_child(progression_bar)
	dock.add_child(model_box)
	dock.add_child(button_box)
	dock.add_child(status_label)
	dock.add_child(auto_insert_checkbox)
	dock.add_child(input_line)
	dock.add_child(http_node)
	dock.add_child(progression_timer)
	
	send_button.pressed.connect(_on_send_button_pressed)
	cancel_button.pressed.connect(_on_cancel_button_pressed)
	http_node.request_completed.connect(_on_http_routing_coordinator)
	progression_timer.timeout.connect(_on_progress_tick)
	
	add_control_to_dock(EditorPlugin.DOCK_SLOT_RIGHT_BR, dock)
	print("talos ui forced into editor successfully.")
	
	_fetch_local_ollama_models()

func _exit_tree() -> void:
	if dock:
		remove_control_from_docks(dock)
		dock.queue_free()

func _init_editor_setting_configs() -> void:
	if not ProjectSettings.has_setting(SETTING_SHORCUT):
		ProjectSettings.set_setting(SETTING_SHORCUT, "T")
		ProjectSettings.set_initial_value(SETTING_SHORCUT, "T")
	
	var property_info = {
		"name": SETTING_SHORCUT,
		"type": TYPE_STRING,
		"hint":PROPERTY_HINT_NONE,
		"hint_string": "The alpha key triggered alongside Ctrl+Shift+T"
	}
	ProjectSettings.add_property_info(property_info)
	ProjectSettings.save()

func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed:
		var configured_key = ProjectSettings.get_setting(SETTING_SHORCUT , "T").to_upper()
		var target_keycode = OS.find_keycode_from_string(configured_key)
		
		if  event.ctrl_pressed and event.shift_pressed and event.keycode == target_keycode:
			if not send_button.disabled:
				get_viewport().set_input_as_handled()
				_on_send_button_pressed()

func _init_cache_directory() -> void:
	if not DirAccess.dir_exists_absolute(CACHE_DIR):
		DirAccess.make_dir_absolute(CACHE_DIR) 

func _apply_segmented_style(bar : ProgressBar) -> void:
	var bg_style = StyleBoxFlat.new()
	bg_style.bg_color = Color(0.08, 0.08, 0.1,0.1)
	bg_style.corner_radius_top_left = 4
	bg_style.corner_radius_bottom_left = 4
	bg_style.corner_radius_top_right = 4
	bg_style.corner_radius_bottom_right = 4
	
	var fg_style = StyleBoxFlat.new()
	fg_style.bg_color = Color(0.15,0.15,0.15)
	fg_style.border_width_right = 2
	fg_style.border_color = Color(0.1,0.1,0.1)
	fg_style.corner_radius_top_left = 2
	fg_style.corner_radius_bottom_left = 2
	
	bar.add_theme_stylebox_override("background", bg_style)
	bar.add_theme_stylebox_override("fill", fg_style)

func _set_status_color(color : Color) -> void:
	status_label.add_theme_color_override("font_color", color)

func _on_progress_tick() -> void:
	if progression_bar.value >= progression_bar.max_value:
		progression_bar.value = 0
	else:
		progression_bar.value += progression_bar.step

func _fetch_local_ollama_models() -> void:
	status_label.text = "Status: Querying host models..."
	_set_status_color(Color(0.9,0.3,0.3))

func _on_model_selected(index : int) -> void:
	selected_model_name = model_select_menu.get_item_text(index)
	status_label.text = "Status: Switched to " + selected_model_name
	_set_status_color(Color(0.2,0.7,0.9))

func _write_to_offine_cache( hash_signature : String, code_content: String) -> void:
	if hash_signature == "" or code_content.strip_edges() == "": return
	var path = CACHE_DIR + hash_signature + ".cache"
	var file = FileAccess.open(path, FileAccess.WRITE)
	if file:
		file.store_string(code_content)
		file.close()

func _read_from_offline_cache(hash_signature: String) -> String:
	var path = CACHE_DIR + hash_signature + ".cache"
	if not FileAccess.file_exists(path):
		return ""
	
	var file = FileAccess.open(path, FileAccess.READ)
	if file:
		var contents = file.get_as_text()
		file.close()
		return contents
	return ""

func _on_clear_cache_pressed() -> void:
	var dir = DirAccess.open(CACHE_DIR)
	if dir:
		dir.list_dir_begin()
		var file_name = dir.get_next()
		var count = 0
		while file_name != "":
			if  not dir.current_is_dir() and file_name.ends_with(".cache"):
				dir.remove(file_name)
				count += 1
			file_name = dir.get_next()
		
		status_label.text = "Status: Purged %d Cached Files Successfully" % count
		_set_status_color(Color(0.9,0.3,0.3))
		
func _load_local_xml_docs(class_name_str : String) -> String:
	var doc_context = ""
	var file_path = LOCAL_XML_DOCS_PATH + class_name_str.to_lower() + ".xml"
	if not FileAccess.file_exists(file_path):
		return "[No offline XML File found for class %s. Using internal ClassDB data.]\n" % class_name_str
	
	var file = FileAccess.open(file_path, FileAccess.READ)
	if file:
		var parser = XMLParser.new()
		parser.open(file_path)
		
		var inside_description = false
		var method_name = ""
		
		while parser.read() == OK:
			var node_type = parser.get_node_type()
			var node_name = parser.get_node_name()
			
			if node_type == XMLParser.NODE_ELEMENT:
				if node_name == "description":
					inside_description = true
			elif node_name == "method":
				method_name = parser.get_named_attribute_value_safe("name")
				doc_context += " - Method API: %s\n" % method_name
			elif node_type == XMLParser.NODE_TEXT and inside_description:
				var text = parser.get_node_data().strip_edges()
				if text != "":
					doc_context += "Class Description : %s\n" % text
				inside_description = false
			elif node_type == XMLParser.NODE_ELEMENT_END and node_name == "description":
				inside_description = false
		file.close()
	return doc_context 

func _get_deep_scene_context() -> String:
	var scene_context = ""
	var scene_root = EditorInterface.get_edited_scene_root()
	
	var children = scene_root.find_children("*","", true, false)
	for child in children:
		scene_context += "-> Node Path Element: %s (Type: %S)\n" % [scene_root.get_path_to(child),child.get_class()]
		var script = child.get_script()
		if script and script is Script:
			scene_context += "[Attached Script Content Found]: %s\n" % script.resource_path
			var lines =  script.source_code.split("\n")
			var line_count = 0 
			for line in lines:
				if line_count > 15:break
				if line.begins_with("var") or line.begins_with("signal") or line.begins_with("func"):
					scene_context += "| %s\n" % line.strip_edges()
					line_count += 1
			return scene_context
			

func _get_editor_context() -> String:
	var context = ""
	var script_editor = EditorInterface.get_script_editor()
	var current_script = script_editor.get_current_script()
	
	if current_script:
		context += "\n--- Current Active Script (%s) ---\n" % current_script.resource_path
		context += current_script.source_code + "\n"
		
		var base_class = current_script.get_instance_base_type()
		context += "\n --- GODOT 4.4 BASE class Documentation (%s) ---\n" % base_class
		
		context += _load_local_xml_docs(base_class)
		
		var methods = ClassDB.class_get_method_list(base_class)
		var method_count = 0
		for method in methods:
			if method_count > 10: break
			if not method["name"].begin_with("_") or method["name"] in ["_ready","_process","_physics_process"]:
				context += "Native Method: %s()\n" % method["name"]
				method_count += 1 
				context += _get_deep_scene_context()
	return context

func _on_send_button_pressed() -> void:
	var user_prompt = input_line.text.strip_edges()
	if user_prompt == "":
		var script_editor = EditorInterface.get_script_editor()
		var base_editor = script_editor.get_current_editor()
		if base_editor:
			var text_edits = base_editor.find_children("*", "TextEdit", true, false)
			if text_edits.size() > 0 and text_edits[0] is TextEdit:
				var target_edit : TextEdit = text_edits[0] as TextEdit
				if target_edit.has_selection():
					user_prompt = target_edit.get_selected_text().strip_edges()
					
	if user_prompt == "":
		if status_label:
			status_label.text = "Status: Prompt Blank (Write text or select script block)"
		_set_status_color(Color(0.9, 0.4, 0.4))
		return
		
	output_box.text = "Talos is forging . . ."
	input_line.clear()
	if status_label:
		status_label.text = "Status: Forging code structure..."
	_set_status_color(Color(0.2, 0.8, 0.5))
	
	if progression_bar: progression_bar.value = 0
	if progression_timer: progression_timer.start()
	if send_button: send_button.disabled = true
	if cancel_button: cancel_button.disabled = false
	if clear_cache_button: clear_cache_button.disabled = true
	if model_select_menu: model_select_menu.disabled = true
	
	var project_context = _get_editor_context()
	var system_prompt = (
		"You are T.A.L.O.S , a local computational system. You are a strict Godot 4.4 engine expert that explains thoroughly. " 
		+ "Use the provided active script structure and ClassDB documentation context below to answer. " 
		+ "Never hallucinate methods. Match the variables, node names, and structural architecture explicitly provided. " 
		+ "Return only clean code blocks."
	)
	var combined_prompt = "CONTEXT Strings:\n" + project_context + "\n\nUSER REQUEST: " + user_prompt
	running_request_hash = "".md5_text(combined_prompt + "_" + selected_model_name)
	
	var body = {
		"model": selected_model_name,
		"prompt": combined_prompt,
		"system": system_prompt,
		"stream": false,
		"options": { "temperature": 0.1 }
	}
	var headers = ["content-type: application/json"]
	
	var request_err = http_node.request(OLLAMA_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(body))
	if request_err != OK:
		_execute_offline_fallback_procedure("HTTP Engine Request Failure")

func _on_cancel_button_pressed() -> void:
	if http_node.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		http_node.cancel()
	if progression_timer: progression_timer.stop()
	if progression_bar: progression_bar.value = 0
	if send_button: send_button.disabled = false
	if cancel_button: cancel_button.disabled = true
	if clear_cache_button: clear_cache_button.disabled = false
	if model_select_menu: model_select_menu.disabled = false
	output_box.text = "Forging Process Aborted by User. T.A.L.O.S stands down."
	if status_label:
		status_label.text = "Status: Aborted"
	_set_status_color(Color(0.9, 0.6, 0.2))

func _on_http_routing_coordinator(result: int, response_code: int, header: PackedStringArray, body: PackedByteArray) -> void:
	var raw_str = body.get_string_from_utf8()
	var json = JSON.new()
	if json.parse(raw_str) == OK:
		var parsed = json.get_data()
		if parsed is Dictionary and parsed.has("models"):
			_process_tags_response(response_code, parsed)
			return
			
	_handle_generation_response(response_code, body)

func _process_tags_response(response_code: int, data: Dictionary) -> void:
	if not status_label or not model_select_menu: return
	if response_code != 200:
		status_label.text = "Status: Using Default Model Configuration Only"
		_set_status_color(Color(0.9, 0.5, 0.2))
		return
		
	model_select_menu.clear()
	var models_list = data["models"]
	for m in models_list:
		if m.has("name"):
			model_select_menu.add_item(m["name"])
			
	if model_select_menu.item_count > 0:
		model_select_menu.select(0)
		selected_model_name = model_select_menu.get_item_text(0)
		
	status_label.text = "Status: Ready (" + selected_model_name + ")"
	_set_status_color(Color(0.2, 0.8, 0.3))

func _handle_generation_response(response_code: int, body: PackedByteArray) -> void:
	if response_code != 200:
		if output_box.text != "Forging Process Aborted by User. T.A.L.O.S stands down.":
			_execute_offline_fallback_procedure("Server Response Code %d" % response_code)
		else:
			if progression_timer: progression_timer.stop()
			if send_button: send_button.disabled = false
			if cancel_button: cancel_button.disabled = true
			if clear_cache_button: clear_cache_button.disabled = false
			if model_select_menu: model_select_menu.disabled = false
		return
		
	if progression_timer: progression_timer.stop()
	if send_button: send_button.disabled = false
	if cancel_button: cancel_button.disabled = true
	if clear_cache_button: clear_cache_button.disabled = false
	if model_select_menu: model_select_menu.disabled = false
	if progression_bar: progression_bar.value = progression_bar.max_value
	if status_label:
		status_label.text = "Status: Computation Complete"
	_set_status_color(Color(0.1, 0.8, 0.5))
	
	var json = JSON.new()
	if json.parse(body.get_string_from_utf8()) == OK:
		var response_data = json.get_data()
		if response_data.has("response"):
			var ai_raw_response = response_data["response"]
			var clean_code = _extract_code_blocks(ai_raw_response)
			
			output_box.text = clean_code
			_write_to_offline_cache(running_request_hash, clean_code) # FIXED SYNTAX ERROR HERE
			
			DisplayServer.clipboard_set(clean_code)
			if auto_insert_checkbox.button_pressed:
				_insert_code_into_active_editor(clean_code)

func _execute_offline_fallback_procedure(reason_str: String) -> void:
	if progression_timer: progression_timer.stop()
	if send_button: send_button.disabled = false
	if cancel_button: cancel_button.disabled = true
	if clear_cache_button: clear_cache_button.disabled = false
	if model_select_menu: model_select_menu.disabled = false
	
	var cached_script = _read_from_offline_cache(running_request_hash)
	if cached_script != "":
		if progression_bar: progression_bar.value = progression_bar.max_value
		output_box.text = cached_script
		DisplayServer.clipboard_set(cached_script)
		if status_label:
			status_label.text = "Status: Offline Fallback Resolved (Fetched From Cache)"
		_set_status_color(Color(0.0, 0.75, 0.85))
		if auto_insert_checkbox.button_pressed:
			_insert_code_into_active_editor(cached_script)
	else:
		if progression_bar: progression_bar.value = 0
		output_box.text = "Error: Ollama Host Unreachable (%s).\nNo matching historical modules found." % reason_str
		if status_label:
			status_label.text = "Status: Core Offline & Cache Miss"
		_set_status_color(Color(0.9, 0.2, 0.2))

func _extract_code_blocks(raw_input : String) -> String:
	if not "```" in raw_input:
		return raw_input.strip_edges()
	var lines = raw_input.split("\n")
	var extracted_code = ""
	var inside_block = false
	for line in lines:
		if line.begins_with("```"):
			inside_block = !inside_block
			continue
		if inside_block:
			extracted_code += line + "\n"
	return extracted_code.strip_edges()

func _insert_code_into_active_editor(code_to_insert: String) -> void:
	var script_editor = EditorInterface.get_script_editor()
	var base_editor = script_editor.get_current_editor()
	if base_editor:
		var text_edits = base_editor.find_children("*", "TextEdit", true, false)
		if text_edits.size() > 0 and text_edits[0] is TextEdit:
			var target_edit : TextEdit = text_edits[0] as TextEdit
			target_edit.insert_text_at_caret(code_to_insert)

func _find_text_edit_recursive(current_node : Node) -> TextEdit:
	if current_node is TextEdit:
		return current_node
	for child in current_node.get_children():
		var result = _find_text_edit_recursive(child)
		if result:
			return result
	return null
