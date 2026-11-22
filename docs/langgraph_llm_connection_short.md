# LangGraph + LLM: explicación corta para presentar o explicar la arquitectura

## 1. En una frase

Este proyecto combina un frontend, un backend en FastAPI, un agente con LangGraph y un modelo de IA para hacer entrevistas adaptativas por rol.

---

## 2. Qué hace cada pieza

### Frontend
Muestra la pantalla del candidato y del admin. El candidato entra por una URL con `role_id` y luego responde preguntas.

### Backend FastAPI
Expone los endpoints:

- /run/start
- /run/answer
- /admin/roles/{role_id}

Se encarga de crear el estado de la entrevista y devolver la siguiente pregunta.

### LangGraph
Es el orquestador principal. Mantiene el estado del interview:

- rol
- tipo de documento
- descripción del puesto
- competencia actual
- turno actual
- dificultad
- historial de decisiones

### Agent
Es la lógica inteligente del entrevistador. No es solo el LLM: es el sistema que decide qué pregunta hacer, cómo evaluar la respuesta y si la entrevista sigue o termina.

### LLM / Model
Es el motor que genera y evalúa texto. Puede ser:

- Gemini
- Ollama
- Anthropic
- GitHub Models

### Generator
Es el adaptador que conecta el estado del grafo con el prompt del modelo. Hace esto:

- toma el estado del graph
- arma el prompt con el rol y la descripción del trabajo
- envía ese prompt al modelo
- recibe la respuesta
- limpia la respuesta
- la devuelve como la siguiente pregunta

---

## 3. Cómo se conectan

```text
Frontend
  -> FastAPI
    -> InterviewGraph (LangGraph)
      -> QuestionGenerator
        -> LLM provider (Gemini / Ollama / Anthropic / GitHub)
      -> respuesta del modelo
      -> nueva pregunta
      -> evaluación de respuesta
      -> siguiente paso del interview
```

---

## 4. Flujo real

### Paso 1: cargar el rol
El admin guarda el rol y su descripción en la base de datos.

### Paso 2: entrar con el link
La URL del candidato trae `role_id`.

### Paso 3: cargar la descripción del puesto
El frontend consulta la API y obtiene:

- title
- location
- description

### Paso 4: iniciar interview
Se envía al backend:

```json
{
  "role": "sr_software_engineer",
  "doc_type": "role_description",
  "role_description": "...texto completo del puesto..."
}
```

### Paso 5: LangGraph crea el estado
El graph guarda ese contexto en memoria.

### Paso 6: generator arma el prompt
El prompt incluye:

- rol actual
- descripción del puesto
- competencia
- turn_index
- dificultad
- max_turns

### Paso 7: LLM genera la primera pregunta
El modelo responde con una pregunta contextualizada al puesto.

### Paso 8: el usuario responde
Se envía al endpoint /run/answer.

### Paso 9: LangGraph evalúa la respuesta
Se calcula:

- relevancia
- profundidad
- especificidad
- off-topic

### Paso 10: se arma la siguiente pregunta
Con base en la evaluación, el graph decide si:

- profundiza
- cambia de competencia
- concluye
- escalates a review

y vuelve a pedir otra pregunta al LLM.

### Paso 11: adaptación de dificultad y respuestas incorrectas

La entrevista comienza en dificultad `medium`:

- score `>= 0.75`: sube la dificultad, hasta `high`;
- score `<= 0.40`: baja la dificultad, hasta `low`;
- score intermedio: mantiene la dificultad;
- respuesta `off_topic`: baja la dificultad.

El máximo configurado es `max_turns=5`, es decir, hasta cinco
preguntas/respuestas evaluadas. La entrevista puede terminar antes si se
cubren las competencias con suficiente confianza.

La ruta se decide según la evaluación:

- `probe_deeper`: la respuesta permite profundizar;
- `switch_competency`: cambia a otra competencia;
- `conclude`: finaliza con cobertura y confianza suficientes;
- `escalate`: deriva a revisión.

Dos respuestas fuera de tema llevan a `escalate`. Una respuesta débil reduce
la dificultad y normalmente mantiene la entrevista con `probe_deeper`; si se
llega al último turno sin calidad suficiente, también se escala.

El score puede venir del adapter LLM o del evaluador determinístico local. El
motor `legacy` y los casos en que el LLM está deshabilitado usan la evaluación
local; el adapter LLM se usa cuando el motor `langgraph` está habilitado y el
proveedor está disponible.

---

## 5. Qué significa la conexión real

LangGraph no reemplaza al LLM. Lo usa como una pieza dentro del flujo.

La relación es:

- LangGraph = controlador del estado y la lógica del interview
- Generator = adaptador entre graph y modelo
- LLM = motor de texto que devuelve la pregunta

En otras palabras:

LangGraph decide el flujo y el LLM ayuda a hacer preguntas y evaluar respuestas.

---

## 6. Por qué se ve la pregunta genérica

La pregunta genérica aparece cuando la app no alcanza al proveedor real del LLM y cae al fallback.

Esto puede pasar si:

- la variable del provider está deshabilitada
- faltan env vars
- hubo error en la llamada
- la cuota se agotó
- el modelo no existe o está vencido

En ese caso, el sistema usa una pregunta fija como backup y no una pregunta contextualizada por rol.

---

## 7. Resumen muy corto

Este proyecto hace esto:

- el candidato llega por un role
- el backend guarda la descripción del puesto
- LangGraph mantiene el estado de la interview
- el generator arma un prompt con contexto del rol
- el LLM responde con una pregunta
- la respuesta del candidato se evalúa y decide la siguiente pregunta

Es decir, LangGraph orquesta el flujo y el modelo aporta el razonamiento y la generación de texto.
