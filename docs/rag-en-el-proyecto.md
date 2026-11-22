# RAG: funcionamiento y aplicación en AI Interviewer

## ¿Qué es RAG?

**RAG** significa *Retrieval-Augmented Generation*, o **generación aumentada por recuperación**. Es una forma de incorporar información externa recuperada como contexto para una tarea realizada con un modelo de lenguaje.

En lugar de depender solamente de la información aprendida durante su entrenamiento, se buscan fragmentos de documentos y se incluyen en la solicitud al modelo. Esto permite orientar la respuesta o la evaluación hacia una fuente disponible para el sistema.

RAG **no es un modelo de inteligencia artificial por sí mismo**. Es una forma de combinar recuperación de información con una tarea de generación o análisis. Tampoco garantiza por sí solo que los fragmentos sean correctos o que el modelo los interprete bien.

## Cómo funciona en general: paso a paso

1. **Preparación de los datos.** Se obtienen documentos, por ejemplo, manuales, archivos PDF o preguntas frecuentes. Su contenido se extrae y se divide en fragmentos más pequeños, llamados *chunks*.

2. **Vectorización e indexación.** Cada fragmento se transforma en una representación numérica llamada *embedding* o vector. Se almacena junto con su texto y sus metadatos para poder buscarlo posteriormente. Algunos sistemas usan modelos de embeddings semánticos; otros utilizan representaciones más simples basadas en palabras.

3. **Búsqueda o recuperación.** Cuando llega una consulta, el sistema la transforma en una representación comparable y busca los fragmentos más relacionados. Puede aplicar filtros, como el tipo de documento o la categoría.

4. **Generación con contexto.** La aplicación envía al modelo la consulta o tarea original junto con los fragmentos recuperados. El prompt puede pedirle que se base en ellos para producir una respuesta. Esa instrucción ayuda a orientar al modelo, pero no garantiza que siempre la cumpla.

En términos simples:

```text
Documentos → fragmentos → vectores e índice
                                ↓
Consulta → búsqueda → fragmentos recuperados → prompt → modelo → resultado
```

La preparación de documentos normalmente ocurre antes de la consulta. La recuperación y la llamada al modelo ocurren cuando se necesita resolver una tarea.

## Cómo se aplica en AI Interviewer

En nuestro proyecto, el contexto recuperado se usa principalmente para **evaluar las respuestas del candidato**. La tarea no es contestarle una pregunta al usuario con los documentos: es aportar contexto al evaluador para valorar una respuesta de la entrevista.

### 1. Preparar e incorporar el corpus

El **corpus** es el conjunto de documentos disponibles para recuperación. El administrador puede incorporar archivos `.pdf`, `.docx` y `.md`. El sistema intenta extraer el texto y registra un error si no encuentra texto legible o falla la ingesta. Un PDF que solo contiene imágenes, por ejemplo, puede no aportar texto legible mediante esta extracción.

El sistema también puede indexar descripciones de roles y dispone de documentos de ejemplo, según la configuración. Los documentos se asocian a datos como el **rol** y el **tipo de documento**, que luego se utilizan como filtros.

### 2. Dividir los documentos en fragmentos

El texto se divide principalmente por bloques separados por líneas en blanco. El proceso conserva información como el identificador del documento, el rol, el tipo de documento y la sección; cuando corresponde, incorpora parte del final del bloque anterior para mantener contexto entre fragmentos.

Esto permite recuperar partes del documento, en lugar de enviar necesariamente el documento completo al evaluador.

### 3. Crear y almacenar las representaciones

El componente implementado, `TokenFrequencyEmbedder`, crea una representación basada en la **frecuencia normalizada de palabras o tokens**. Es importante no confundirla con un modelo de embeddings semánticos: en esta implementación la relación se basa principalmente en coincidencias de tokens, no en una comprensión profunda del significado.

Hay dos alternativas de almacenamiento y búsqueda:

- **En memoria:** usa un índice en memoria, preparado a partir de los documentos de ejemplo y de los documentos incorporados al servicio.
- **PostgreSQL con pgvector:** usa la extensión `pgvector` para almacenar y comparar representaciones vectoriales en PostgreSQL, si se configura esa opción.

Usar PostgreSQL para los datos operativos **no implica por sí solo** que la recuperación esté usando pgvector: el mecanismo de recuperación se configura por separado. Sin inspeccionar la configuración efectiva de una ejecución no podemos asegurar cuál de los dos está activo.

### 4. Recuperar contexto para una respuesta

Después de que el candidato responde una pregunta evaluada, la API reanuda LangGraph. El flujo llega al nodo `retrieve`, que construye la búsqueda combinando:

- La **competencia actual**, por ejemplo, `test_reliability`.
- El texto de la **respuesta del candidato**.

La búsqueda filtra por rol y tipo de documento. Primero intenta encontrar fragmentos asociados a la competencia; si no encuentra resultados, prueba con filtros de rol y tipo de documento. Como respaldo puede devolver fragmentos de ese conjunto aun sin coincidencias de tokens. Recupera **hasta dos fragmentos**, junto con identificadores de origen y un puntaje de similitud.

Por eso, un fragmento recuperado no necesariamente tiene una coincidencia fuerte con la respuesta. El puntaje de búsqueda mide similitud para la recuperación; **no es el puntaje de la respuesta del candidato**.

### 5. Evaluar con el contexto recuperado

El nodo `evaluate` recibe la respuesta y los fragmentos recuperados. Según la configuración:

- Si hay un **evaluador con modelo de lenguaje**, el adaptador prepara un prompt con la respuesta, la competencia, el rol, el tipo de documento y los fragmentos. Le pide al modelo un puntaje, señales y evidencia, y le indica que base la evaluación en la respuesta y el corpus recuperado.
- Si no hay un evaluador con modelo habilitado, se utiliza un **evaluador determinístico**, basado en reglas. También puede utilizarse como respaldo ante errores del adaptador del modelo. Este evaluador igualmente requiere evidencia recuperada, por lo que el respaldo no garantiza que la evaluación siempre pueda completarse.

Cuando se utiliza un modelo, **el modelo produce la evaluación** y LangGraph coordina la ejecución del nodo y registra el resultado. La instrucción de basarse en el corpus no garantiza que el modelo lo haga correctamente.

### 6. Continuar la entrevista y permitir la revisión

El nodo `decide` aplica reglas sobre el resultado y el estado de la entrevista para definir si corresponde profundizar, cambiar de competencia, concluir o escalar. La decisión de ruta es determinística: no la toma directamente el modelo evaluador.

El sistema registra referencias a los fragmentos usados, junto con otros datos de la evaluación, para que el reviewer pueda inspeccionar lo sucedido. El reviewer es quien debe interpretar esos datos y tomar la decisión humana.

```text
Administrador → incorpora documentos → extracción → fragmentos → índice

Candidato → responde
                 ↓
FastAPI → reanuda LangGraph
                 ↓
retrieve: competencia + respuesta → hasta 2 fragmentos
                 ↓
evaluate: respuesta + contexto → puntaje, señales y evidencia
                 ↓
decide: reglas → siguiente pregunta o revisión humana
```

## Diferencias importantes para explicarlo con precisión

- **RAG no genera necesariamente la pregunta.** En el flujo revisado, la generación de preguntas utiliza el estado y la descripción del rol; la recuperación explicada aquí se aplica a la evaluación posterior de la respuesta.
- **Los embeddings de este proyecto no son embeddings semánticos de un modelo neuronal.** La implementación revisada usa frecuencias de tokens.
- **La pregunta de entrevista no se incluye en el prompt del evaluador con modelo** en la implementación revisada. Por eso, aunque use contexto recuperado, no podemos asegurar que el modelo valore correctamente si la respuesta contesta lo preguntado.
- **La evidencia de la evaluación y las fuentes recuperadas son cosas distintas.** Al modelo se le piden citas textuales de la respuesta del candidato como evidencia; además se registran referencias a los fragmentos del corpus usados como contexto. Si las citas faltan o no coinciden con la respuesta, se registra una advertencia, pero se conserva la evaluación del modelo.
- **Recuperar contexto no garantiza exactitud.** La calidad depende de los documentos, de la búsqueda y del evaluador. Tampoco reemplaza la revisión humana.

## Ejemplo para contarlo oralmente

> En nuestro proyecto usamos RAG para aportar contexto a la evaluación de las respuestas. Primero incorporamos documentos del rol, extraemos su texto, los dividimos en fragmentos y los indexamos.
>
> Cuando el candidato responde, LangGraph busca hasta dos fragmentos combinando la competencia actual con la respuesta y filtrando por el rol y el tipo de documento. Si está configurado un evaluador con modelo de lenguaje, el sistema le envía esa respuesta y los fragmentos recuperados, y le pide una evaluación fundamentada en ellos.
>
> Es importante aclarar que nuestra búsqueda usa una representación basada en frecuencia de palabras, no un modelo semántico de embeddings. Y el modelo no decide por sí solo cómo sigue la entrevista: después de evaluar, una política de reglas determina la ruta. Finalmente, el reviewer puede revisar el resultado y sus fuentes.

## Archivos de referencia

- [Ingesta y división de documentos](../services/agent/retrieval/ingestion.py)
- [Representación basada en frecuencia de tokens](../services/agent/retrieval/embedder.py)
- [Configuración y recuperación de contexto](../services/agent/retrieval/service.py)
- [Nodos de recuperación, evaluación y generación de preguntas](../services/agent/graph/studio_graph.py)
- [Prompt y validación de la evaluación con modelo](../services/agent/graph/llm.py)
- [Extracción y administración de documentos](../services/api/corpus.py)
