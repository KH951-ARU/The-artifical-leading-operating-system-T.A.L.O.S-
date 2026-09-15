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
		
