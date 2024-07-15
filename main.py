from flask import Flask, jsonify, request, abort
from dotenv import load_dotenv
import os
from openai import AzureOpenAI
import requests
import json
import time

app = Flask(__name__)

# Cargar las variables de entorno desde el archivo .env
load_dotenv()

# Obtener la clave API de las variables de entorno
API_KEY = os.getenv('API_KEY')
API_KEY_AZURE_ASSISTANT = os.getenv('API_KEY_AZURE_ASSISTANT')
API_KEY_SERVICE_SEARCH = os.getenv('API_KEY_SERVICE_SEARCH')
URL_POTENCIATEC = os.getenv('URL_POTENCIATEC')
AZURE_ENDPOINT_ASSISTANT = os.getenv('AZURE_ENDPOINT_ASSISTANT')
API_VERSION_ASSISTANT = os.getenv('API_VERSION_ASSISTANT')
ID_ASSISTANT = os.getenv('ID_ASSISTANT')
ID_BASIC_ASSISTANT = os.getenv('ID_BASIC_ASSISTANT')

def check_api_key():
    api_key = request.headers.get('X-Api-Key')
    if api_key != API_KEY:
        abort(403, description="Forbidden: Invalid or missing API key")

def perform_search(model, year, search):
    url = URL_POTENCIATEC
    headers = {
        "Api-key": API_KEY_SERVICE_SEARCH,
        "Content-Type": "application/json"
    }
    payload = {
        "search": f"{search} {model} {year}",
        "queryType": "semantic",
        "semanticConfiguration": "my-semantic-config",
        "captions": "extractive",
        "top": 2,
        "answers": "extractive|count-3",
        "queryLanguage": "en-US"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()["value"]

        # Extraer los datos deseados
        results = []
        for item in data[:2]:
            result = {
                "url_manual": item.get("url", ""),
                "title": item.get("title", ""),
                "content": (item.get("content", "")[:150] + '...') if len(item.get("content", "")) > 150 else item.get("content", "")
            }
            results.append(result)

        # Crear una respuesta más humana
        response_message = "He encontrado los siguientes documentos:\n"
        for result in results:
            response_message += f"\nTítulo: {result['title']}\nURL: {result['url_manual']}\nDescripción: {result['content']}\n"

        # Guardar los datos en un archivo JSON
        with open("output.json", "w", encoding="utf-8") as file:
            json.dump(results, file, ensure_ascii=False, indent=4)

        print("Datos guardados en output.json")
        print("response : " + response_message)
        return response_message

    except requests.exceptions.RequestException as e:
        return f"Error al realizar la búsqueda: {e}"

tools = [
    {
        "type": "function",
        "function": {
            "name": "perform_search",
            "description": "Obtain manuals or advisory guides in the mechanical field of any vehicle or automotive component. The response will be an array structure with json, interpret it and give a response that includes the url_manual properties: which will be the path to download the manual and if possible use the title and content property to give more details, that with one of the 2 responses received.",
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {
                        "type": "string",
                        "description": "La marca y el modelo, Renault, clio",
                    },
                    "year": {"type": "string", "description": "Fecha del modelo"},
                    "search": {
                        "type": "string",
                        "description": "Elemento requerido, manual, esquema electrico",
                    },
                },
                "required": ["model", "year", "search"],
            },
        },
    }
]

print(2)
available_function = {"perform_search": perform_search}
print(3)
client = AzureOpenAI(
    api_key=API_KEY_AZURE_ASSISTANT,
    azure_endpoint=AZURE_ENDPOINT_ASSISTANT,
    api_version=API_VERSION_ASSISTANT,
)
print(4)

def poll_run_till_completion(
    client: AzureOpenAI,
    thread_id: str,
    run_id: str,
    available_functions: dict,
    verbose: bool,
    max_steps: int = 20,  # Incrementado para más intentos de polling
    wait: int = 3,
) -> None:
    if (client is None and thread_id is None) or run_id is None:
        print("Client, Thread ID and Run ID are required.")
        return
    try:
        cnt = 0
        print(11)
        print(cnt)
        while cnt < max_steps:
            run = client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run_id)
            
            if verbose:
                print("Poll {}: {}".format(cnt, run.status))
            cnt += 1
            if run.status == "requires_action":
                tool_responses = []
                if (
                    run.required_action.type == "submit_tool_outputs"
                    and run.required_action.submit_tool_outputs.tool_calls is not None
                ):
                    tool_calls = run.required_action.submit_tool_outputs.tool_calls

                    for call in tool_calls:
                        if call.type == "function":
                            if call.function.name not in available_functions:
                                raise Exception("Function requested by the model does not exist")
                            function_to_call = available_functions[call.function.name]
                            tool_response = function_to_call(**json.loads(call.function.arguments))
                            tool_responses.append({"tool_call_id": call.id, "output": tool_response})

                    # Enviar las respuestas de las herramientas
                    run = client.beta.threads.runs.submit_tool_outputs(
                        thread_id=thread_id, run_id=run.id, tool_outputs=tool_responses
                    )
            if run.status == "failed":
                print("Run failed.")
                break
            if run.status == "completed":
                break
            time.sleep(wait)

    except Exception as e:
        print(e)
print(6)

@app.route('/check-api-key')
def check_api_key():
    headers = {key: value for key, value in request.headers}
     
    return jsonify({'API_KEY': API_KEY,'api_user':request.headers.get('X-Api-Key'),'headers': headers})


@app.route('/')
def root():
    check_api_key()
    return jsonify({'saludo': 'hola'})

@app.route('/asistant')
def get_chat():
    check_api_key()  # Verificar la clave API
    message = request.args.get('msj')
    thread_req = request.args.get('thread_id')
    if not message:
        return jsonify({'error': 'Falta el parámetro msj'}), 400
    
    # Create a thread
    if not thread_req:
        print('si')
        thread = client.beta.threads.create()
        thread_id = thread.id  # Obteniendo el id del nuevo thread
    else:
        print('no')
        thread_id = thread_req 
    print(7)
    # Add a user question to the thread
    message = client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=message,
    )
    print(8)
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=ID_ASSISTANT,
        instructions=f"""
        Eres un asistente de mecánica que puede buscar y proporcionar manuales y guías técnicas de vehículos.

        Usando la herramienta de búsqueda "perform_search" proporcionada, realiza la búsqueda una vez se tengan los datos requeridos y proporciona una respuesta detallada que incluya:

        1. La URL del manual o guía técnica correspondiente, si se encuentra disponible.
        2. Un resumen del contenido del manual o guía, destacando información relevante sobre el esquema del motor.
        3. Envía las 2 URL de manual.

        Responde de manera concisa y útil para el usuario.
        Si el usuario no te envía los datos de modelo, año y detalles de lo buscado, debes responder que necesita datos adicionales como (y agregar los datos que falten para ejecutar la búsqueda).
        """
    )
    print(9)
    # Run the thread and poll for the result
    poll_run_till_completion(client=client, thread_id=thread_id, run_id=run.id, available_functions=available_function, verbose=True)
    print(10)
    # Process the messages
    messages = client.beta.threads.messages.list(thread_id=thread_id)

    messages_list = list(messages)

    if messages_list:
        # Obtener el primer mensaje
        primer_mensaje = messages_list[0]

        # Acceder al contenido del primer mensaje
        if primer_mensaje.content:
            content_block = primer_mensaje.content[0]
            if hasattr(content_block, 'text') and hasattr(content_block.text, 'value'):
                texto_respuesta = content_block.text.value
                return jsonify({'text': texto_respuesta, 'thread': thread_id})
    print(messages.to_json())

@app.route('/basic_asistant')
def get_basic_chat():
    check_api_key()

    message = request.args.get('msj')
    thread_req = request.args.get('thread_id')

    if not message:
        return jsonify({'error': 'Falta el parámetro msj'}), 400

    # Crear o recuperar el thread de la conversación
    if not thread_req:
        thread = client.beta.threads.create()
        thread_id = thread.id
    else:
        thread_id = thread_req

    # Añadir la pregunta del usuario al thread
    user_message = client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=message,
    )

    # Lista ampliada de palabras clave en español e inglés
    keywords_mecanica = [
        'motor', 'coche', 'automóvil', 'mecánico', 'reparación', 'transmisión', 'manual', 'guía',
        'vehículo', 'carro', 'mantenimiento', 'servicio', 'frenos', 'aceite', 'neumáticos', 'suspensión',
        'chasis', 'clutch', 'embrague', 'escape', 'filtro', 'radiador', 'bujía', 'inyección', 'diagnóstico',
        'engine', 'car', 'automobile', 'mechanic', 'repair', 'transmission', 'manual', 'guide',
        'vehicle', 'maintenance', 'service', 'brakes', 'oil', 'tires', 'suspension',
        'chassis', 'clutch', 'exhaust', 'filter', 'radiator', 'spark plug', 'injection', 'diagnosis'
    ]

    # Verificar si el mensaje del usuario está relacionado con mecánica antes de procesarlo
    if any(keyword in message.lower() for keyword in keywords_mecanica):
        # Crear y ejecutar el thread solo si el mensaje está relacionado con mecánica
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ID_BASIC_ASSISTANT,
            instructions="""
            Eres un asistente de mecánica dedicado a responder consultas sobre manuales y guías de reparación de vehículos.
            """
        )

        # Ejecutar la función de polling y esperar la respuesta
        poll_run_till_completion(client, thread_id, run.id, available_function, verbose=True)

        # Procesar y obtener las respuestas
        messages = client.beta.threads.messages.list(thread_id=thread_id)
        messages_list = list(messages)

        if messages_list:
            # Obtener el contenido del primer mensaje con respuesta
            primer_mensaje = messages_list[0]
            if primer_mensaje.content:
                content_block = primer_mensaje.content[0]
                if hasattr(content_block, 'text') and hasattr(content_block.text, 'value'):
                    texto_respuesta = content_block.text.value
                    return jsonify({'text': texto_respuesta, 'thread': thread_id})
    else:
        # Indicar al usuario que solo se pueden responder preguntas de mecánica
        return jsonify({'text': 'Solo puedo responder preguntas relacionadas con la mecánica de vehículos. Por favor, realiza una consulta sobre este tema.','thread': thread_id}), 200

    # En caso de no haber mensajes válidos, devolver información adicional
    return jsonify({'error': 'No se pudo procesar la respuesta correctamente', 'thread': thread_id}), 500


if __name__ == "__main__":
    app.run(debug=True)
