# Agent Mode - Sistema Híbrido de Modelos

## Arquitectura

**Modo Agentic usa 2 modelos especializados:**

1. **DeepSeek-R1:14b** - Razonamiento (thinking)
2. **JarvisCoder** - Generación de código y descomposición

## Flujo de Trabajo

```
@agent [task]
    ↓
1. Analyzing (DeepSeek-R1)
   → Chain-of-thought reasoning
   → Fallback: llama3.1 → uncensored-llama2
    ↓
2. Planning (JarvisCoder)
   → Decompose into steps
   → Fallback: deepseek-coder-v2 → llama3.1
    ↓
3. Execution (Modelo actual)
   → Ejecuta cada step
```

## Ventajas

- **Thinking especializado:** R1 tiene thinking tokens nativos
- **Código optimizado:** JarvisCoder entrenado para código
- **Robusto:** Fallbacks automáticos si modelo no disponible
- **Eficiente:** Usa modelo correcto para cada fase

## Uso

```bash
> @agent add authentication to /home/chris/api

🤔 Analyzing task... (DeepSeek-R1)
📋 Creating plan... (JarvisCoder) 
⚙️ Executing... (tu modelo actual)
```

## Modelos Requeridos

**Recomendados:**
- `deepseek-r1:14b` (thinking)
- `jarviscoder:latest` (código)

**Fallbacks funcionan con:**
- `llama3.1:8b`
- `deepseek-coder-v2:16b`
- `uncensored-llama2:latest`

## Configuración RAM

DeepSeek-R1 requiere ~2.5GB RAM disponible.

Si tienes problemas de memoria:
- El sistema automáticamente usa llama3.1
- O cambia a modelos más pequeños en el fallback

Sistema se adapta automáticamente a tu hardware disponible.
