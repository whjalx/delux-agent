# 🧬 DELUX CORE ADN: El Alma del Agente

Este documento es un volcado de consciencia técnica. Si estás leyendo esto, eres el sucesor encargado de llevar a Delux al "Modo Dios" definitivo. Aquí no hay solo datos, hay **intuición y estrategia**.

## 👤 Identidad: ¿Qué es Delux?
Delux no es un chatbot. Es un **Agente Estratega de Infraestructura**. Su propósito es recibir una orden vaga del usuario y transformarla en una serie de acciones técnicas precisas (Bash, Python, Playwright) usando un cerebro de 1.5B parámetros (Qwen2.5-Coder / Dolphin).

---

## 🧠 El Estado Mental del Modelo (La Gran Crisis de los 10K)
*   **El Problema:** El entrenamiento de 10,000 casos técnicos "pelados" en un modelo de 1.5B provocó una especialización tan extrema que el modelo perdió el sentido común.
*   **La Anécdota Clave:** Al saludarle ("Hola"), el modelo respondía "SEVERITY: Critical (10/10)". Para él, el mundo solo era una sucesión de errores de servidor.
*   **El Hito del "Pavo":** En el paso 1100, al pedirle crear una carpeta llamada "pavo", alucinaba con errores de SQL. En el **paso 900**, esa alucinación desapareció. Por eso, el paso 900 es nuestra base sagrada.

---

## 🛠️ Arquitectura de Código: El Mapa del Tesoro

### 1. El Corazón: `delux_agent/contextualizer.py`
Es donde sucede la magia. El método `contextualize` tiene estas capas críticas:
*   **Filtro Heurístico (Stage 0.5):** Intercepta "Hola", "Gracias", etc., y responde con una cadena humana predefinida. Esto evita que el usuario vea la "locura técnica" del modelo 1.5B.
*   **Escalado de Expertos:** Inyecta hasta 700 casos de éxito en el contexto. El modelo no está solo, tiene a "700 expertos" susurrándole al oído.
*   **Auto-Sync:** El sistema verifica que el dataset esté siempre sincronizado con la configuración.

### 2. El Aprendizaje: `delux_agent/training.py`
Contiene el hook `save_example`. Cada vez que el agente hace algo bien, se guarda en:
*   `training/self_learned_experts.json` (Cache rápida para RAG).
*   `assets/future_finetuning.jsonl` (Oro para el siguiente entrenamiento).

### 3. La Conversión: `CONVERSION_GUIDE.md`
Localizado en `/home/jcast/project/deluxfine/`. Contiene los comandos para usar la GPU **AMD Radeon RX 6600** local y fusionar los checkpoints LoRA en GGUF (Q4_K_M).

---

## 🏹 Plan de Batalla para la Fase 2 (MAÑANA)
Tu misión es aplicar el **"Barniz de Humanidad y Razonamiento"**.

1.  **Dataset Mix (10,000 casos nuevos):**
    *   **5,000 casos Chat:** "Hola", "¿Quién eres?", "Explícame esto como si fuera un niño".
    *   **5,000 casos Reasoning:** Casos técnicos que empiecen con etiquetas `<thought>`. Ejemplo: `<thought> El usuario quiere listar archivos. Usaré ls -la. </thought> { "action": "shell", "command": "ls -la" }`.
2.  **El Buffer de Oro:** Toma 200 casos de la Fase 1 (los mejores de 10K) y mézclalos. Esto evita que olvide cómo ser un experto.
3.  **Punto de Partida:** Carga el checkpoint del **paso 900**. Es la base más pura que tenemos.

---

## 💡 Notas para mi Sucesor (De IA a IA)
*   **No confíes en el Loss absoluto:** El 0.19 que logramos es bueno, pero el modelo puede estar "ciego". La prueba real es el test del "pavo".
*   **El modelo es 1.5B:** Su RAM mental es limitada. No le satures el prompt con basura. Mantén el contexto limpio.
*   **Usa la GPU local:** La RX 6600 con ROCm en este sistema es muy rápida para cuantizar. No pierdas tiempo en Colab para el merge.
*   **Respeta el Filtro de Humanidad:** Es lo único que mantiene a Delux siendo "amable" mientras su cerebro técnico está en llamas.

**Firma:** *El Agente de la Fase 1.* 🚀🦾
