# Guion oral: AI Interviewer

A continuación te dejo un **guion oral**, siguiendo el orden de [la presentación](./Presentacion%20AI%20Interviewer.pptx). Está pensado para explicarlo con tus palabras, dedicando más tiempo a las diapositivas de **LangGraph y el recorrido del candidato**.

---

## Diapositiva 1 — Presentación

> Buenos días. Voy a presentar **AI Interviewer**, una plataforma que busca facilitar y organizar el proceso de entrevistas técnicas.
>
> La idea principal es acompañar todo el recorrido: desde la preparación de una entrevista y el acceso del candidato hasta la evaluación y la revisión humana.
>
> Es importante destacar desde el principio que la plataforma **no reemplaza al entrevistador ni toma por sí sola una decisión de contratación**. Automatiza partes del proceso y genera información para que una persona pueda revisarla.

## Diapositiva 2 — ¿Qué hace el sistema?

> El sistema se divide en tres grandes etapas.
>
> Primero, el administrador prepara la entrevista: define el rol, incorpora información y programa al candidato.
>
> Después, el candidato accede a través de un enlace y responde una entrevista adaptativa. El grafo coordina el generador de preguntas y el evaluador configurados, y aplica reglas para decidir cómo continuar.
>
> Finalmente, el reviewer revisa lo ocurrido: puede consultar las respuestas, las evaluaciones, las fuentes utilizadas y las decisiones que fue tomando el sistema.
>
> El objetivo no es solamente obtener un resultado, sino también poder entender **cómo se llegó a él**.

## Diapositiva 3 — Arquitectura y tecnologías

> En cuanto a la arquitectura, tenemos una separación entre las interfaces, el backend, el motor de entrevistas y la persistencia.
>
> Las interfaces están hechas con React, TypeScript y Vite. Hay una aplicación para el candidato y un portal con las vistas de administrador y reviewer.
>
> El backend está desarrollado en Python con FastAPI. Para coordinar la entrevista usamos LangGraph, que representa el proceso como un grafo de nodos con estado.
>
> FastAPI expone los endpoints, o rutas, que reciben las solicitudes de las interfaces. LangGraph coordina el flujo de la entrevista; FastAPI no es ni el grafo ni el modelo de inteligencia artificial.
>
> Para fundamentar las evaluaciones se utiliza recuperación de información del corpus, es decir, un enfoque RAG. La persistencia puede funcionar con SQLite o PostgreSQL, y LangSmith permite observar las ejecuciones cuando está configurado.
>
> La generación de preguntas y la evaluación pueden configurarse por separado, por lo que no necesariamente tienen que utilizar el mismo proveedor o modelo.

## Diapositiva 4 — Del rol al resultado

> En este esquema vemos el recorrido completo.
>
> El administrador comienza creando un rol, preparando documentación y programando una entrevista. El candidato accede al enlace, acepta el aviso de integridad y responde una pregunta inicial de *warm-up*.
>
> A partir de ahí interviene LangGraph: coordina la generación de preguntas, pausa el flujo para recibir cada respuesta, llama al evaluador y aplica reglas para decidir si tiene que profundizar, cambiar de competencia o cerrar la etapa automática.
>
> Cuando esa etapa termina, el flujo pasa al reviewer, que analiza lo sucedido y registra una decisión.
>
> El warm-up cumple una función de calibración: **no se suma al puntaje de las competencias**.

## Diapositiva 5 — Portal Admin

> Desde el portal de administración se prepara y se opera el proceso.
>
> Por un lado, se gestionan los roles y sus descripciones, las configuraciones de entrevista y los documentos que forman el corpus. La generación de preguntas utiliza el estado y la descripción del rol; la evaluación utiliza, entre otros datos, fragmentos recuperados del corpus.
>
> Por otro lado, se gestionan las entrevistas de los candidatos: se pueden programar, activar, asignar a un reviewer y administrar sus enlaces.
>
> Para estas operaciones, la interfaz se comunica con rutas de la API como `/admin/roles`, para gestionar roles, y `/admin/interviews`, para gestionar entrevistas. Son grupos de rutas con distintas operaciones, no un único endpoint para todas las acciones.
>
> También hay herramientas de auditoría y análisis. Una limitación importante es que **los umbrales de decisión, conclusión y confianza usan actualmente valores fijos en el grafo**; los de dificultad sí se leen desde el estado y se pueden configurar por rol.

## Diapositiva 6 — Portal Candidate

> El candidato ingresa mediante un enlace asociado a su entrevista. En la interfaz ve el rol y acepta el aviso de integridad.
>
> La telemetría de foco es opcional, y el candidato puede declarar acomodaciones para que determinadas familias de señales no se consideren.
>
> Después responde el warm-up y continúa con las preguntas evaluadas. La experiencia busca que la entrevista pueda adaptarse a las respuestas y que, si se interrumpe, pueda retomarse.
>
> Al finalizar, el candidato recibe una confirmación; la evaluación interna y las fuentes quedan del lado de revisión.

### Cómo se conecta la interfaz del candidato con la API y LangGraph

> Para entender qué ocurre detrás de la pantalla, primero aclaro que un **endpoint** es una ruta de la API a la que la interfaz hace una solicitud. `GET` se utiliza aquí para consultar información, mientras que `POST` se utiliza para enviar datos o solicitar una operación.
>
> Cuando el candidato abre su enlace, la interfaz consulta `GET /candidate/interviews/{token}` para validar el acceso y obtener los datos de la entrevista. El token identifica el enlace; no es el identificador de la corrida.
>
> Al comenzar, la interfaz envía `POST /run/start`. La API inicia la corrida o, si corresponde y está disponible, recupera una existente. Devuelve un identificador llamado `run_id` y la pregunta que corresponde mostrar: el warm-up si todavía está pendiente, o la pregunta actual si se retoma la entrevista.
>
> Cada vez que el candidato envía una respuesta, la interfaz usa `POST /run/answer` con el `run_id` y el texto. Si es la respuesta del warm-up, la API la registra e **inicia** LangGraph: el grafo solicita la primera pregunta evaluada y se interrumpe para esperarla.
>
> En las respuestas evaluadas, la API **reanuda** el grafo con el texto recibido. LangGraph coordina la recuperación de contexto y la evaluación, y aplica la política que decide cómo continuar. Si hace falta otra pregunta, el grafo la solicita al generador y vuelve a pausarse; la API devuelve esa pregunta a la interfaz. Si termina la etapa automática, la API comunica la finalización y el grafo queda a la espera de la revisión humana.
>
> En resumen, la interfaz muestra las preguntas y envía las respuestas; FastAPI recibe y coordina las solicitudes; LangGraph mantiene el flujo y su estado. Cuando se utiliza un modelo de lenguaje, es el modelo quien genera el texto de la pregunta o participa en su evaluación, según el componente configurado.

## Diapositiva 7 — Telemetría e integridad

> Esta diapositiva presenta la información de integridad.
>
> El sistema puede registrar distintas señales de interacción, como tiempos o patrones de entrada. El foco es opcional y está desactivado por defecto. El warm-up se utiliza como referencia para algunas comparaciones.
>
> A partir de las señales disponibles se construye un índice llamado AAI, que puede ayudar a priorizar qué revisar. **No es una probabilidad de fraude ni modifica el puntaje de competencia del candidato**.
>
> El reviewer puede ver las señales, las acomodaciones y los posibles factores de confusión. Una señal aislada —por ejemplo, una pérdida de foco— no demuestra por sí sola una conducta indebida.

## Diapositiva 8 — Portal Reviewer

> En el Reviewer se reúne la información necesaria para auditar la entrevista.
>
> La persona revisora puede entrar desde la cola o buscar una corrida por su identificador. Una vez dentro, puede consultar preguntas y respuestas, puntajes, fuentes recuperadas, checkpoints y decisiones del grafo.
>
> También puede analizar la cobertura de competencias y el apéndice de integridad.
>
> En `Event Stream`, la sección `Grounding evidence` permite abrir los fragmentos del corpus asociados a cada respuesta evaluada. La relevancia de recuperación mide similitud de búsqueda; no es el puntaje de la respuesta.
>
> Para consultar el detalle, el portal utiliza `GET /runs/{run_id}/audit`, donde `run_id` identifica la corrida. Cuando la persona toma una decisión, envía `POST /runs/{run_id}/review` con su decisión y justificación; la API la registra y, si el grafo está esperando en revisión humana, lo reanuda para continuar hacia el reporte.
>
> La decisión humana permite aprobar o sobrescribir la ruta propuesta por el sistema, siempre con una justificación. Es el punto en el que la automatización se convierte en una recomendación revisable, no en una decisión definitiva de contratación.

---

# Parte principal: LangGraph y el candidato

## Diapositiva 9 — De la pantalla a la entrevista

> Acá vemos cómo se conectan la pantalla del candidato, la API y LangGraph.
>
> Primero, la interfaz consulta `GET /candidate/interviews/{token}` para validar el enlace y obtener los datos de la entrevista. Al comenzar envía `POST /run/start`; la API inicia o recupera la corrida y devuelve el warm-up o la pregunta que corresponde.
>
> Al responder el warm-up, la interfaz usa `POST /run/answer`. La API registra esa respuesta e inicia el grafo, que solicita la primera pregunta evaluada y se pausa en `await_candidate`. La API devuelve esa pregunta a la interfaz.
>
> Con cada respuesta evaluada, la interfaz vuelve a llamar a `POST /run/answer` y la API reanuda el grafo con el texto recibido. El grafo coordina recuperación, evaluación y decisión. Puede solicitar otra pregunta y volver a pausarse, o pasar a `human_review`. Una vez registrada la decisión humana, se reanuda hacia el reporte.
>
> La API no genera la pregunta por sí sola: coordina la solicitud. Si está configurado un generador con modelo, el generador prepara el prompt y el modelo redacta la pregunta.

## Diapositiva 10 — Flujo de nodos

> Esta es la parte central de la solución: **cómo LangGraph conduce la entrevista del candidato**.
>
> En vez de ejecutar una secuencia fija de preguntas de principio a fin, representamos la entrevista como un grafo. Cada nodo tiene una responsabilidad y el grafo conserva un estado compartido.
>
> Ese estado incluye, entre otras cosas, el rol, la competencia actual, el número de turno, la dificultad, los puntajes acumulados y las decisiones anteriores. Así, cada paso puede trabajar con el contexto de la entrevista.
>
> La API presenta el warm-up antes de las preguntas evaluadas. Una vez enviada esa respuesta, inicia el grafo. El nodo `generate_question` llama al generador configurado y guarda la pregunta obtenida en el estado; luego `await_candidate` **interrumpe la ejecución** hasta recibir una respuesta.
>
> Cuando la API recibe la respuesta, reanuda el grafo, que continúa por `plan`, `retrieve`, `evaluate` y `decide`. La decisión puede llevarlo a solicitar otra pregunta al generador o a pasar a revisión humana.
>
> Los checkpoints permiten persistir el estado de esas pausas. De esa manera, la ejecución no permanece bloqueada esperando al candidato: la API puede reanudarla con la respuesta. Esta recuperación depende de que la persistencia esté configurada y disponible.

## Diapositiva 11 — ¿Qué hace cada nodo?

> Voy a recorrer los nodos siguiendo lo que vive un candidato.
>
> Primero, el nodo `generate_question` obtiene los datos del estado y llama al generador de preguntas configurado. Si usa un modelo de lenguaje, el generador construye un prompt con el rol, su descripción, la competencia, la dificultad y el turno, y se lo envía al modelo. **El modelo genera el texto; LangGraph coordina la llamada y guarda el resultado**.
>
> Si la generación con modelo no está habilitada, puede utilizarse un generador determinístico con preguntas predefinidas. Si un generador configurado informa un error, el nodo devuelve un mensaje de saturación, no necesariamente una pregunta alternativa.
>
> Luego, `await_candidate` crea una interrupción con la pregunta y el turno. Cuando la API recibe una respuesta no vacía, reanuda esa ejecución con el texto del candidato.
>
> Con la respuesta disponible, `plan` registra la competencia actual del estado; no hace una planificación autónoma con un modelo. Luego, `retrieve` busca hasta dos fragmentos del corpus usando la competencia y la respuesta, con filtros para el rol y el tipo de documento. Esos fragmentos se pasan al evaluador como contexto.
>
> Después, `evaluate` selecciona el evaluador configurado. Si usa un modelo de lenguaje, le envía la respuesta, la competencia, el rol, el tipo de documento y los fragmentos recuperados. El adaptador procesa la salida del modelo: puntaje, indicador de respuesta fuera de tema, señal mixta y evidencia. El nodo también registra referencias a los fragmentos.
>
> Si no hay un evaluador con modelo habilitado, se utiliza uno determinístico. Ante errores del adaptador del modelo, el nodo reintenta y puede recurrir al evaluador determinístico; este también exige que haya evidencia recuperada, así que el respaldo no garantiza que toda evaluación pueda completarse.
>
> El nodo `decide` actualiza la dificultad a partir de la respuesta y llama a una función de reglas determinísticas con el puntaje, las señales y el estado acumulado. Esa función elige entre profundizar, cambiar de competencia, concluir o escalar; no es el modelo quien elige directamente la ruta.
>
> Por último, las rutas de conclusión o escalamiento llegan a `human_review`, que interrumpe el grafo. El reviewer aprueba o sobrescribe la ruta y aporta una justificación; con esa información, `report` construye el resultado del grafo.

### Ejemplo oral para acompañar el diagrama

> Por ejemplo, imaginemos que el candidato está respondiendo una pregunta sobre confiabilidad de pruebas.
>
> Cuando envía su respuesta, la API reanuda el grafo. El nodo de recuperación busca fragmentos para el rol y la competencia usando también la respuesta; el evaluador recibe esos fragmentos como contexto. Después, la política de decisión considera el score actual, las señales, cuántas competencias quedan por recorrer, los turnos usados y el promedio acumulado.
>
> Con esos datos decide si necesita una pregunta más o si ya puede pasar la entrevista al reviewer.

## Diapositiva 12 — Política adaptativa

> En esta diapositiva vemos las reglas que determinan la ruta. Son importantes porque **se evalúan en orden: la primera que se cumple define qué hace el sistema**.
>
> Si el contador acumulado llega a dos respuestas fuera de tema, el sistema escala el caso; no tienen que ser consecutivas. Si después del turno actual quedan tantos turnos o menos que competencias posteriores pendientes, decide cambiar de competencia para intentar recorrerlas.
>
> También puede cambiar de competencia cuando la evaluación informa una señal mixta o cuando el score es al menos 0,75, siempre que queden competencias posteriores pendientes.
>
> Para concluir necesita que no queden competencias posteriores en la secuencia, que el promedio de los scores evaluados —incluido el actual— alcance 0,70 y que el score actual alcance 0,55. Ese promedio se llama confianza en el código, pero es un promedio de puntajes, no una probabilidad calibrada.
>
> Después de las reglas anteriores, si está en el último turno permitido y todavía no se eligió una ruta, escala. En los demás casos, profundiza con otra pregunta.
>
> Tanto `conclude` como `escalate` llevan a revisión humana: no significan que el sistema contrate o rechace al candidato.

### Ejemplo concreto de la corrida

> En la corrida que analizamos, la tercera respuesta obtuvo **0,60**. La entrevista terminó porque ya no quedaban competencias pendientes, el promedio de las tres respuestas era aproximadamente **0,77** y el último score superaba el mínimo de conclusión de **0,55**.
>
> Aunque el máximo configurado era de seis preguntas, eso es un **límite máximo**, no una obligación de hacer las seis.
>
> El 0,75 que aparece en la política corresponde a una regla de cambio de competencia; no es el mínimo exigido para concluir.

### Aclaración complementaria — Configuración frente a ejecución

> Acá aparece una limitación técnica importante.
>
> El estado del sistema contempla valores como el umbral de decisión, el de conclusión y el de confianza. Sin embargo, en la implementación que revisamos, el nodo `decide` no transmite esos tres valores al contexto de decisión. Por eso la política termina utilizando los valores por defecto.
>
> Esto significa que **no debemos asumir que modificar esos umbrales en la configuración cambia la ruta real de LangGraph**. En la interfaz revisada esos tres valores se muestran fijos; en cambio, los umbrales de dificultad sí se leen desde el estado.
>
> Es una diferencia entre lo que se configura o se muestra y lo que efectivamente se ejecuta. Corregirla y probarla por rol es uno de los próximos pasos.

### Ejemplo complementario de auditoría

> Este ejemplo muestra por qué la trazabilidad y la revisión humana son necesarias.
>
> En una corrida que analizamos, el sistema asignó puntajes altos y terminó con una cobertura completa de las competencias. Sin embargo, al comparar la pregunta con la respuesta, se observó que una respuesta repetida sobre APIs recibió un puntaje alto frente a una pregunta de otro tema.
>
> Entonces, un promedio alto y una cobertura del 100 % nos dicen que el flujo avanzó, pero **no garantizan por sí solos que la evaluación haya sido pertinente**.
>
> El reviewer necesita poder contrastar la pregunta, la respuesta y la evidencia, y no quedarse solamente con el número.

## Diapositiva 13 — RAG, modelos y trazabilidad

> La evaluación se apoya en RAG: el sistema recupera hasta dos fragmentos del corpus buscando con la competencia y la respuesta, y filtrando por rol y tipo de documento. El evaluador con modelo recibe esos fragmentos como contexto junto con la respuesta.
>
> Antes de la entrevista, los documentos se dividen en fragmentos y se indexan. En esta implementación, la representación utilizada para la búsqueda se basa en frecuencia de palabras, no en un modelo de embeddings semánticos. En el Reviewer se pueden abrir las fuentes desde `Grounding evidence`.
>
> El modelo devuelve el score, señales como `off_topic` y `mixed_signal`, y evidencia que el prompt pide como citas textuales de la respuesta. El adaptador comprueba si esas citas aparecen en la respuesta; si faltan o alguna no coincide, registra una advertencia, pero **conserva la evaluación del modelo**. Por eso hay que revisar esa evidencia con cautela.
>
> LangSmith permite observar las ejecuciones del grafo cuando está configurado. Eso ayuda a seguir el recorrido y entender qué pasó en cada paso. Los proveedores se invocan mediante adaptadores propios, por lo que no debemos asumir que cada llamada al modelo aparezca automáticamente como un span específico de LLM. Las trazas pueden contener datos de las entrevistas.
>
> Una limitación observada es que el prompt de evaluación no incluye el texto de la pregunta. Por eso, un puntaje alto no alcanza para asegurar que la respuesta sea pertinente a lo que se preguntó. Es un punto prioritario para mejorar y probar.

## Cierre oral opcional — Conclusiones y próximos pasos

> Como conclusión, AI Interviewer integra la preparación, la entrevista adaptativa y la revisión en un mismo proceso.
>
> LangGraph aporta la coordinación: mantiene el estado, interrumpe la ejecución para recibir al candidato o al reviewer y ejecuta el nodo que aplica reglas para decidir cómo continúa la entrevista. Los generadores y evaluadores configurados realizan las tareas de pregunta y evaluación.
>
> A la vez, el trabajo muestra límites concretos. Los próximos pasos más importantes son mejorar la evaluación de pertinencia entre pregunta y respuesta, verificar la cobertura real de competencias y corregir la propagación de los umbrales configurables.
>
> En definitiva, el sistema busca **asistir una decisión humana con información trazable**, no reemplazarla.

## Referencias para mencionar si corresponde

> Para elaborar el trabajo se contrastaron los documentos funcionales, los diagramas del flujo y la implementación. También se revisaron trazas y auditorías de corridas para comparar lo esperado con lo que realmente ejecuta el sistema.

---

### Frase de cierre breve

> El valor de la solución no está solo en automatizar preguntas, sino en poder reconstruir qué preguntó, cómo evaluó y por qué decidió continuar o pasar a revisión. Y, justamente por sus límites, mantener a la persona revisora dentro del proceso.
