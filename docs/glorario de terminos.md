# Glosario de términos — AI Interviewer

Este glosario acompaña el guion y la presentación. Las definiciones distinguen los conceptos generales de su uso en el proyecto; las tecnologías marcadas como opcionales no necesariamente están activas en cada ejecución.

## 1. Actores y recorrido de la entrevista

**AI Interviewer:** Plataforma que organiza entrevistas técnicas: permite prepararlas, realizar preguntas y registrar evaluaciones para su posterior revisión humana. No toma por sí sola una decisión de contratación.

**Admin o administrador:** Persona que prepara y administra el proceso: gestiona roles, configuración, documentos e invitaciones a entrevistas.

**Candidate o candidato:** Persona que accede a una entrevista mediante un enlace y responde las preguntas presentadas en la interfaz.

**Reviewer o revisor:** Persona que analiza la entrevista y sus evidencias. Puede aprobar o sobrescribir la ruta propuesta por el sistema y debe justificar su decisión.

**Rol:** Puesto o perfil para el que se entrevista, por ejemplo, Scrum Master. Su descripción aporta contexto a la generación de preguntas y puede formar parte del corpus consultado durante la evaluación.

**Entrevista programada:** Registro administrativo asociado a un candidato, un rol y un período de disponibilidad. Tiene un enlace de acceso y un estado, como programada, activa, en progreso o completada.

**Enlace de entrevista y token:** El enlace permite acceder a una entrevista específica. Incluye un **token**, una cadena utilizada para identificar y autorizar ese acceso. Debe tratarse como privado.

**Corrida o run:** Una ejecución concreta de una entrevista. Tiene un identificador de corrida o **run ID** que permite consultar su estado y auditoría.

**Turno:** En el flujo evaluado, es una pregunta junto con la respuesta del candidato y la evaluación asociada. El warm-up se trata por separado y no cuenta como turno evaluado de competencia.

**Warm-up o calibración:** Pregunta inicial previa a las preguntas evaluadas. Su respuesta sirve como referencia para algunas métricas de integridad; no se suma al puntaje de las competencias.

**Competencia:** Área que se busca abordar en la entrevista. En la implementación revisada, el orden predeterminado incluye `debugging`, `api_design` y `test_reliability`.

**Cobertura de competencias:** Indicador de avance por la secuencia de competencias. Llegar a la última competencia no demuestra por sí solo que cada una se haya evaluado adecuadamente.

**Disclosure o aviso de integridad:** Información presentada al candidato sobre el tratamiento de señales de interacción. La interfaz solicita su aceptación antes de iniciar la entrevista.

**Acomodación:** Declaración que permite suprimir determinadas familias de señales de integridad, para tener en cuenta circunstancias que pueden afectar su interpretación.

**Seguimiento o follow-up:** Solicitud posterior a la revisión para realizar una acción adicional, por ejemplo, pedir una entrevista complementaria.

## 2. Interfaces y tecnologías web

**Frontend:** Parte de una aplicación con la que interactúa el usuario desde el navegador. En este proyecto existen interfaces para Admin, Candidate y Reviewer.

**Backend:** Parte del sistema que recibe solicitudes, aplica la lógica de negocio, coordina servicios y accede al almacenamiento. En este proyecto incluye la API en Python.

**Portal:** Interfaz web que reúne funciones para un tipo de usuario. El portal del proyecto contiene las vistas de administración y revisión.

**React:** Biblioteca de JavaScript que se usa para construir las interfaces y sus componentes.

**Componente:** Pieza reutilizable de una interfaz, como una sección, un formulario o una lista. En React, un componente puede recibir datos y mostrar contenido en función de ellos.

**JavaScript:** Lenguaje de programación utilizado habitualmente en el navegador para dar comportamiento a las interfaces.

**TypeScript:** Lenguaje basado en JavaScript que añade tipos y comprobaciones durante el desarrollo. Las interfaces del proyecto utilizan TypeScript.

**Vite:** Herramienta que levanta las interfaces durante el desarrollo y genera los archivos para publicarlas. Se usa junto con React: no lo reemplaza.

**Python:** Lenguaje de programación utilizado en el backend del proyecto, incluidos la API, el grafo y la lógica de evaluación.

**FastAPI:** Framework de Python para construir APIs HTTP. FastAPI expone las rutas del backend y recibe las solicitudes de los frontends. Cuando llega una respuesta, la API coordina su procesamiento y reanuda LangGraph. FastAPI no es el modelo de IA ni el grafo: es la interfaz que conecta las aplicaciones con esa lógica. En el caso del warm-up, la API inicia el grafo después de recibir la respuesta; en los turnos evaluados, lo reanuda.

**Pydantic:** Biblioteca de Python que permite definir modelos de datos y validar su contenido. En este proyecto, FastAPI utiliza modelos de Pydantic para definir y validar datos de entrada y salida de las rutas, por ejemplo, los que se envían y devuelven al iniciar una entrevista o responder una pregunta.

**Uvicorn:** Servidor que ejecuta la aplicación FastAPI y recibe las solicitudes HTTP. En desarrollo puede iniciarse con recarga automática.

**API:** Interfaz mediante la cual distintos programas intercambian datos. Las aplicaciones web del proyecto se comunican con el backend a través de su API.

**Endpoint o ruta:** Operación accesible a través de una URL de la API. Por ejemplo, `POST /run/answer` recibe una respuesta del candidato.

**HTTP y métodos GET / POST:** HTTP es el protocolo de comunicación entre navegador y servidor. `GET` suele solicitar información y `POST` enviar datos o pedir una operación, como iniciar una entrevista.

**JSON:** Formato de texto para representar datos estructurados mediante objetos, listas y valores. Se usa, por ejemplo, para intercambiar datos entre el frontend y la API.

**CSV:** Formato tabular de texto que separa campos por comas u otros delimitadores. Puede utilizarse para importar o exportar datos de entrevistas.

## 3. LangGraph y flujo del candidato

**LangGraph:** Biblioteca para organizar procesos con estado como grafos de nodos y conexiones. En el proyecto coordina el flujo de la entrevista, las pausas y la transición entre pasos. **No es el modelo de lenguaje ni redacta preguntas por sí mismo**.

**Grafo:** Estructura formada por nodos y conexiones que indica qué pasos se ejecutan y cómo se pasa de uno a otro. El grafo de entrevista incluye, entre otros, generación, evaluación y revisión.

**Nodo:** Función que cumple una tarea dentro del grafo. Recibe el estado y devuelve actualizaciones; por ejemplo, `retrieve` recupera contexto y `decide` aplica la política.

**Arista o conexión:** Relación que indica a qué nodo continúa el grafo. Una conexión condicional elige el siguiente paso según el estado o la ruta decidida.

**Estado o state:** Conjunto de datos que el grafo usa y actualiza durante la entrevista: rol, competencia actual, turno, dificultad, respuestas, puntajes y decisiones, entre otros.

**START, END y `entry_router`:** `START` y `END` representan el comienzo y el final del grafo. `entry_router` elige desde qué punto entrar o retomar según el estado; no es un nodo de negocio que evalúe al candidato.

**`generate_question`:** Nodo que llama al generador de preguntas configurado y guarda el resultado en el estado. Si se usa un modelo, el generador prepara el prompt y el modelo produce el texto. Si la generación con modelo no está habilitada, puede usarse un generador determinístico.

**`await_candidate`:** Nodo que interrumpe el grafo y espera una respuesta no vacía. La API reanuda el flujo cuando recibe la respuesta.

**Interrupción o interrupt:** Pausa explícita de la ejecución para esperar un dato externo, como la respuesta del candidato o la decisión del reviewer. El proceso se retoma con ese dato.

**`plan`:** Nodo que registra y propaga el estado de la competencia actual. En esta implementación no hace una planificación autónoma mediante un modelo.

**`retrieve`:** Nodo que busca hasta dos fragmentos del corpus usando la competencia y la respuesta, con filtros para el rol y el tipo de documento. Los fragmentos se pasan al evaluador.

**`evaluate`:** Nodo que ejecuta el evaluador configurado y registra el puntaje, las señales, la evidencia y referencias a los fragmentos. Puede usar un modelo de lenguaje o un evaluador determinístico.

**`decide`:** Nodo que actualiza la dificultad y llama a una política de reglas determinísticas. Esa política selecciona la ruta a partir de la evaluación y el estado; el modelo no elige directamente la ruta.

**`probe_deeper`:** Ruta que continúa la entrevista con otra pregunta para profundizar en la competencia actual.

**`switch_competency`:** Ruta que avanza a otra competencia de la secuencia cuando hay competencias posteriores disponibles.

**`conclude`:** Ruta que finaliza la etapa automática cuando se cumplen las condiciones de la política. Pasa a revisión humana y no equivale por sí sola a contratar al candidato.

**`escalate`:** Ruta que envía el caso a revisión humana, por ejemplo, por respuestas fuera de tema o por agotar el límite de turnos sin concluir. No equivale por sí sola a rechazar al candidato.

**`human_review`:** Nodo que interrumpe el grafo para recibir la decisión y justificación de un reviewer. La persona puede aprobar o sobrescribir la ruta propuesta.

**`report`:** Nodo que construye el resultado del grafo a partir de la ruta y la decisión humana. La salida puede contener una ruta sobrescrita por el reviewer.

**Checkpoint:** Copia persistida del estado del grafo en un punto de ejecución. Permite retomar una entrevista pausada, siempre que el almacenamiento esté correctamente configurado y disponible.

**Reanudación o resume:** Continuación de una ejecución interrumpida. En el flujo del candidato, la API entrega la respuesta al grafo para continuar desde la pausa.

**Máquina de estados:** Forma de modelar un proceso que conserva información sobre su situación y cambia de estado al ejecutar acciones. Un grafo con estado permite representar ese comportamiento.

## 4. Modelos, prompts y evaluación

**Inteligencia artificial o IA:** Conjunto de técnicas que permiten a sistemas realizar tareas como analizar o generar texto. En esta plataforma se utiliza como apoyo para formular preguntas y evaluar respuestas cuando están configurados modelos.

**Modelo de lenguaje o LLM:** Modelo entrenado para procesar y generar texto. En el proyecto puede recibir un prompt para producir una pregunta o una evaluación. Su salida debe interpretarse y validarse; no es una decisión humana.

**Prompt:** Texto de instrucciones y contexto enviado al modelo. El prompt de preguntas incluye datos como el rol, su descripción, la competencia, la dificultad y el turno.

**Generador de preguntas:** Componente que devuelve la siguiente pregunta. Según la configuración, puede llamar a un modelo con un prompt o seleccionar una pregunta predefinida mediante lógica determinística.

**Evaluador:** Componente que produce un puntaje y señales sobre una respuesta. Puede ser un adaptador de modelo de lenguaje o el evaluador determinístico local.

**Adaptador de modelo o proveedor:** Código que prepara la solicitud y procesa la respuesta de un servicio o modelo concreto. La generación de preguntas y la evaluación se configuran por separado.

**Ollama:** Herramienta para ejecutar modelos de lenguaje localmente. Es uno de los proveedores que el proyecto puede usar según la configuración.

**Llama 3.1:** Familia de modelos de lenguaje. En la configuración revisada puede usarse mediante Ollama; el modelo efectivo depende de las variables de entorno.

**Gemini y Anthropic:** Proveedores de modelos de lenguaje que el proyecto puede utilizar si se configuran sus adaptadores y credenciales.

**GitHub Models:** Servicio de acceso a modelos de lenguaje. Es una opción contemplada para la generación de preguntas, según la configuración.

**Determinístico:** Comportamiento definido por reglas de código, en vez de pedir una respuesta generada a un modelo. El proyecto dispone de generación de preguntas y evaluación determinísticas.

**Fallback o respaldo:** Alternativa utilizada cuando un componente principal falla. En la evaluación, ante errores del adaptador de modelo se puede recurrir al evaluador determinístico. Este también requiere evidencia recuperada, por lo que el respaldo no garantiza el éxito en todos los casos.

**Score o puntaje:** Valor numérico asignado a una respuesta por el evaluador. En la salida del modelo se valida que esté entre 0 y 1. Un puntaje alto no garantiza que la respuesta sea pertinente a la pregunta.

**`off_topic`:** Indicador de que el evaluador considera una respuesta fuera de tema. Su significado depende del evaluador utilizado. La política escala cuando el contador acumulado llega a dos.

**`mixed_signal` o señal mixta:** Indicador producido por el evaluador ante señales mixtas. Cuando quedan competencias posteriores, la política puede usarlo para cambiar de competencia; por sí solo no impide concluir si ya no quedan.

**Evidencia de evaluación:** Información que acompaña el puntaje. Al modelo se le piden citas textuales de la respuesta; el evaluador determinístico puede generar indicadores basados en palabras detectadas.

**Verificación de citas:** Comprobación de que la evidencia devuelta por el modelo aparece en la respuesta del candidato. Si falta o alguna cita no coincide, el adaptador registra una advertencia, pero conserva la evaluación.

**Pertinencia pregunta–respuesta:** Grado en que una respuesta aborda lo que se preguntó. En la implementación revisada, el prompt de evaluación no incluye el texto de la pregunta: esto limita la capacidad de garantizar esa pertinencia.

**Umbral:** Valor de referencia usado en una regla. Por ejemplo, el umbral de conclusión del código revisado es 0,55 para el score actual.

**Decision threshold — umbral de decisión (0,75):** Si el puntaje de la respuesta actual alcanza o supera 0,75 y quedan competencias posteriores, esta regla puede llevar al grafo a cambiar de competencia. No es el mínimo para aprobar ni para concluir la entrevista; otras reglas anteriores también pueden determinar la ruta.

**Low recommendation max — límite inferior para la dificultad (0,40):** Con los valores indicados, una respuesta con puntaje menor o igual a 0,40 baja un nivel la dificultad solicitada para la siguiente pregunta, sin bajar del nivel bajo. Una respuesta marcada como fuera de tema también baja la dificultad. Este valor puede configurarse por rol; pese a su nombre, no es una recomendación final de contratación.

**High recommendation min — límite superior para la dificultad (0,70):** Con los valores indicados, una respuesta que no está marcada como fuera de tema y tiene un puntaje mayor o igual a 0,70 sube un nivel la dificultad solicitada para la siguiente pregunta, sin superar el nivel alto. Entre 0,40 y 0,70, sin incluir esos extremos, la dificultad se mantiene si la respuesta no está fuera de tema. Este valor puede configurarse por rol; no es una recomendación final de contratación.

**Conclusion score threshold — umbral del puntaje para concluir (0,55):** La última respuesta evaluada debe alcanzar o superar 0,55 para que esta regla permita concluir la etapa automática. También deben cumplirse las demás condiciones: que no queden competencias posteriores en la secuencia y que el promedio alcance el umbral de confianza. Concluir lleva a revisión humana, no implica contratar.

**Confidence threshold — umbral de confianza (0,70):** Para que se cumpla la regla de conclusión, el promedio de los puntajes de todas las respuestas evaluadas, incluida la actual, debe alcanzar o superar 0,70. También se exige el puntaje mínimo de la última respuesta y que no queden competencias posteriores. Aunque se llama confianza, este promedio no es una probabilidad calibrada.

**Valores mostrados y valores usados:** En el flujo de LangGraph revisado, los umbrales de decisión, conclusión y confianza usan actualmente los valores predeterminados 0,75, 0,55 y 0,70, respectivamente, porque el nodo `decide` no transmite los valores del estado al contexto de decisión. Los límites de dificultad, en cambio, sí se leen del estado y pueden configurarse por rol. Las reglas se aplican en orden y estos umbrales no son decisiones finales de contratación.

**Política adaptativa:** Conjunto ordenado de reglas determinísticas que elige cómo sigue la entrevista. La primera condición que se cumple determina la ruta.

**Confianza o `confidence`:** En la política revisada, es el promedio de los puntajes de las respuestas evaluadas, incluida la actual. Aunque el código lo llama confianza, **no es una probabilidad calibrada**.

**Dificultad:** Nivel solicitado para la siguiente pregunta, representado como bajo, medio o alto. Se actualiza a partir del score y de si la respuesta está fuera de tema, según los umbrales presentes en el estado.

**Máximo de turnos:** Límite de preguntas evaluadas permitido por la configuración. Es un máximo, no una obligación de realizar esa cantidad: la política puede terminar la etapa automática antes.

**Configuración frente a ejecución:** Distinción entre valores guardados o mostrados y valores efectivamente usados por una función. En el nodo `decide` revisado, los umbrales de decisión, conclusión y confianza no se pasan al contexto y se utilizan los valores predeterminados.

## 5. RAG, documentos y búsqueda vectorial

**RAG:** Sigla de *Retrieval-Augmented Generation*, o generación aumentada por recuperación. Es un enfoque que recupera información externa y la incorpora como contexto para una tarea con un modelo. Aquí se usa contexto recuperado para la evaluación.

**Corpus:** Conjunto de documentos o contenidos disponibles para buscar información. Puede incluir descripciones de roles y otros documentos incorporados al sistema.

**Ingesta o ingestión:** Proceso de incorporar un documento al sistema de recuperación para que su contenido pueda buscarse. La reingesta vuelve a procesar un documento existente.

**Chunk o fragmento:** Parte más pequeña de un documento. Dividir documentos en fragmentos permite recuperar secciones relevantes sin enviar necesariamente el documento completo.

**Retrieval o recuperación:** Búsqueda de fragmentos relevantes para una consulta. En el grafo revisado, la consulta utiliza la competencia y la respuesta del candidato.

**Grounding o fundamentación:** Uso de información recuperada como contexto para una evaluación. La existencia de fuentes no garantiza por sí sola que la conclusión del modelo sea correcta.

**Fuente o referencia:** Identificador y datos de un fragmento recuperado, por ejemplo, su documento, su identificador de chunk y su puntaje de búsqueda. No es lo mismo que una cita textual de la respuesta del candidato.

**Relevancia de recuperación:** Puntaje que indica la cercanía o relevancia estimada de un fragmento para una búsqueda. Es distinto del score asignado a la respuesta del candidato.

**Embedding o vector de representación:** Lista de números que representa un texto para facilitar comparaciones de similitud. Textos relacionados pueden quedar próximos según el modelo y la métrica utilizados.

**Base de datos vectorial:** Sistema que almacena y busca vectores de representación, generalmente para encontrar elementos similares. En este proyecto la búsqueda vectorial con PostgreSQL y pgvector es opcional; también existe recuperación en memoria.

**pgvector:** Extensión de PostgreSQL que permite almacenar vectores y realizar búsquedas por similitud. El proyecto puede utilizarla para guardar embeddings de fragmentos.

**Similitud:** Medida de cercanía entre representaciones. La similitud vectorial ayuda a recuperar contexto, pero no demuestra que un documento sea verdadero ni que una respuesta sea correcta.

## 6. Persistencia e infraestructura

**Persistencia:** Almacenamiento de información para que sobreviva al fin de una solicitud o al reinicio de un proceso. Incluye, por ejemplo, corridas, eventos y checkpoints.

**Base de datos:** Sistema organizado para almacenar y consultar información. El proyecto admite SQLite y PostgreSQL para datos operativos.

**SQLite:** Motor de base de datos que guarda la información en archivos locales. Es la opción predeterminada en la configuración revisada.

**PostgreSQL o Postgres:** Sistema gestor de bases de datos relacional. Es una alternativa configurable para almacenar información operativa del proyecto y checkpoints de LangGraph.

**Tabla, fila y columna:** Una tabla organiza registros; cada fila representa un registro y cada columna un dato, como un identificador o un estado.

**Clave primaria o PK:** Campo que identifica de manera única un registro dentro de una tabla.

**Clave foránea o FK:** Campo cuya relación con otra tabla está declarada en la base de datos. Una relación lógica entre datos no necesariamente está implementada como FK.

**Esquema de base de datos:** Espacio de nombres que agrupa objetos como tablas dentro de una base. Cuando LangGraph y la API usan la misma base PostgreSQL, pueden necesitar esquemas separados porque ambos poseen tablas llamadas `checkpoints`.

**DSN:** Cadena de conexión que indica cómo acceder a una base de datos, incluido el servidor y la base. Puede contener credenciales, por lo que no debe compartirse públicamente.

**Variable de entorno:** Valor de configuración disponible para un proceso, por ejemplo, qué backend de base de datos usar o dónde conectarse.

**`.env`:** Archivo que puede contener variables de configuración. No todas las aplicaciones lo cargan automáticamente; hay que iniciar el proceso de una forma que lo lea. No debe exponerse si contiene credenciales.

**DuckDB:** Motor de base de datos orientado a consultas analíticas. En el proyecto puede utilizarse de forma opcional para materializar datos analíticos.

**Lakehouse:** Enfoque de arquitectura de datos que combina almacenamiento de datos con capacidades de análisis. El proyecto contempla un flujo analítico opcional con DuckDB y archivos de datos.

**Bronze, Silver y Gold:** Capas utilizadas para organizar datos analíticos: Bronze conserva datos de origen, Silver presenta datos preparados y Gold agrupa métricas o resultados para análisis.

**Parquet:** Formato de archivo columnar utilizado habitualmente para almacenamiento y análisis de datos. El flujo opcional del proyecto puede generar archivos Parquet.

**MinIO:** Servicio de almacenamiento de objetos compatible con interfaces de tipo S3. En el proyecto aparece como integración opcional para guardar artefactos.

**Airflow:** Herramienta para programar y coordinar tareas mediante flujos. El proyecto contempla su uso opcional para procesos como ingestión y análisis.

**Resend:** Servicio de envío de correos electrónicos que puede configurarse para invitaciones. Es una integración opcional; su disponibilidad depende de la configuración.

## 7. Auditoría, integridad y observabilidad

**Auditoría:** Registro y revisión de información sobre lo ocurrido: preguntas, respuestas, eventos, evaluaciones y decisiones. Permite reconstruir una corrida.

**Evento de auditoría:** Registro de algo ocurrido durante el proceso, con tipo, datos y fecha. Ejemplos: inicio de una corrida o finalización de un turno.

**Event stream o flujo de eventos:** Listado de eventos asociados a una corrida. En el Reviewer ayuda a inspeccionar el recorrido de la entrevista.

**Raw payload:** Datos originales o estructurados recibidos y mostrados para inspección técnica. En el Reviewer permite examinar el contenido completo del paquete de auditoría.

**Log:** Registro textual de actividad, advertencias o errores de una aplicación. Un log ayuda a diagnosticar, pero no es necesariamente equivalente a una traza completa.

**Traza o trace:** Registro de una ejecución y sus pasos. Ayuda a identificar qué se ejecutó y con qué resultado; puede contener información sensible de la entrevista.

**LangSmith:** Plataforma de observabilidad para ejecuciones de aplicaciones con modelos y grafos. Puede recibir trazas cuando está correctamente configurada.

**Span:** Unidad individual dentro de una traza, que representa una operación. Los adaptadores propios del proyecto no garantizan que cada llamada al modelo aparezca automáticamente como un span específico de LLM.

**Telemetría:** Señales registradas durante el uso de una aplicación, como determinados tiempos o interacciones. Deben interpretarse en contexto y no equivalen por sí solas a una prueba de conducta.

**Focus o foco:** Señal relacionada con el foco del campo de respuesta. En la interfaz revisada su telemetría es opcional y está desactivada por defecto.

**Timing e input:** Familias de señales relacionadas con tiempos e interacciones de entrada, como escritura o pegado. No deben interpretarse automáticamente como evidencia de fraude.

**AAI:** Índice de integridad que resume señales disponibles y puede ayudar a priorizar la revisión. No es una probabilidad de fraude ni modifica el puntaje de competencia.

**Factor de confusión:** Circunstancia que puede ofrecer otra explicación para una señal observada, como una acomodación o diferencias en la forma de interacción.

**Aprobación y override:** En la revisión, aprobar acepta la ruta propuesta; un **override** o sobrescritura cambia la ruta. Ambas acciones requieren una justificación en el flujo revisado.

**Analytics:** Análisis agregado de datos para observar métricas y tendencias. Es diferente de la evaluación individual de una respuesta.

**Snapshot:** Captura de datos o métricas en un momento determinado, utilizada para análisis y comparaciones.

**Drift:** Cambio observado en métricas o comportamientos entre períodos o snapshots. Una alerta de drift requiere interpretación; no identifica automáticamente la causa.

**Trazabilidad:** Capacidad de seguir el recorrido de una ejecución y relacionar sus decisiones con los datos y eventos registrados.
