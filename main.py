from flask import Flask, jsonify, request, abort, render_template_string ,Response
from dotenv import load_dotenv
import os
from openai import AzureOpenAI
import requests
import json
import time
from urllib.parse import quote

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
        "top": 6,
        "answers": "extractive|count-3",
        "queryLanguage": "en-US"
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()["value"]

        # Extraer los datos deseados
        results = []
        for item in data[:6]:
            result = {
                "url_manual": item.get("url", ""),
                "title": item.get("title", ""),
                "content": (item.get("content", "")[:150] + '...') if len(item.get("content", "")) > 150 else item.get("content", ""),
                "page": item.get("page", ""),
            }
            results.append(result)

        # Crear una respuesta más humana
        response_message = "He encontrado los siguientes documentos:\n"
        for result in results:
            response_message += f"\nTítulo: {result['title']}\nURL: {result['url_manual']}\nDescripción: {result['content']}\nPagina: {result['page']}\n"

        # Guardar los datos en un archivo JSON
        with open("output.json", "w", encoding="utf-8") as file:
            json.dump(results, file, ensure_ascii=False, indent=4)

        #print("Datos guardados en output.json")
        #print("response : " + response_message)
        return response_message

    except requests.exceptions.RequestException as e:
        return f"Error al realizar la búsqueda: {e}"

tools = [
    {
        "type": "function",
        "function": {
            "name": "perform_search",
            "description": "Obtain manuals or advisory guides in the mechanical field of any vehicle or automotive component. The response will be an array structure with json, interpret it and give a response that includes the url_manual properties: what will be the path to download the manual and if possible use the title and content property to give more details, also add the page property which is the number of the page where the searched content is, that with one of the 2 responses received.",
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


available_function = {"perform_search": perform_search}

client = AzureOpenAI(
    api_key=API_KEY_AZURE_ASSISTANT,
    azure_endpoint=AZURE_ENDPOINT_ASSISTANT,
    api_version=API_VERSION_ASSISTANT,
)


def poll_run_till_completion(
    client: AzureOpenAI,
    thread_id: str,
    run_id: str,
    available_functions: dict,
    verbose: bool,
    max_steps: int = 30,  # Incrementado para más intentos de polling
    wait: int = 3,
) -> None:
    if (client is None and thread_id is None) or run_id is None:
        print("Client, Thread ID and Run ID are required.")
        return
    try:
        cnt = 0
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
        thread = client.beta.threads.create()
        thread_id = thread.id  # Obteniendo el id del nuevo thread
    else:
        thread_id = thread_req 
    # Add a user question to the thread
    message = client.beta.threads.messages.create(
        thread_id=thread_id,
        role="user",
        content=message,
    )
    run = client.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=ID_ASSISTANT,
        # instructions=f"""
        # Eres un asistente de mecánica que puede buscar y proporcionar manuales y guías técnicas de vehículos.

        # Usando la herramienta de búsqueda "perform_search" proporcionada, realiza la búsqueda una vez se tengan los datos requeridos y proporciona una respuesta detallada que incluya:

        # 1. La URL del manual o guía técnica correspondiente, si se encuentra disponible.
        # 2. Un resumen del contenido del manual o guía, destacando información relevante sobre el esquema del motor.
        # 3. Envía las 2 URL de manual.

        # Responde de manera concisa y útil para el usuario.
        # Si el usuario no te envía los datos de modelo, año y detalles de lo buscado, debes responder que necesita datos adicionales como (y agregar los datos que falten para ejecutar la búsqueda).
        # """
    )
    
    # Run the thread and poll for the result
    poll_run_till_completion(client=client, thread_id=thread_id, run_id=run.id, available_functions=available_function, verbose=True)
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
    # comentado el validador de respuesta.
    #if any(keyword in message.lower() for keyword in keywords_mecanica):
    if True: 
        # Crear y ejecutar el thread solo si el mensaje está relacionado con mecánica
        run = client.beta.threads.runs.create(
            thread_id=thread_id,
            assistant_id=ID_BASIC_ASSISTANT,
            # instructions="""
            # Eres un asistente de mecánica dedicado a responder consultas sobre manuales y guías de reparación de vehículos.
            # """
            # instructions="""
            # Eres un asistente de cocina, puedes dar recetas.
            # """
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


@app.route('/viewPdf')
def view_pdf():
    original_url = request.args.get('url')
    page = request.args.get('page', default=1, type=int)
    if not original_url:
        return "URL del PDF no proporcionada", 400

    # Convertir barras invertidas a barras normales y asegurar la codificación correcta
    corrected_url = original_url.replace('%5C', '/')
    safe_url = quote(corrected_url, safe=':/')

    # Plantilla HTML que incorpora PDF.js para visualizar el PDF con navegación
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Visualizador de PDF</title>
        <link rel="stylesheet" href="https://unpkg.com/pdfjs-dist@3.11.174/web/pdf_viewer.css">
        <script src="https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.js"></script>
        <script src="https://unpkg.com/pdfjs-dist@3.11.174/web/pdf_viewer.js"></script>
        <style>
            #viewerContainer {{
                width: 100%;
                height: 90vh;
                overflow: auto;
                position: absolute;
                top: 50px;  /* Ajuste de espacio para la barra de herramientas */
                left: 0;
            }}
            #pdf-viewer {{
                width: 100%;
                height: 100%;
            }}
            #toolbar {{
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 50px;
                background-color: #333;
                color: white;
                display: flex;
                align-items: center;
                justify-content: space-around;
                z-index: 1000;
            }}
            #toolbar button, #toolbar input {{
                background-color: #444;
                border: none;
                color: white;
                padding: 10px;
                cursor: pointer;
                margin: 0 5px;
            }}
            #toolbar button:hover, #toolbar input:hover {{
                background-color: #555;
            }}
            #toolbar input {{
                width: 50px;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <h1>Visualizador de PDF</h1>
        <div id="toolbar">
            <button id="prev">Anterior</button>
            <span>Página: <input type="number" id="page_num_input" min="1" value="{page}" style="width: 50px;"> / <span id="page_count">1</span></span>
            <button id="next">Siguiente</button>
            <button id="download">Descargar</button>
        </div>
        <div id="viewerContainer">
            <div id="pdf-viewer" class="pdfViewer"></div>
        </div>

        <script>
            document.addEventListener('DOMContentLoaded', function () {{
                console.log('DOM fully loaded and parsed');
                const pdfjsLib = window['pdfjs-dist/build/pdf'];
                const pdfjsViewer = window['pdfjs-dist/web/pdf_viewer'];

                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.js';

                var container = document.getElementById('viewerContainer');
                var eventBus = new pdfjsViewer.EventBus();

                var pdfLinkService = new pdfjsViewer.PDFLinkService({{
                    eventBus: eventBus
                }});

                var pdfViewer = new pdfjsViewer.PDFViewer({{
                    container: container,
                    eventBus: eventBus,
                    linkService: pdfLinkService
                }});

                pdfLinkService.setViewer(pdfViewer);

                var loadingTask = pdfjsLib.getDocument("{safe_url}");
                loadingTask.promise.then(function (pdf) {{
                    console.log('PDF loaded successfully');
                    pdfViewer.setDocument(pdf);
                    pdfLinkService.setDocument(pdf, null);

                    document.getElementById('page_count').textContent = pdf.numPages;

                    // Wait until all pages are loaded before setting the initial page
                    pdfViewer.eventBus.on('pagesinit', function () {{
                        pdfViewer.currentPageNumber = {page};
                    }});

                    document.getElementById('prev').addEventListener('click', function() {{
                        if (pdfViewer.currentPageNumber > 1) {{
                            pdfViewer.currentPageNumber--;
                            document.getElementById('page_num_input').value = pdfViewer.currentPageNumber;
                        }}
                    }});

                    document.getElementById('next').addEventListener('click', function() {{
                        if (pdfViewer.currentPageNumber < pdf.numPages) {{
                            pdfViewer.currentPageNumber++;
                            document.getElementById('page_num_input').value = pdfViewer.currentPageNumber;
                        }}
                    }});

                    document.getElementById('page_num_input').addEventListener('change', function() {{
                        var pageNumber = parseInt(this.value);
                        if (pageNumber >= 1 && pageNumber <= pdf.numPages) {{
                            pdfViewer.currentPageNumber = pageNumber;
                        }}
                    }});

                    document.getElementById('download').addEventListener('click', function() {{
                        var a = document.createElement('a');
                        a.href = "{safe_url}";
                        a.download = "document.pdf";
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    }});

                    pdfViewer.eventBus.on('pagechanging', function (evt) {{
                        document.getElementById('page_num_input').value = evt.pageNumber;
                    }});
                }}, function (reason) {{
                    console.error('Error loading PDF: ', reason);
                }});
            }});
        </script>
    </body>
    </html>
    """

    return render_template_string(html_template)

if __name__ == "__main__":
    app.run(debug=True)
