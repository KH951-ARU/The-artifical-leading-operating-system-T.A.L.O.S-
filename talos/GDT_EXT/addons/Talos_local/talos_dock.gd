@tool
extends Control

const OLLAMA_URL = "http://localhost:11434/api/generate"
# Use "qwen2.5-coder:3b".
const MODEL_NAME = "qwen2.5-coder:3b"

@onready var output_box: TextEdit = $VBoxContainer/TextEdit
@onready var input_line: LineEdit = $VBoxContainer/LineEdit
@onready var http_node: HTTPRequest = $TALOSRequest


func _ready() -> void:
	http_node.request_completed.connect(_on_TALOS_response)


func _on_send_button_pressed() -> void:
	var user_prompt = input_line.text.strip_edges()
	if user_prompt == "":
		return

	output_box.text = "Talos is forging . . ."
	input_line.clear()

	# System prompt to stay within Godot 4.4 documentation.
	var system_prompt = (
		"You are T.A.L.O.S, a local computational system. Generate clean, valid Godot 4.4 GDScript. "
		+ "Use modern features described in the Godot 4.4 documentation with comments."
		+ "Provide only raw function code without introductory small talk."
	)

	# Formulate the payload according to the API schema.
	var body = {
		"model": MODEL_NAME,
		"prompt": user_prompt,
		"system": system_prompt,
		"stream": false,
	}

	var headers = ["Content-Type: application/json"]
	http_node.request(OLLAMA_URL, headers, HTTPClient.METHOD_POST, JSON.stringify(body))


func _on_TALOS_response(
	_result: int,
	response_code: int,
	_headers: PackedStringArray,
	body: PackedByteArray,
) -> void:
	if response_code != 200:
		output_box.text = (
			"Error connecting to the local Ollama server. Ensure it is running. "
			+ "T.A.L.O.S is depowered for the moment."
		)
		return

	var json = JSON.new()
	var error = json.parse(body.get_string_from_utf8())
	if error == OK:
		var response_data = json.get_data()
		if response_data.has("response"):
			var ai_code = response_data["response"]
			output_box.text = ai_code
			# Added to the clipboard instantly for pasting upon call.
			DisplayServer.clipboard_set(ai_code)
