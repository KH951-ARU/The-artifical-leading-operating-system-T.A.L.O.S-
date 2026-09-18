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
	return context

func _on_send_button_pressed() -> void:
	var user_prompt = input_line.text.strip_edges()
	if user_prompt == "": return
	
	output_box.text = "Talos is forging . . ."
	input_line.clear()
	
	progression_bar.value = 0
	progression_timer.start()
	send_button.disabled = true
	cancel_button.disabled = false
	
	var project_context = _get_editor_context()
	
	var system_prompt = (
		"You are T.A.L.O.S , a local computational system. You are a strict Godot 4.4 engine expert that explains thoroughly. " +
		"Use the provided active script structure and ClassDB documentation context below to answer. " +
		"Never hallucinate methods. Match the variables, node names, and structural architecture explicitly provided. " +
		"Return only clean code blocks."
	)
	
	var combined_prompt = "CONTEXT Strings:\n" + project_context + "\n\nUSER REQUEST: " + user_prompt
	
	# BUG FIX: Change user_prompt to combined_prompt to send context to Ollama
	var body = {
		"model": selected_model_name,
		"prompt": combined_prompt,
		"system": system_prompt,
		"stream": false,
		"options": {
			"temperature": 0.1
		}
	}
		
	var headers = ["content-type: application/json"]
	http_node.request(OLLAMA_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(body))

func _on_cancel_button_pressed() -> void:
	if http_node.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		http_node.cancel()
	progression_timer.stop()
	progression_bar.value = 0
	send_button.disabled = false
	cancel_button.disabled = true
	output_box.text = "Forging Process Aborted by User. T.A.L.O.S stands down."
	status_label.text = "Status: Aborted"
	_set_status_color(Color(0.9,0.6,0.2))

func _on_http_routing_coordinator(result: int, response_code: int, header : PackedStringArray, body : PackedByteArray) -> void:
	if send_button.disabled and not model_select_menu.disabled:
		pass
	
	var raw_str = body.get_string_from_utf8()
	var json = JSON.new()
	
	if json.parse(raw_str) == OK:
		var parsed = json.get_data()
		if parsed is Dictionary and parsed.has("models"):
			_process_tags_response(response_code,parsed)
		return
		
		_handle_generation_response(response_code, body)

func _process_tags_response(response_code : int, data : Dictionary) -> void:
	if response_code != 200:
		status_label.text = "Status: failed to retrieve models "
		_set_status_color(Color(0.9,0.3,0.3))
		return
	
	model_select_menu.clear()
	var models_list = data["models"]
	
	for m in models_list:
		if m.has("name"):
			model_select_menu.add_item(m["name"])
			
	if model_select_menu.item_count > 0:
		model_select_menu.select(0)
		selected_model_name = model_select_menu.get_item_text(0)
		status_label.text = "Status: ready (" + selected_model_name + ")"
		_set_status_color(Color(0.2,0.8,0.3))

func _handle_generation_response(response_code : int , body: PackedByteArray) -> void:
	progression_timer.stop()
	send_button.disabled = false
	cancel_button.disabled = true
	model_select_menu.disabled = false
	
	if response_code != 200:
		if output_box.text != "Forging Process Aborted by User. T.A.L.O.S stands down.":
			_execute_offline_fallback_fallback_procedure("Server Response Code %d" % response_code)
		else:
			progression_timer.stop()
			send_button.disabled = false
			cancel_button.disabled = true
			model_select_menu.disabled = false
		return
	progression_timer.stop()
	send_button.disabled = false
	cancel_button.disabled = true
	model_select_menu.disabled = false
	progression_bar.value = progression_bar.max_value
	status_label.text = "Status: Computation Complete"
	_set_status_color(Color(0.1, 0.8, 0.5))
	
	var json = JSON.new()
	if json.parse(body.get_string_from_utf8()) == OK:
		var response_data = json.get_data()
		if response_data.has("response"):
			var ai_raw_response = response_data["response"]
			var clean_code = _extract_code_blocks(ai_raw_response)
			output_box.text = clean_code
			_write_to_offine_cache(running_request_hash, clean_code)
			DisplayServer.clipboard_set(clean_code)
			
			if auto_insert_checkbox.button_pressed:
				_insert_code_into_active_editor(clean_code)

func _execute_offline_fallback_fallback_procedure(reason_str: String) -> void:
	progression_timer.stop()
	send_button.disabled = false
	cancel_button.disabled = true
	model_select_menu.disabled = false
	
	var cached_script = _read_from_offline_cache(running_request_hash)
	if cached_script != "":
		progression_bar.value = progression_bar.max_value
		output_box.text = cached_script
		DisplayServer.clipboard_set(cached_script)
		status_label.text = "Status: Offline Fallback Resolved (Fetched From Cache)"
		_set_status_color(Color(0.0, 0.75, 0.85)) # Distinct Cyan color for database lookup
		
		if auto_insert_checkbox.button_pressed:
			_insert_code_into_active_editor(cached_script)
	else:
		progression_bar.value = 0
		output_box.text = "Error: Ollama Host Unreachable (%s).\nNo matching compiled historical modules found in offline database cache." % reason_str
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
			print("Talos auto insert triggered successfully.")
		else:
			var found_edit = _find_text_edit_recursive(base_editor)
			if found_edit:
				found_edit.insert_text_at_caret(code_to_insert)
				print("Talos auto insertion triggered via fallback.")
			else:
				print("TALOS WARNING: could not locate textedit area inside coding window")

func _find_text_edit_recursive(current_node : Node) -> TextEdit:
	if current_node is TextEdit:
		return current_node
	for child in current_node.get_children():
		var result = _find_text_edit_recursive(child)
		if result:
			return result
	return null
