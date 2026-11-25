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
var manual_pannel : VBoxContainer

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
var diff_left_view: CodeEdit
var diff_right_view: CodeEdit
var diff_inject_partial_btn: Button
var diff_block_selector : OptionButton
var parsed_code_blocks : Array[String] = []
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
	_apply_gdscript_highligher(output_box)
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
	input_line.placeholder_text = "Request an offering to T.A.L.O.S...(Press Enter)"
	input_line.text_submitted.connect(func(_new_text: String): _on_send_button_pressed())
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
	_apply_gdscript_highligher(history_preview)
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

	_build_manual_tab()
	main_tabs.add_child(manual_pannel)
	
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

	_fetch_local_ollama_models.call_deferred()
	_refresh_history_list()

func _build_manual_tab() -> void:
		manual_pannel = VBoxContainer.new()
		manual_pannel.name = "Manual"
		manual_pannel.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		manual_pannel.size_flags_vertical = Control.SIZE_EXPAND_FILL
	
		var manual_text = RichTextLabel.new()
		manual_text.bbcode_enabled = true
		manual_text.fit_content = false
		manual_text.scroll_active = true
		manual_text.selection_enabled = true
		manual_text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		manual_text.size_flags_vertical = Control.SIZE_EXPAND_FILL
	
		manual_text.text = """[b][color = #4dd0e1] T.A.L.O.S --- OPERATIONS MANUAL[/color][/b]
		[color = #90a4ae]Local Ollama GDScript Assistant[/color]
		
		[b][color = #81c784]1. QUICKSTART[/color][/b]
		Ensure [b]Ollama[/b] is running locally on port [code]11434[/code].
		• Open a [code].gd[/code] script and place your cursor where you want code inserted.
		• Select an installed model from the [b]Model[/b] dropdown.
		• Type a request in the bottom bar and press [b]Enter[/b] or click [b]Offer Prompt[/b].

		[b][color=#81c784]2. SELECTION-AS-PROMPT[/color][/b]
		• Leave the prompt input box blank.
		• Highlight lines of code inside the Godot Script Editor.
		• Click [b]Offer Prompt[/b] or press [b]Ctrl + Shift + T[/b] to send your selection directly.

		[b][color=#81c784]3. BEFORE & AFTER DIFF SCREEN[/color][/b]
		• [b]Active Block Dropdown:[/b] Switch between individual generated blocks ([i]Block 1 Only[/i], [i]Block 2 Only[/i]) or view all blocks combined.
		• [b]Inject Selected Block at Caret:[/b] Runs a GDScript syntax check and inserts the active block at your cursor.
		• [b]Inject Highlighted Selection Only:[/b] Drag-select specific lines in the [b]AFTER[/b] panel to insert just that chunk.
		• [b]Replace Entire Script:[/b] Overwrites the entire active script after passing syntax validation.

		[b][color=#81c784]4. OFFLINE CACHE & HISTORY[/color][/b]
		• Every generation is saved in [code]user://talos_cache/[/code] and copied to your clipboard.
		• Use the [b]History Modules[/b] tab to preview and re-inject previous outputs anytime.
		• Click [b]Clear Cache Database[/b] to delete all saved [code].cache[/code] files.

		[b][color=#81c784]5. SHORTCUTS & SETTINGS[/color][/b]
		• [b]Enter:[/b] Submit prompt from input bar.
		• [b]Ctrl + Shift + T:[/b] Trigger T.A.L.O.S from anywhere in the editor.
		• Customize the trigger key under [b]Project Settings > Plugins > Talos > Shortcut Key[/b] (enable [i]Advanced Settings[/i])."""
		
		
		manual_pannel.add_child(manual_text)
		var manual_btn_box = HBoxContainer.new()
		manual_btn_box.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	
		var ping_ollama_btn = Button.new()
		ping_ollama_btn.text = "Test Ollama Connection"
		ping_ollama_btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		ping_ollama_btn.pressed.connect(_on_test_ollama_connection_pressed)
	
	
		var copy_diag_btn = Button.new()
		copy_diag_btn.text = "Copy Troubleshooting Info"
		copy_diag_btn.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		copy_diag_btn.pressed.connect(_on_copy_troubleshooting_pressed)
	
		manual_pannel.add_child(copy_diag_btn)
		manual_pannel.add_child(ping_ollama_btn)
		manual_pannel.add_child(manual_btn_box)

func _on_copy_troubleshooting_pressed() -> void:
	var godot_ver = Engine.get_version_info().get("string", "Unknown")
	var shortcut_key = ProjectSettings.get_setting(SETTING_SHORTCUT, "T")
	var current_status = status_label.text if status_label else "Unknown"
	
	var active_script_path = "None"
	var script_editor = EditorInterface.get_script_editor()
	if script_editor and script_editor.get_current_script():
		active_script_path = script_editor.get_current_script().resource_path
		
	var diag_report = (
		"=== T.A.L.O.S Diagnostic Report ===\n"
		+ "Godot Version: %s\n" % godot_ver
		+ "Ollama Endpoint: %s\n" % OLLAMA_URL
		+ "Selected Model: %s\n" % selected_model_name
		+ "Current Status: %s\n" % current_status
		+ "Shortcut Key: Ctrl + Shift + %s\n" % shortcut_key
		+ "Cached Modules: %d\n" % history_hashes.size()
		+ "Active Script: %s\n" % active_script_path
		+ "==================================="
	)
	
	DisplayServer.clipboard_set(diag_report)
	_show_ui_notification_banner("Troubleshooting report copied to clipboard.", Color(0.2, 0.75, 0.95))

func _on_test_ollama_connection_pressed() -> void:
	if not http_node:
		return
		
	if http_node.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		_show_ui_notification_banner("HTTP client busy. Finish or abort current request first.", Color(0.9, 0.6, 0.2))
		return
		
	if status_label:
		status_label.text = "Status: Pinging Ollama server..."
		_set_status_color(Color(0.8, 0.5, 0.1))
		
	var error = http_node.request(OLLAMA_TAGS_URL, [], HTTPClient.METHOD_GET)
	if error != OK:
		if status_label:
			status_label.text = "Status: Connection Failed (Error %d)" % error
			_set_status_color(Color(0.9, 0.2, 0.2))
		_show_ui_notification_banner("Failed to reach Ollama at %s." % OLLAMA_TAGS_URL, Color(0.9, 0.2, 0.2))
	else:
		_show_ui_notification_banner("Ping sent to Ollama. Check Status label for result.", Color(0.2, 0.75, 0.95))

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
	diff_window.min_size = Vector2i(980, 650)
	diff_window.ok_button_text = "Inject Full Offering"
	diff_window.confirmed.connect(_on_diff_window_confirmed)

	# Custom Action Button for Partial Selection Injection
	diff_inject_partial_btn = diff_window.add_button(
		"Inject Highlighted Selection Only", false, "inject_partial")
	diff_inject_partial_btn.disabled = true
	diff_window.custom_action.connect(_on_diff_custom_action)

	var main_vbox = VBoxContainer.new()
	main_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	main_vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL

	var top_bar = HBoxContainer.new()
	var selector_lbl = Label.new()
	selector_lbl.text = "Active Generated Block: "

	diff_block_selector = OptionButton.new()
	diff_block_selector.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	diff_block_selector.item_selected.connect(_on_diff_block_selected)

	top_bar.add_child(selector_lbl)
	top_bar.add_child(diff_block_selector)
	main_vbox.add_child(top_bar)


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
	hsplit.split_offset = 480

	# BEFORE Screen (Left Column Container)
	var left_vbox = VBoxContainer.new()
	left_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	left_vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var left_lbl = Label.new()
	left_lbl.text = "BEFORE (Current Active Script)"
	left_lbl.add_theme_color_override("font_color", Color(0.9, 0.5, 0.5))
	diff_left_view = CodeEdit.new()
	diff_left_view.editable = false
	diff_left_view.gutters_draw_line_numbers = true
	diff_left_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_apply_gdscript_highligher(diff_left_view)
	left_vbox.add_child(left_lbl)
	left_vbox.add_child(diff_left_view)

	# AFTER Screen (Right Column Container)
	var right_vbox = VBoxContainer.new()
	right_vbox.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	right_vbox.size_flags_vertical = Control.SIZE_EXPAND_FILL
	var right_lbl = Label.new()
	right_lbl.text = "AFTER (Simulated Result with T.A.L.O.S Offering)"
	right_lbl.add_theme_color_override("font_color", Color(0.4, 0.9, 0.6))
	diff_right_view = CodeEdit.new()
	diff_right_view.editable = false
	diff_right_view.gutters_draw_line_numbers = true
	diff_right_view.size_flags_vertical = Control.SIZE_EXPAND_FILL
	diff_right_view.caret_changed.connect(_on_diff_right_selection_changed)
	_apply_gdscript_highligher(diff_right_view)
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

func _apply_gdscript_highligher(target_edit : TextEdit) -> void:
	if not target_edit:
		return
	
	var highlighter = CodeHighlighter.new()
	
	# Base token colors
	highlighter.number_color = Color(0.63, 1.0, 0.88)
	highlighter.symbol_color = Color(0.67, 0.79, 1.0)
	highlighter.function_color = Color(0.34, 0.7, 1.0)
	highlighter.member_variable_color = Color(0.73, 0.88, 1.0)
	
	# Control flow keywords (pink/red)
	var control_keywords = [
		"if", "elif", "else", "for", "while", "match", 
		"break", "continue", "pass", "return", "await", "yield"
	]
	for kw in control_keywords:
		highlighter.add_keyword_color(kw, Color(1.0, 0.44, 0.52))
		
	# Declaration & logic keywords (coral/orange)
	var decl_keywords = [
		"func", "var", "const", "signal", "enum", "class", 
		"class_name", "extends", "static", "true", "false", 
		"null", "self", "super", "and", "or", "not", "in", "is", "as"
	]
	for kw in decl_keywords:
		highlighter.add_keyword_color(kw, Color(1.0, 0.55, 0.45))
		
	# Built-in Godot types (teal/green)
	var builtin_types = [
		"void", "bool", "int", "float", "String", "StringName",
		"Vector2", "Vector2i", "Vector3", "Vector3i", "Color", "Rect2",
		"Node", "Node2D", "Node3D", "Control", "Array", "Dictionary",
		"PackedStringArray", "PackedByteArray"
	]
	for t in builtin_types:
		highlighter.add_keyword_color(t, Color(0.26, 0.85, 0.72))
		
	# Comments, Strings, and @Annotations
	highlighter.add_color_region("#", "", Color(0.5, 0.55, 0.6), true)
	highlighter.add_color_region("\"", "\"", Color(1.0, 0.93, 0.63), false)
	highlighter.add_color_region("'", "'", Color(1.0, 0.93, 0.63), false)
	highlighter.add_color_region("@", " ", Color(1.0, 0.7, 0.4), false)
	
	# Apply to the TextEdit
	target_edit.syntax_highlighter = highlighter

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
		var has_selection = (
			diff_right_view.has_selection()
			and diff_right_view.get_selected_text().strip_edges() != ""
		)
		diff_inject_partial_btn.disabled = not has_selection


func _build_simulated_after_code(original_code: String, incoming_code: String) -> String:
	if original_code.strip_edges() == "":
		return incoming_code

	var active_edit = _get_active_script_text_edit()
	if not active_edit:
		return original_code + "\n\n" + incoming_code

	var lines = original_code.split("\n")
	if lines.is_empty():
		return incoming_code

	var caret_line = clampi(active_edit.get_caret_line(), 0, lines.size() - 1)
	var caret_col = active_edit.get_caret_column()
	var target_line = lines[caret_line]
	var safe_col = clampi(caret_col, 0, target_line.length())
	var prefix_text = target_line.substr(0, safe_col)
	var suffix_text = target_line.substr(safe_col)
	lines[caret_line] = prefix_text + incoming_code + suffix_text
	return "\n".join(lines)

func _parse_blocks_array(raw_input: String) -> Array[String]:
	var blocks : Array[String] = []
	if not "```" in raw_input:
		var cleaned = _clean_block_markers(raw_input)
		if cleaned != "":
			blocks.append(cleaned)
		return blocks
		
	var lines = raw_input.split("\n")
	var current_block = ""
	var inside_block = false
	
	for line in lines:
		if line.strip_edges().begins_with("```"):
			if inside_block:
				if current_block.strip_edges() != "":
					blocks.append(current_block.strip_edges())
				current_block = ""
			inside_block = !inside_block
			continue
		if inside_block:
			current_block += line + "\n"
			
	if blocks.is_empty() and raw_input.strip_edges() != "":
		blocks.append(_clean_block_markers(raw_input))
	return blocks

func _trigger_diff_comparison_view(incoming_code: String) -> void:
	parsed_code_blocks = _parse_blocks_array(incoming_code)
	if parsed_code_blocks.is_empty():
		return
		
	var original_code = ""
	var script_editor = EditorInterface.get_script_editor()
	if script_editor:
		var current_script = script_editor.get_current_script()
		if current_script:
			original_code = current_script.source_code
			
	diff_left_view.clear()
	diff_left_view.text = original_code
	
	# Populate Block Selector Dropdown
	diff_block_selector.clear()
	if parsed_code_blocks.size() > 1:
		diff_block_selector.add_item("All Blocks Combined (%d blocks)" % parsed_code_blocks.size(), 0)
		for i in range(parsed_code_blocks.size()):
			diff_block_selector.add_item("Block %d Only" % (i + 1), i + 1)
		diff_block_selector.select(1) # Default to Block 1 so you see individual blocks first
		_on_diff_block_selected(1)
	else:
		diff_block_selector.add_item("Block 1 (Single Offering)", 0)
		diff_block_selector.select(0)
		_on_diff_block_selected(0)
		
	diff_window.popup_centered()

func _on_diff_block_selected(index: int) -> void:
	if parsed_code_blocks.is_empty():
		return
		
	if parsed_code_blocks.size() > 1:
		if index == 0:
			pending_injection_code = "\n\n".join(parsed_code_blocks)
		else:
			pending_injection_code = parsed_code_blocks[index - 1]
	else:
		pending_injection_code = parsed_code_blocks[0]
		
	diff_right_view.clear()
	diff_right_view.text = pending_injection_code
	diff_inject_partial_btn.disabled = true
	
	# Highlight all lines in the right panel as proposed generated code
	for j in range(diff_right_view.get_line_count()):
		diff_right_view.set_line_background_color(j, Color(0.12, 0.55, 0.22, 0.25))
		
	diff_right_view.scroll_vertical = 0

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
	label.text = "T.A.L.O.S: " + message
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
		func() -> void:
			if is_instance_valid(banner):
				banner.queue_free()
	)


func _run_code_diagnostics(code_to_verify: String) -> bool:
	if code_to_verify.strip_edges() == "":
		return false

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
					var index_value = structures[1].to_int()
					if index_value > highest_index:
						highest_index = index_value
			file_name = dir.get_next()
	return highest_index + 1


func _write_to_offline_cache(_hash_signature: String, code_content: String) -> void:
	if code_content.strip_edges() == "":
		return
	var next_index = get_next_backup_index()
	var time_dict = Time.get_time_dict_from_system()
	var time_stamp = "%02d-%02d" % [time_dict["hour"], time_dict["minute"]]
	var custom_backup_filename = "Backup_%04d_%s" % [next_index, time_stamp]
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
		_show_ui_notification_banner("Cache system cleared completely.", Color(0.9, 0.3, 0.3))
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
	history_preview.text = _read_from_offline_cache(target_filename)
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
			"hint_string": "The alpha key triggered alongside Ctrl+Shift",
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
					doc_context += "Class Description: %s\n" % text
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
		+ "You are a strict Godot 4.4 engine expert. Return only clean code blocks."
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
	var request_error = http_node.request(
		OLLAMA_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(body)
	)
	if request_error != OK:
		_execute_offline_fallback_procedure("HTTP Engine Request Failure")


func _on_cancel_button_pressed() -> void:
	if http_node.get_http_client_status() != HTTPClient.STATUS_DISCONNECTED:
		http_node.cancel_request()
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
	var raw_string = body.get_string_from_utf8()
	var json = JSON.new()
	if json.parse(raw_string) == OK:
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
	for model in models_list:
		if model.has("name"):
			model_select_menu.add_item(model["name"])
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
		if response_data is Dictionary and response_data.has("response"):
			var ai_raw_response = response_data["response"]
			var display_blocks = _extract_code_blocks(ai_raw_response)
			var injectable_code = _clean_block_markers(display_blocks)
			
			output_box.text = display_blocks
			_write_to_offline_cache(running_request_hash, injectable_code)
			_show_ui_notification_banner("Generation Finished & Cached.", Color(0.1, 0.8, 0.5))
			DisplayServer.clipboard_set(injectable_code)
			if auto_insert_checkbox.button_pressed:
				_trigger_diff_comparison_view(injectable_code)


func _execute_offline_fallback_procedure(reason_string: String) -> void:
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
			"Error: Ollama Host Unreachable (%s).\nNo cache matches found." % reason_string
		)
		if status_label:
			status_label.text = "Status: Core Offline & Cache Miss"
			_set_status_color(Color(0.9, 0.2, 0.2))



func _extract_code_blocks(raw_input : String) -> String:
	if not "```" in raw_input:
		return raw_input.strip_edges()
	var lines = raw_input.split("\n")
	var blocks : Array[String] = []
	var current_block = ""
	var inside_block = false
	
	for line in lines:
		if line.strip_edges().begins_with("```"):
			if inside_block:
				if current_block.strip_edges() != "":
					blocks.append(current_block.strip_edges())
				current_block = ""
			inside_block = !inside_block
			continue
		if inside_block:
			current_block += line + "\n"
			
	if blocks.size() <= 1:
		return blocks[0] if blocks.size() == 1 else raw_input.strip_edges()
		
	var formatted_output = ""
	for i in range(blocks.size()):
		formatted_output += "# === [ BLOCK %d ] ===\n%s\n\n" % [i + 1, blocks[i]]
	return formatted_output.strip_edges()

func _clean_block_markers(code_text: String) -> String:
	var clean_lines : Array[String] = []
	for line in code_text.split("\n"):
		if not line.strip_edges().begins_with("# === [ BLOCK "):
			clean_lines.append(line)
	return "\n".join(clean_lines).strip_edges()

func _insert_code_into_active_editor(code_to_insert: String) -> void:
	var target_edit = _get_active_script_text_edit()
	if target_edit:
		target_edit.insert_text_at_caret(code_to_insert)
