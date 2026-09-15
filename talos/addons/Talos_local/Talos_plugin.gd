@tool
extends EditorPlugin

var dock : VBoxContainer
var output_box : TextEdit
var input_line : LineEdit
var send_button : Button
var auto_insert_checkbox : CheckBox
var http_node: HTTPRequest

const OLLAMA_URL = "http://localhost:11434/api/generate"
const MODEL_NAME = "qwen2.5-coder:3b"
const LOCAL_XML_DOCS_PATH = "res://doc_classes/"

func _enter_tree() -> void:
	#load custom ui scene
	dock = VBoxContainer.new()
	dock.name = "T.A.L.O.S"
	
	dock.custom_minimum_size = Vector2(250, 400)
	dock.size_flags_vertical = Control.SIZE_EXPAND_FILL
	dock.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	
	output_box = TextEdit.new()
	output_box.editable = false
	output_box.placeholder_text = " talos output will appear here.."
	output_box.size_flags_vertical = Control.SIZE_EXPAND_FILL
	
	auto_insert_checkbox = CheckBox.new()
	auto_insert_checkbox.text = "auto insert at cursor position"
	auto_insert_checkbox.button_pressed = false
	
	input_line = LineEdit.new()
	input_line.placeholder_text = "Requst a offering to T.A.L.O.S for a creation"
	
	send_button = Button.new()
	send_button.text = "offer to T.A.L.O.S"
	
	http_node = HTTPRequest.new()
	
	dock.add_child(output_box)
	dock.add_child(auto_insert_checkbox)
	dock.add_child(input_line)
	dock.add_child(send_button)
	dock.add_child(http_node)
	
	send_button.pressed.connect(_on_send_button_pressed)
	http_node.request_completed.connect(_on_TALOS_response)
	
	add_control_to_dock(EditorPlugin.DOCK_SLOT_RIGHT_BR, dock)
	print("talos ui forced into editor successfully.")

func _exit_tree() -> void:
	if dock:
		remove_control_from_docks(dock)
		dock.queue_free()

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
		
		while  parser.read() == OK:
			var node_type = parser.get_node_type()
			var node_name = parser.get_node_name()
			
			if node_type == XMLParser.NODE_ELEMENT:
				if node_name == "description":
					inside_description = true
			elif node_name == "method":
				method_name = parser.get_named_attribute_value_safe("name")
				doc_context += " - Method API: %s\n" % method_name
			elif  node_type == XMLParser.NODE_TEXT and inside_description:
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
	var script_editor = get_editor_interface().get_script_editor()
	var current_script = get_editor_interface().get_script_editor().get_current_script()
	
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
			if  not method["name"].begin_with("_") or method["name"] in ["_ready","_process","_physics_process"]:
				context += "Native Method: %s()\n" % method["name"]
				method_count += 1 
	return context

func _on_send_button_pressed() -> void:
	var user_prompt = input_line.text.strip_edges()
	if user_prompt == "": return
	
	output_box.text = "Talos is forging . . ."
	input_line.clear()
	
	var project_context = _get_editor_context()
	
	#system prompt to stay with in Godot 4.4 documentation
	var  system_prompt = ("You are T.A.L.O.S , a local computational system. you are a strict Godot 4.4 engine expert that explains throughly. " +
	"Use the provided active script structure and ClassDB documentation context below to answer." +
	"Never hallucinate methods. Match the variables, node names, and structural architecture explicitly provided. " +
	"Return only clean code blocks"
	)
	
	var combined_prompt = "CONTEXT Strings:\n" + project_context + "\n\nUSER REQUEST: " + user_prompt
	
	# formulate the payload according to the api schema
	var body = {
		"model": MODEL_NAME,
		"prompt": user_prompt,
		"system": system_prompt,
		"stream": false, # returns on ecomplete package instead of streaming chunks
		"options": {
			"temperature": 0.1 # lower temperature make ai folloe more closer
				}
		}
		
	var headers = ["content-type: application/json"]
	http_node.request(OLLAMA_URL,headers,HTTPClient.METHOD_POST , JSON.stringify(body))
		

func _on_TALOS_response(result: int, responce_code: int , header: PackedStringArray, body: PackedByteArray) -> void:
	if responce_code != 200:
		output_box.text = " error connecting to local Ollama server.Ensure it's runnning!
		Talos is depowered for the moment"
		return
	
	var json = JSON.new()
	if json.parse(body.get_string_from_utf8()) == OK:
		var response_data = json.get_data()
		if response_data.has("response"):
			var ai_raw_response = response_data["response"]
			var clean_code = ai_raw_response
			if "```" in clean_code:
				var lines = clean_code.split("\n")
				clean_code = ""
				var inside_block = false
				for line in lines:
					if line.begin_with("```"):
						inside_block = !inside_block
						continue
					clean_code += line + "\n"
			output_box.text = clean_code
			#added to clipboard instantly for pating upon call
			DisplayServer.clipboard_set(clean_code)
			
			if auto_insert_checkbox.button_pressed:
				_insert_code_into_active_editor(clean_code)

func _insert_code_into_active_editor(code_to_insert: String) -> void:
	var script_editor = get_editor_interface().get_script_editor()
	var base_editor = script_editor.get_current_editor()
	
	if  base_editor:
		var text_edits  = base_editor.find_children("*", "TextEdit", true, false)
		if text_edits.size() > 0 and text_edits[0] is TextEdit:
			var target_edit : TextEdit = text_edits[0] as TextEdit
			target_edit.insert_text_at_caret(code_to_insert)
			print(" Talos auto insert triggered succesfully.")
		else:
			var found_edit = _find_text_edit_recursive(base_editor)
			if found_edit:
				found_edit.insert_text_at_caret(code_to_insert)
				print("talos auto insertion triggered via fallback")
			else:
				print(" TALOS WARNING: could loacte textedit area inside coding window")

func _find_text_edit_recursive(current_node : Node) -> TextEdit:
	if current_node is TextEdit:
		return current_node
	for child in current_node.get_children():
		var result = _find_text_edit_recursive(child)
		if result:
			return result
	return null
