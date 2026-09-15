@tool
extends EditorPlugin

var dock : VBoxContainer
var output_box : TextEdit
var input_line : LineEdit
var send_button : Button
var http_node: HTTPRequest

const OLLAMA_URL = "http://localhost:11434/api/generate"
const MODEL_NAME = "qwen2.5-coder:3b"


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
	
	input_line = LineEdit.new()
	input_line.placeholder_text = "Ask T.A.L.O.S for a creation"
	
	send_button = Button.new()
	send_button.text = "offer to T.A.L.O.S"
	
	http_node = HTTPRequest.new()
	
	dock.add_child(output_box)
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
func _on_send_button_pressed() -> void:
	var user_prompt = input_line.text.strip_edges()
	if user_prompt == "": return
	
	output_box.text = "Talos is forging . . ."
	input_line.clear()
	
	#system prompt to stay with in Godot 4.4 documentation
	var  system_prompt = ("You are T.A.L.O.S , a local computational system. Generate clean , vaild godot 4.4 GDscript. " +
	"Use modern features like @export, character2D, and lambda functions." +
	"Provide only raw, function code without introductory small talk.")
	
	# formulate the payload according to the api schema
	var body = {
		"model": MODEL_NAME,
		"prompt": user_prompt,
		"system": system_prompt,
		"stream": false # returns on ecomplete package instead of streaming chunks
		}
		
	var headers = ["content-type: application/json"]
	http_node.request(OLLAMA_URL,headers,HTTPClient.METHOD_POST , JSON.stringify(body))
		

func _on_TALOS_response(result: int, responce_code: int , header: PackedStringArray, body: PackedByteArray) -> void:
	if responce_code != 200:
		output_box.text = " error connecting to local Ollama server.Ensure it's runnning!
		Talos is depowered for the moment"
		return
	var json = JSON.new()
	var error = json.parse(body.get_string_from_utf8())
	if error == OK:
		var response_data = json.get_data()
		if response_data.has("response"):
			var ai_code = response_data["response"]
			output_box.text = ai_code
			#added to clipboard instantly for pating upon call
			DisplayServer.clipboard_set(ai_code)
