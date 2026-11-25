@tool
extends EditorPlugin

const OLLAMA_URL = "http://localhost:11434/api/generate"
const OLLAMA_TAGS_URL = "http://localhost:11434/api/tags"
const LOCAL_XML_DOCS_PATH = "res://doc_classes/"
const CACHE_DIR = "user://talos_cache/"
const SETTING_SHORTCUT = "plugins/talos/shortcut_key"

# UI Hierarchy Nodes
var main_tabs: TabContainer
var dock: VBoxContainer
var history_panel: VBoxContainer

# Forging Tab Elements
var output_box: TextEdit
var input_line: LineEdit
var send_button: Button
var cancel_button: Button
var clear_cache_button: Button
var auto_insert_checkbox: CheckBox
var http_node: HTTPRequest
var model_select_menu: OptionButton
var status_label: Label
var progress_bar: ProgressBar
var progress_timer: Timer

# History Tab Elements
var history_list: ItemList
var history_preview: TextEdit
var history_insert_button: Button

# Live Diff Layout View Modules (Before & After Screen)
var diff_window: AcceptDialog
var diff_left_view: TextEdit
var diff_right_view: TextEdit
var diff_inject_partial_btn: Button
var pending_injection_code: String = ""
var is_syncing_scroll: bool = false

var selected_model_name = "qwen2.5-coder:3b"

var running_request_hash = ""
var history_hashes: Array[String] = []


func _enter_tree() -> void:
	_init_cache_directory()
	_init_editor_settings_configs()

	# Root Layout Wrapper Container
	main_tabs = TabContainer.new()
	main_tabs.name = "T.A.L.O.S"
	main_tabs.custom_minimum_size = Vector2(250, 580)
	main_tabs.size_flags_vertical = Control.SIZE_EXPAND_FILL
	main_tabs.size_flags_horizontal = Control.SIZE_EXPAND_FILL

	# ==========================================
	# TAB 1: CODE FORGING COCKPIT
	# ==========================================
	dock = VBoxContainer.new()
	dock.name = "Forging"

	output_box = TextEdit.new()
	output_box.editable = false
	output_box.placeholder_text = " talos output will appear here.."
	output_box.size_flags_vertical = Control.SIZE_EXPAND_FILL

	progress_bar = ProgressBar.new()
	progress_bar.min_value = 0
	progress_bar.max_value = 10
	progress_bar.step = 1.0
	progress_bar.value = 0
	progress_bar.show_percentage = false
	progress_bar.custom_minimum_size = Vector2(0, 14)
	_apply_segmented_style(progress_bar)

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
	send_button.text = "Offer Prompt"
	send_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL

	cancel_button = Button.new()
	cancel_button.text = "Abort"
	cancel_button.disabled = true
	cancel_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL

	button_box.add_child(send_button)
	button_box.add_child(cancel_button)

	clear_cache_button = Button.new()
	clear_cache_button.text = "Clear Cache Database"
	clear_cache_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL

	status_label = Label.new()
	status_label.text = "Status: Idle"
	status_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD
	_set_status_color(Color(0.6, 0.6, 0.6))

	progress_timer = Timer.new()
	progress_timer.wait_time = 0.15
	progress_timer.one_shot = false

	auto_insert_checkbox = CheckBox.new()
	auto_insert_checkbox.text = "review changes via Before/After Diff"
	auto_insert_checkbox.button_pressed = true

	input_line = LineEdit.new()
	input_line.placeholder_text = "Request an offering to T.A.L.O.S..."

	http_node = HTTPRequest.new()

	dock.add_child(output_box)
	dock.add_child(progress_bar)
	dock.add_child(model_box)
	dock.add_child(button_box)
	dock.add_child(clear_cache_button)
	dock.add_child(status_label)
	dock.add_child(auto_insert_checkbox)
	dock.add_child(input_line)
	dock.add_child(http_node)
	dock.add_child(progress_timer)

	# ==========================================
	# TAB 2: CACHE MODULE HISTORY SIDEBAR
	# ==========================================
	history_panel = VBoxContainer.new()
	history_panel.name = "History Modules"

	var history_info_label = Label.new()
	history_info_label.text = "Compiled Cache Modules:"
	history_info_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_LEFT

	history_list = ItemList.new()
	history_list.size_flags_vertical = Control.SIZE_EXPAND_FILL
	history_list.item_selected.connect(_on_history_item_selected)

	history_preview = TextEdit.new()
	history_preview.editable = false
	history_preview.placeholder_text = "Select a historical script signature module to preview..."
	history_preview.size_flags_vertical = Control.SIZE_EXPAND_FILL

	history_insert_button = Button.new()
	history_insert_button.text = "Compare & Inject Module"
	history_insert_button.disabled = true
	history_insert_button.pressed.connect(_on_history_insert_pressed)

	history_panel.add_child(history_info_label)
	history_panel.add_child(history_list)
	history_panel.add_child(history_preview)
	history_panel.add_child(history_insert_button)

	# Assembly Tab Layout Framework
	main_tabs.add_child(dock)
	main_tabs.add_child(history_panel)

	# Initialise Dynamic Comparative Layout Subsystems
	_setup_diff_viewer_window()

	# Signal Connections
	send_button.pressed.connect(_on_send_button_pressed)
	cancel_button.pressed.connect(_on_cancel_button_pressed)
	clear_cache_button.pressed.connect(_on_clear_cache_pressed)
	http_node.request_completed.connect(_on_http_routing_coordinator)
	progress_timer.timeout.connect(_on_progress_tick)

	add_control_to_dock(EditorPlugin.DOCK_SLOT_RIGHT_BR, main_tabs)
	print("talos UI framework deployed successfully.")

	callable(_fetch_local_ollama_models).call_deferred()
	_refresh_history_list()


func _exit_tree() -> void:
	if main_tabs:
		remove_control_from_docks(main_tabs)
		main_tabs.queue_free()
	if diff_window:
		diff_window.queue_free()


# ==============================================================================
# LIVE BEFORE & AFTER DIFF VIEWING LAYOUT SUB-SYSTEM
# ==============================================================================
func _setup_diff_viewer_window() -> void:
	diff_window = AcceptDialog.new()
	diff_window.title = "⚖️ T.A.L.O.S Before & After Script Comparison"
	diff_window.min_size = Vector2i(960, 640)
	diff_window.ok_button_text = "Inject Full Offering"
	diff_window.confirmed.connect(_on_diff_window_confirmed)

	# Custom Action Button for Partial Selection Injection
	diff_inject_partial_btn = diff_window.add_button(
		"Inject Highlighted Selection Only", false, "inject_partial"
	)
	diff_inject_partial_btn.disabled = true
	diff_window.custom_action.connect(_on_diff_custom_action)

	var main_vbox = VBoxContainer.new()
	main_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	main_vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL

	var header_lbl = Label.new()
	header_lbl.text = (
		"Compare BEFORE vs. AFTER states. "
		+ "Highlight specific lines on the right to inject a partial chunk."
	)
	header_lbl.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	main_vbox.add_child(header_lbl)

	var hsplit = HSplitContainer.new()
	hsplit.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	hsplit.size_flags_vertical = Control.SIZE_EXPAND_FILL
	hsplit.split_offset = 470

	# BEFORE Screen (Left Column Container)
	var left_vbox = VBoxContainer.new()
	left_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	left_vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var left_lbl = Label.new()
	left_lbl.text = "BEFORE (Current Active Script)"
	left_lbl.add_theme_color_override("font_color", Color(0.9, 0.5, 0.5))
	diff_left_view = TextEdit.new()
	diff_left_view.editable = false
	diff_left_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	left_vbox.add_child(left_lbl)
	left_vbox.add_child(diff_left_view)

	# AFTER Screen (Right Column Container)
	var right_vbox = VBoxContainer.new()
	right_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right_vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var right_lbl = Label.new()
	right_lbl.text = "AFTER (Simulated Result with T.A.L.O.S Offering)"
	right_lbl.add_theme_color_override("font_color", Color(0.4, 0.9, 0.6))
	diff_right_view = TextEdit.new()
	diff_right_view.editable = false
	diff_right_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	diff_right_view.caret_changed.connect(_on_diff_right_selection_changed)
	right_vbox.add_child(right_lbl)
	right_vbox.add_child(diff_right_view)

	# Synchronize Vertical & Horizontal Scrollbars
	diff_left_view.get_v_scroll_bar().value_changed.connect(_on_left_v_scroll)
	diff_right_view.get_v_scroll_bar().value_changed.connect(_on_right_v_scroll)
	diff_left_view.get_h_scroll_bar().value_changed.connect(_on_left_h_scroll)
	diff_right_view.get_h_scroll_bar().value_changed.connect(_on_right_h_scroll)

	hsplit.add_child(left_vbox)
	hsplit.add_child(right_vbox)
	main_vbox.add_child(hsplit)
	diff_window.add_child(main_vbox)

	EditorInterface.get_base_control().add_child(diff_window)


func _on_left_v_scroll(val: float) -> void:
	if is_syncing_scroll:
		return
	is_syncing_scroll = true
	diff_right_view.scroll_vertical = int(val)
	is_syncing_scroll = false


func _on_right_v_scroll(val: float) -> void:
	if is_syncing_scroll:
		return
	is_syncing_scroll = true
	diff_left_view.scroll_vertical = int(val)
	is_syncing_scroll = false


func _on_left_h_scroll(val: float) -> void:
	if is_syncing_scroll:
		return
	is_syncing_scroll = true
	diff_right_view.scroll_horizontal = int(val)
	is_syncing_scroll = false


func _on_right_h_scroll(val: float) -> void:
	if is_syncing_scroll:
		return
	is_syncing_scroll = true
	diff_left_view.scroll_horizontal = int(val)
	is_syncing_scroll = false


func _on_diff_right_selection_changed() -> void:
	if diff_inject_partial_btn and diff_right_view:
		var has_sel = (
			diff_right_view.has_selection()
			and diff_right_view.get_selected_text().strip_edges() != ""
		)
		diff_inject_partial_btn.disabled = not has_sel


func _build_simulated_after_code(original_code: String, incoming_code: String) -> String:
	if original_code.strip_edges() == "":
		return incoming_code
		var active_edit = _get_active_script_text_edit()
		if not active_edit:
			return original_code + "\n\n" + incoming_code
			var lines = original_code.split("\n")
			var caret_line = clampi(active_edit.get_caret_line(), 0, max(0, lines.size() - 1))
			var caret_col = active_edit.get_caret_column()
			if lines.size() == 0:
				return incoming_code
				var target_line = lines[caret_line]
				var safe_col = clampi(caret_col, 0, target_line.length())
				var prefix = target_line.substr(0, safe_col)
				var suffix = target_line.substr(safe_col)
				lines[caret_line] = prefix + incoming_code + suffix
				return "\n".join(lines)


func _trigger_diff_comparison_view(incoming_code: String) -> void:
	pending_injection_code = incoming_code
	var original_code = ""
	var script_editor = EditorInterface.get_script_editor()
	if script_editor:
		var current_script = script_editor.get_current_script()
		if current_script:
			original_code = current_script.source_code
			var simulated_after_code = _build_simulated_after_code(original_code, incoming_code)
			diff_left_view.clear()
			diff_right_view.clear()
			diff_left_view.text = original_code
			diff_right_view.text = simulated_after_code
			diff_inject_partial_btn.disabled = true
			var left_lines = original_code.split("\n")
			var right_lines = simulated_after_code.split("\n")
			var first_diff_line = -1
			for i in range(left_lines.size()):
				if i >= right_lines.size() or left_lines[i] != right_lines[i]:
					diff_left_view.set_line_background_color(i, Color(0.55, 0.12, 0.12, 0.28))
					if first_diff_line == -1:
						first_diff_line = i
					for j in range(right_lines.size()):
						if j >= left_lines.size() or right_lines[j] != left_lines[j]:
							diff_right_view.set_line_background_color(
								j, Color(0.12, 0.55, 0.22, 0.28)
							)
							if first_diff_line == -1:
								first_diff_line = j
							diff_window.popup_centered()
							# Auto-scroll both windows to the first modified line
							if first_diff_line > 0:
								var target_scroll = max(0, first_diff_line - 3)
								diff_left_view.scroll_vertical = target_scroll
								diff_right_view.scroll_vertical = target_scroll


func _on_diff_custom_action(action_name: StringName) -> void:
	if action_name == &"inject_partial":
		var selected_chunk = diff_right_view.get_selected_text()
		if selected_chunk.strip_edges() != "":
			_insert_code_into_active_editor(selected_chunk)
			_show_ui_notification_banner("Partial chunk injected at caret.", Color(0.2, 0.75, 0.95))
			diff_window.hide()
			pending_injection_code = ""


func _on_diff_window_confirmed() -> void:
	if pending_injection_code != "":
		if _run_code_diagnostics(pending_injection_code):
			_insert_code_into_active_editor(pending_injection_code)
			_show_ui_notification_banner(
				"Full offering committed via Before/After Diff.", Color(0.1, 0.8, 0.5)
			)
			pending_injection_code = ""


func _show_ui_notification_banner(message: String, accent_color: Color) -> void:
	var script_editor = EditorInterface.get_script_editor()
	if not script_editor:
		return
	var banner = PanelContainer.new()
	var style = StyleBoxFlat.new()
	style.bg_color = Color(0.12, 0.12, 0.16, 0.95)
	style.border_width_bottom = 3
	style.border_color = accent_color
	style.corner_radius_bottom_left = 6
	style.corner_radius_bottom_right = 6
	banner.add_theme_stylebox_override("panel", style)
	banner.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	banner.custom_minimum_size = Vector2(400, 45)
	var margin = MarginContainer.new()
	margin.add_theme_constant_override("margin_left", 15)
	margin.add_theme_constant_override("margin_right", 15)
	var label = Label.new()
	label.text = "⚡ T.A.L.O.S: " + message
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.add_theme_color_override("font_color", Color(0.95, 0.95, 0.95))
	margin.add_child(label)
	banner.add_child(margin)
	script_editor.add_child(banner)
	banner.set_anchors_and_offsets_preset(Control.PRESET_TOP_WIDE, Control.PRESET_MODE_MINSIZE)
	banner.offset_top = 10
	var banner_timer = script_editor.get_tree().create_timer(3.2)
	banner_timer.timeout.connect(
		func():
			if is_instance_valid(banner):
				banner.queue_free()
	)


func _run_code_diagnostics(code_to_verify: String) -> bool:
	if code_to_verify.strip_edges() == "":
		return false
	# Combine with active script context so partial snippets compile cleanly during syntax checks
	var full_test_source = code_to_verify
	var script_editor = EditorInterface.get_script_editor()
	if script_editor and script_editor.get_current_script():
		full_test_source = _build_simulated_after_code(
			script_editor.get_current_script().source_code, code_to_verify
		)
	var dynamic_script = GDScript.new()
	dynamic_script.source_code = full_test_source
	var compilation_error = dynamic_script.reload()
	if compilation_error != OK:
		_show_ui_notification_banner(
			"Syntax Check Warning! Merged script has parse errors.", Color(0.9, 0.2, 0.2)
		)
		if status_label:
			status_label.text = "Status: Diagnostic Error (Verification Stopped)"
			_set_status_color(Color(0.9, 0.2, 0.2))
		return false
	return true


func get_next_backup_index() -> int:
	var highest_index = 0
	var dir = DirAccess.open(CACHE_DIR)
	if dir:
		dir.list_dir_begin()
		var file_name = dir.get_next()
		while file_name != "":
			if (
				not dir.current_is_dir()
				and file_name.begins_with("Backup")
				and file_name.ends_with(".cache")
			):
				var structures = file_name.split("_")
				if structures.size() > 1:
					var index_val = structures[1].to_int()
					if index_val > highest_index:
						highest_index = index_val
						file_name = dir.get_next()
						return highest_index + 1


func _write_to_offline_cache(_hash_signature: String, code_content: String) -> void:
	if code_content.strip_edges() == "":
		return
	var next_idx = _get_next_backup_index()
	var time_dict = Time.get_time_dict_from_system()
	var time_stamp = "%02d-%02d" % [time_dict["hour"], time_dict["minute"]]
	var custom_backup_filename = "Backup_%04d_%s" % [next_idx, time_stamp]
	var path = CACHE_DIR + custom_backup_filename + ".cache"
	var file = FileAccess.open(path, FileAccess.WRITE)
	if file:
		file.store_string(code_content)
		file.close()
		_refresh_history_list()


func _read_from_offline_cache(filename_signature: String) -> String:
	var path = CACHE_DIR + filename_signature + ".cache"
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
			if not dir.current_is_dir() and file_name.ends_with(".cache"):
				dir.remove(file_name)
				count += 1
				file_name = dir.get_next()
				if status_label:
					status_label.text = "Status: Purged %d Cached Files" % count
					_set_status_color(Color(0.9, 0.3, 0.3))
					_show_ui_notification_banner(
						"Cache system cleared completely.", Color(0.9, 0.3, 0.3)
					)
					_refresh_history_list()
					if history_preview:
						history_preview.text = ""


func _refresh_history_list() -> void:
	if not history_list:
		return
	history_list.clear()
	history_hashes.clear()
	var dir = DirAccess.open(CACHE_DIR)
	if dir:
		dir.list_dir_begin()
		var file_name = dir.get_next()
		while file_name != "":
			if not dir.current_is_dir() and file_name.ends_with(".cache"):
				var raw_filename = file_name.replace(".cache", "")
				history_hashes.append(raw_filename)
				history_list.add_item(raw_filename)
				file_name = dir.get_next()


func _on_history_item_selected(index: int) -> void:
	if index >= history_hashes.size() or not history_preview:
		return
	var target_filename = history_hashes[index]
	var cached_code = _read_from_offline_cache(target_filename)
	history_preview.text = cached_code
	if history_insert_button:
		history_insert_button.disabled = false


func _on_history_insert_pressed() -> void:
	if history_preview and history_preview.text != "":
		_trigger_diff_comparison_view(history_preview.text)


func _init_cache_directory() -> void:
	if not DirAccess.dir_exists_absolute(CACHE_DIR):
		DirAccess.make_dir_absolute(CACHE_DIR)


func _init_editor_settings_configs() -> void:
	if not ProjectSettings.has_setting(SETTING_SHORTCUT):
		ProjectSettings.set_setting(SETTING_SHORTCUT, "T")
		ProjectSettings.set_initial_value(SETTING_SHORTCUT, "T")
		var property_info = {
			"name": SETTING_SHORTCUT,
			"type": TYPE_STRING,
			"hint": PROPERTY_HINT_NONE,
			"hint_string":
			"The alpha key triggered alongside Ctrl+Shift to force T.A.L.O.S invocations"
		}
		ProjectSettings.add_property_info(property_info)
		ProjectSettings.save()


func _input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed:
		var configured_key = ProjectSettings.get_setting(SETTING_SHORTCUT, "T").to_upper()
		var target_keycode = OS.find_keycode_from_string(configured_key)
		if event.ctrl_pressed and event.shift_pressed and event.keycode == target_keycode:
			if send_button and not send_button.disabled:
				get_viewport().set_input_as_handled()
				_on_send_button_pressed()


func _apply_segmented_style(bar: ProgressBar) -> void:
	var bg_style = StyleBoxFlat.new()
	bg_style.bg_color = Color(0.08, 0.08, 0.1, 1.0)
	bg_style.corner_radius_top_left = 4
	bg_style.corner_radius_bottom_left = 4
	bg_style.corner_radius_top_right = 4
	bg_style.corner_radius_bottom_right = 4
	var fg_style = StyleBoxFlat.new()
	fg_style.bg_color = Color(0.0, 0.75, 0.65, 1.0)
	fg_style.border_width_right = 3
	fg_style.border_color = Color(0.08, 0.08, 0.1, 1.0)
	fg_style.corner_radius_top_left = 2
	fg_style.corner_radius_bottom_left = 2
	bar.add_theme_stylebox_override("background", bg_style)
	bar.add_theme_stylebox_override("fill", fg_style)


func _set_status_color(color: Color) -> void:
	if status_label:
		status_label.add_theme_color_override("font_color", color)


func _on_progress_tick() -> void:
	if progress_bar:
		if progress_bar.value >= progress_bar.max_value:
			progress_bar.value = 0
	else:
		progress_bar.value += progress_bar.step


func _fetch_local_ollama_models() -> void:
	if not status_label:
		return
	status_label.text = "Status: Querying host models..."
	_set_status_color(Color(0.8, 0.5, 0.1))
	var error = http_node.request(OLLAMA_TAGS_URL, [], HTTPClient.METHOD_GET)
	if error != OK:
		status_label.text = "Status: Local Server Offline"
		_set_status_color(Color(0.9, 0.5, 0.2))


func _on_model_selected(index: int) -> void:
	if not model_select_menu or not status_label:
		return
	selected_model_name = model_select_menu.get_item_text(index)
	status_label.text = "Status: Switched to " + selected_model_name
	_set_status_color(Color(0.2, 0.7, 0.9))


func _load_local_xml_docs(class_name_str: String) -> String:
	var doc_context = ""
	var file_path = LOCAL_XML_DOCS_PATH + class_name_str.to_lower() + ".xml"
	if not FileAccess.file_exists(file_path):
		return "[No XML found for class %s. Using ClassDB data.]\n" % class_name_str

	var file = FileAccess.open(file_path, FileAccess.READ)
	if file:
		var parser = XMLParser.new()
		parser.open(file_path)
		var inside_description = false
		while parser.read() == OK:
			var node_type = parser.get_node_type()
			var node_name = parser.get_node_name()
			if node_type == XMLParser.NODE_ELEMENT:
				if node_name == "description":
					inside_description = true
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
	if scene_root:
		scene_context += "\n--- Edited Active Scene Tree Hierarchy ---\n"
		var children = scene_root.find_children("*", "", true, false)
		for child in children:
			scene_context += (
				" -> Node Path Element: %s (Type: %s)\n"
				% [scene_root.get_path_to(child), child.get_class()]
			)
			var script = child.get_script()
			if script and script is Script:
				var lines = script.source_code.split("\n")
				var line_count = 0
				for line in lines:
					if line_count > 15:
						break
					if (
						line.begins_with("var")
						or line.begins_with("signal")
						or line.begins_with("func")
					):
						scene_context += "     | %s\n" % line.strip_edges()
						line_count += 1
	return scene_context


func _get_editor_context() -> String:
	var context = ""
	var script_editor = EditorInterface.get_script_editor()
	if script_editor:
		var current_script = script_editor.get_current_script()
		if current_script:
			context += "\n--- Current Active Script (%s) ---\n" % current_script.resource_path
			context += current_script.source_code + "\n"
			var base_class = current_script.get_instance_base_type()
			context += _load_local_xml_docs(base_class)
			var methods = ClassDB.class_get_method_list(base_class)
			var method_count = 0
			for method in methods:
				if method_count > 10:
					break
				if (
					not method["name"].begins_with("_")
					or method["name"] in ["_ready", "_process", "_physics_process"]
				):
					context += "Native Method: %s()\n" % method["name"]
					method_count += 1
	context += _get_deep_scene_context()
	return context


func _get_active_script_text_edit() -> TextEdit:
	var script_editor = EditorInterface.get_script_editor()
	if script_editor:
		var base_editor = script_editor.get_current_editor()
		if base_editor:
			var text_edits = base_editor.find_children("*", "TextEdit", true, false)
			if text_edits.size() > 0 and text_edits[0] is TextEdit:
				return text_edits[0]
	return null


func _on_send_button_pressed() -> void:
	var user_prompt = input_line.text.strip_edges()
	if user_prompt == "":
		var active_edit = _get_active_script_text_edit()
		if active_edit and active_edit.has_selection():
			user_prompt = active_edit.get_selected_text().strip_edges()
	if user_prompt == "":
		if status_label:
			status_label.text = "Status: Prompt Blank"
			_set_status_color(Color(0.9, 0.4, 0.4))
		return

	output_box.text = "Talos is forging . . ."
	input_line.clear()
	if status_label:
		status_label.text = "Status: Forging code structure..."
		_set_status_color(Color(0.2, 0.8, 0.5))
	if progress_bar:
		progress_bar.value = 0
	if progress_timer:
		progress_timer.start()
	if send_button:
		send_button.disabled = true
	if cancel_button:
		cancel_button.disabled = false
	if clear_cache_button:
		clear_cache_button.disabled = true
	if model_select_menu:
		model_select_menu.disabled = true

	var project_context = _get_editor_context()
	var system_prompt = (
		"You are T.A.L.O.S, a local computational system. "
		+ "You are a strict Godot 4.4 engine expert that explains thoroughly. "
		+ "Return only clean code blocks."
	)
	var combined_prompt = (
		"CONTEXT Strings:\n" + project_context + "\n\nUSER REQUEST: " + user_prompt
	)
	var raw_combination_string = combined_prompt + "_" + selected_model_name
	running_request_hash = raw_combination_string.md5_text()
	var body = {
		"model": selected_model_name,
		"prompt": combined_prompt,
		"system": system_prompt,
		"stream": false,
		"options": {"temperature": 0.1},
	}
	var headers = ["Content-Type: application/json"]
	var request_err = http_node.request(
		OLLAMA_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(body)
	)
	if request_err != OK:
		_execute_offline_fallback_procedure("HTTP Engine Request Failure")


func _on_cancel_button_pressed() -> void:
	if http_node.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		http_node.cancel()
		if progress_timer:
			progress_timer.stop()
		if progress_bar:
			progress_bar.value = 0
		if send_button:
			send_button.disabled = false
		if cancel_button:
			cancel_button.disabled = true
		if clear_cache_button:
			clear_cache_button.disabled = false
		if model_select_menu:
			model_select_menu.disabled = false
		output_box.text = "Forging Process Aborted."
		if status_label:
			status_label.text = "Status: Aborted"
			_set_status_color(Color(0.9, 0.6, 0.2))


func _on_http_routing_coordinator(
	_result: int, response_code: int, _header: PackedStringArray, body: PackedByteArray
) -> void:
	var raw_str = body.get_string_from_utf8()
	var json = JSON.new()
	if json.parse(raw_str) == OK:
		var parsed = json.get_data()
		if parsed is Dictionary and parsed.has("models"):
			_process_tags_response(response_code, parsed)
			return
	_handle_generation_response(response_code, body)


func _process_tags_response(response_code: int, data: Dictionary) -> void:
	if not status_label or not model_select_menu:
		return
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
		if output_box.text != "Forging Process Aborted.":
			_execute_offline_fallback_procedure("Server Response Code %d" % response_code)
		return

	if progress_timer:
		progress_timer.stop()
	if send_button:
		send_button.disabled = false
	if cancel_button:
		cancel_button.disabled = true
	if clear_cache_button:
		clear_cache_button.disabled = false
	if model_select_menu:
		model_select_menu.disabled = false
	if progress_bar:
		progress_bar.value = progress_bar.max_value
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
			_write_to_offline_cache(running_request_hash, clean_code)
			_show_ui_notification_banner("Generation Finished & Cached.", Color(0.1, 0.8, 0.5))
			DisplayServer.clipboard_set(clean_code)
			if auto_insert_checkbox.button_pressed:
				_trigger_diff_comparison_view(clean_code)


func _execute_offline_fallback_procedure(reason_str: String) -> void:
	if progress_timer:
		progress_timer.stop()
	if send_button:
		send_button.disabled = false
	if cancel_button:
		cancel_button.disabled = true
	if clear_cache_button:
		clear_cache_button.disabled = false
	if model_select_menu:
		model_select_menu.disabled = false
	var cached_script = _read_from_offline_cache(running_request_hash)
	if cached_script != "":
		if progress_bar:
			progress_bar.value = progress_bar.max_value
		output_box.text = cached_script
		DisplayServer.clipboard_set(cached_script)
		if status_label:
			status_label.text = "Status: Offline Fallback Resolved"
			_set_status_color(Color(0.0, 0.75, 0.85))
		_show_ui_notification_banner(
			"Server unreachable. Resolved from offline cache.", Color(0.0, 0.75, 0.85)
		)
		if auto_insert_checkbox.button_pressed:
			_trigger_diff_comparison_view(cached_script)
	else:
		if progress_bar:
			progress_bar.value = 0
		output_box.text = (
			"Error: Ollama Host Unreachable (%s).\nNo cache matches found." % reason_str
		)
		if status_label:
			status_label.text = "Status: Core Offline & Cache Miss"
			_set_status_color(Color(0.9, 0.2, 0.2))


func _extract_code_blocks(raw_input: String) -> String:
	if not "```" in raw_input:
		return raw_input.strip_edges()

	var lines = raw_input.split("\n")
	var extracted_code = ""
	var inside_block = false

	for line in lines:
		if line.begins_with("```"):
			inside_block = not inside_block
			continue
		if inside_block:
			extracted_code += line + "\n"

	return extracted_code.strip_edges()


func _insert_code_into_active_editor(code_to_insert: String) -> void:
	var target_edit = _get_active_script_text_edit()
	if target_edit:
		target_edit.insert_text_at_caret(code_to_insert)
