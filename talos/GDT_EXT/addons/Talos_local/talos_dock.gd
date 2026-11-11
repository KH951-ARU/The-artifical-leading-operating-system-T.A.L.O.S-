@tool
extends Control

@onready var output_box: TextEdit = $VBoxContainer/TextEdit
@onready var input_line: LineEdit = $VBoxContainer/LineEdit
@onready var http_node: HTTPRequest = $TALOSRequest

const OLLAMA_URL = "http://localhost:11434/api/generate"
#Use 'qween2.5-coder:3.1b' 
const MODEL_NAME = "qwen2.5-coder:3b"

func _ready() -> void:
	http_node.request_completed.connect(_on_TALOS_response)

func _on_send_button_pressed() -> void:
	var user_prompt = input_line.text.strip_edges()
	if user_prompt == "": return
	
	output_box.text = "Talos is forging . . ."
	input_line.clear()
	
	#system prompt to stay with in Godot 4.4 documentation
	var  system_prompt = ("You are T.A.L.O.S , a local computational system. Generate clean , vaild godot 4.4 GDscript. " +
	"Use modern features described in the godot 4.4 documentation with commnets" +
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
	
