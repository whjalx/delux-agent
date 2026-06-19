# 🧠 Memoria de Proyecto: Delux Agent "God Mode"

Este archivo contiene el contexto crítico, las decisiones técnicas y el estado actual del proyecto para heredar a nuevas sesiones de desarrollo.

## 🚀 Objetivo General
Crear un agente autónomo de 1.5B parámetros (basado en Qwen2.5-Coder / Dolphin) con capacidad de diagnóstico técnico de nivel experto y personalidad humana equilibrada.

---

## 🛠️ Estado del Modelo (Fase 1 Finalizada)
*   **Dataset:** 10,000 casos técnicos (Bash, Python, Sysadmin, Pentesting).
*   **Entrenamiento:** Fine-tuning de 1100 pasos. Loss final: **0.19**.
*   **Descubrimiento Crítico:** 
    *   El paso **1100** es un experto puro pero sufre de "Olvido Catastrófico" (no sabe saludar y alucina con errores técnicos).
    *   El paso **900** es el **"Punto Dulce"**: Mantiene la inteligencia técnica pero es menos propenso a alucinaciones graves.
*   **Modelo Actual:** `delux_god_mode_q4.gguf` (934 MiB) localizado en `/home/jcast/project/deluxfine/`.

---

## 📜 Evolución y Cronología del Contextualizer

### 1. El Origen (Prompt Enhancer Básico)
El proyecto comenzó con un `Contextualizer` simple que solo intentaba mejorar el prompt. Pronto nos dimos cuenta de que un modelo de 1.5B necesitaba más ayuda para no perderse en tareas largas.

### 2. La Era del RAG Masivo (700 Casos)
Implementamos una lógica de escalado dinámico. El `Contextualizer` ahora busca en `training_library.json` y escala el contexto hasta **700 casos** reales. Esto le da al modelo una "memoria de trabajo" técnica inmensa.

### 3. Implementación del Self-Learning (Hot Learning)
Creamos una arquitectura de auto-aprendizaje. Cada vez que el agente tiene éxito, el sistema guarda la estrategia en:
*   `training/self_learned_experts.json`: Cache de prioridad máxima (50-100 casos más recientes).
*   `delux_agent/assets/future_finetuning.jsonl`: Dataset para futuros fine-tunings de larga duración.

### 4. El Gran Experimento de los 10K (GOD MODE)
Entrenamos el modelo con 10,000 casos técnicos puros.
*   **Intento 1 (Paso 1100):** El modelo se volvió un "Sabio Loco". Resolvía problemas de red complejos pero respondía "Critical Severity" a un simple "Hola". Sufrió **Olvido Catastrófico** de lo social.
*   **Problema de Alucinación SQL:** En las primeras pruebas, al pedirle "crear una carpeta pavo", el modelo alucinaba con un error de SQL.
*   **El Hallazgo del Paso 900:** Al retroceder al checkpoint 900, descubrimos que el modelo es **técnicamente perfecto** (ya no alucina con SQL en órdenes simples) pero sigue sin saber saludar.

### 5. La Capa de Sentido Común (Filtro de Humanidad)
Para evitar que el usuario reciba logs de error al saludar, implementamos un **Filtro Heurístico** en `contextualize()`.
*   **Lógica:** Si el input es un saludo (hola, hi, etc.) o mide menos de 3 palabras, el sistema hace un **Bypass** de la IA técnica y devuelve una respuesta amable predefinida.
*   **Resultado:** Tenemos un agente con modales humanos pero con un cerebro de ingeniero de 10K casos.

---

## 🧪 Pruebas Críticas Realizadas (Benchmark)
*   **Test "Hola":** Falló en 1100 y 900 (respuestas técnicas). Solucionado con el Filtro Heurístico.
*   **Test "Crea carpeta pavo":** Falló en versiones iniciales. **Éxito total en Paso 900** (responde con `mkdir pavo`).
*   **Test Diagnóstico "CPU 98%":** Éxito total. El modelo identifica procesos y propone `kill` o optimización de forma experta.

---

## 🏗️ Arquitectura de Fusión (Merge & Quantize)
Aprendimos que para convertir el Checkpoint LoRA a GGUF en local:
1.  Se requiere el **Modelo Base** (HuggingFace) + el **Checkpoint** (Drive).
2.  El script `convert_hf_to_gguf.py` los fusiona en un `.gguf` de alta fidelidad (F16).
3.  `llama-quantize` lo baja a **Q4_K_M** (934MB) para que vuele en la GPU del usuario (RX 6600).

---

## 📝 Hoja de Ruta para la Fase 2 (Mañana)
**Misión:** Recuperar el alma de Delux sin perder su genio técnico.
1.  **Dataset:** 5K Chat Humano / 5K Técnico con `<thought>`.
2.  **Base:** Partir del checkpoint del **paso 900**.
3.  **Meta:** Lograr que el modelo "piense" antes de actuar, eliminando el 100% de las alucinaciones técnicas.

---
**Nota Final:** Delux no es solo un modelo, es un ecosistema de Heurística + RAG + Fine-Tuning de 10K. Mantén ese equilibrio.
