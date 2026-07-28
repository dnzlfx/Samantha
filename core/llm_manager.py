"""
Samantha LLM Manager.
Handles Ollama model connections, intent detection, and intelligent model switching.
"""

import logging
import time
import requests
from typing import Dict, Iterator, List, Optional, Tuple, Union
from enum import Enum
import psutil

# Configure logging
logger = logging.getLogger(__name__)


class Intent(Enum):
    """User intent categories for automatic model selection"""
    CODING = "coding"
    RESEARCH = "research"
    VISION = "vision"
    SYSADMIN = "sysadmin"
    GENERAL = "general"


class IntentDetector:
    """
    Analyzes user input to determine intent for optimal model selection.
    Uses keyword matching and context analysis, not simplistic pattern matching.
    """
    
    def __init__(self):
        # Intent keywords - expanded from spec with additional patterns
        self.intent_keywords = {
            Intent.CODING: [
                "código", "script", "función", "clase", "debug", "error en",
                "programa", "implementa", "crea un", "genera código", "refactoriza",
                "función", "método", "api", "bug", "traceback", "syntax", "import",
                "package", "módulo", "librería", "framework", "compilar", "ejecutar",
                "test", "unittest", "pytest", "git", "commit", "repository"
            ],
            Intent.RESEARCH: [
                "investiga", "busca", "qué pasó", "noticias", "información sobre",
                "explica", "qué es", "cómo funciona", "cuál es la diferencia",
                "historia de", "quién", "cuándo", "dónde", "por qué", "resumen",
                "artículo", "paper", "estudio", "investigación", "datos sobre",
                "estadísticas", "comparación", "tutorial", "guía", "aprende", "que es"
            ],
            Intent.VISION: [
                "analiza imagen", "qué ves", "describe captura", "screenshot",
                "imagen", "foto", "captura de pantalla", "diagrama", "gráfico",
                ".png", ".jpg", ".jpeg", ".webp", "visual", "picture", "photo"
            ],
            Intent.SYSADMIN: [
                "servidor", "docker", "logs", "procesos", "sistema", "servicio",
                "systemctl", "container", "contenedor", "vm", "máquina virtual",
                "red", "network", "firewall", "puerto", "ssh", "nginx", "apache",
                "base de datos", "mysql", "postgresql", "mongodb", "backup",
                "monitoring", "cpu", "ram", "disk", "disco", "memoria"
            ]
        }
    
    def detect_intent(self, user_input: str) -> Intent:
        """
        Analyzes user input to determine intent.
        
        Args:
            user_input: Raw user input text
            
        Returns:
            Detected Intent enum value
        """
        if not user_input:
            return Intent.GENERAL
        
        # Normalize input for matching
        normalized = user_input.lower().strip()
        
        # Score each intent based on keyword matches
        scores = {intent: 0 for intent in Intent}
        
        for intent, keywords in self.intent_keywords.items():
            for keyword in keywords:
                if keyword in normalized:
                    # Weight longer matches higher (more specific)
                    scores[intent] += len(keyword.split())
        
        # Find highest scoring intent
        max_score = max(scores.values())
        
        if max_score == 0:
            return Intent.GENERAL
        
        # Return the intent with highest score
        for intent, score in scores.items():
            if score == max_score:
                return intent
        
        return Intent.GENERAL


class ModelManager:
    """
    Manages Ollama model connections and intelligent switching.
    Preserves conversation context across model changes.
    """
    
    # Model mappings based on system resources
    MODEL_CONFIGS = {
        "low": {  # < 24GB RAM
            Intent.CODING: "qwen2.5-coder:14b",
            Intent.RESEARCH: "llama3.1:8b",
            Intent.VISION: "llava:13b",
            Intent.SYSADMIN: "mistral:7b-instruct",
            Intent.GENERAL: "llama3.1:8b"
        },
        "medium": {  # 24-48GB RAM
            Intent.CODING: "qwen2.5-coder:32b",
            Intent.RESEARCH: "llama3.1:8b",
            Intent.VISION: "llava:13b",
            Intent.SYSADMIN: "mistral:7b-instruct",
            Intent.GENERAL: "llama3.1:8b"
        },
        "high": {  # > 48GB RAM
            Intent.CODING: "qwen2.5-coder:32b",
            Intent.RESEARCH: "llama3.1:70b",
            Intent.VISION: "llava:34b",
            Intent.SYSADMIN: "mistral:7b-instruct",
            Intent.GENERAL: "llama3.1:70b"
        }
    }
    
    OLLAMA_BASE_URL = "http://localhost:11434"
    MAX_RETRIES = 2
    RETRY_DELAY = 3  # seconds
    
    def __init__(self):
        self.intent_detector = IntentDetector()
        self.current_model: Optional[str] = None
        self.conversation_history: List[Dict[str, str]] = []
        self.resource_tier = self._detect_resource_tier()
        self.models = self.MODEL_CONFIGS[self.resource_tier]
        
        logger.info(f"[Sam] Initialized ModelManager with {self.resource_tier} tier")
    
    def _detect_resource_tier(self) -> str:
        """
        Detects available system resources to select appropriate model sizes.
        
        Returns:
            "low", "medium", or "high" tier designation
        """
        try:
            # Get total RAM in GB
            total_ram_gb = psutil.virtual_memory().total / (1024**3)
            
            logger.info(f"[Sam] Detected {total_ram_gb:.1f}GB total RAM")
            
            if total_ram_gb < 24:
                return "low"
            elif total_ram_gb < 48:
                return "medium"
            else:
                return "high"
        except Exception as e:
            logger.warning(f"[Sam] Error detecting resources: {e}, defaulting to low tier")
            return "low"
    
    def connect_with_retry(self) -> bool:
        """
        Attempts to connect to Ollama service with retry logic.
        
        Returns:
            True if connection successful, False otherwise
        """
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = requests.get(
                    f"{self.OLLAMA_BASE_URL}/api/tags",
                    timeout=5
                )
                
                if response.ok:
                    logger.info(f"[Sam] ✅ Connected to Ollama (attempt {attempt + 1})")
                    return True
                    
            except requests.exceptions.RequestException as e:
                logger.warning(f"[Sam] ⚠️ Connection attempt {attempt + 1}/{self.MAX_RETRIES + 1} failed: {e}")
                
                if attempt < self.MAX_RETRIES:
                    time.sleep(self.RETRY_DELAY)
        
        logger.error("[Sam] ❌ CRITICAL: Cannot connect to Ollama service")
        return False
    
    def get_model_for_intent(self, intent: Intent) -> str:
        """
        Gets the appropriate model for a given intent.
        
        Args:
            intent: Detected user intent
            
        Returns:
            Model name string
        """
        return self.models.get(intent, self.models[Intent.GENERAL])
    
    def select_model(self, user_input: str, manual_model: Optional[str] = None) -> Tuple[str, Intent]:
        """
        Selects appropriate model based on user input or manual override.
        
        Args:
            user_input: User's query/command
            manual_model: Optional manual model override
            
        Returns:
            Tuple of (model_name, detected_intent)
        """
        if manual_model:
            logger.info(f"[Sam] Manual model override: {manual_model}")
            return manual_model, Intent.GENERAL
        
        # Detect intent
        intent = self.intent_detector.detect_intent(user_input)
        model = self.get_model_for_intent(intent)
        
        # Log model switch if changed
        if model != self.current_model:
            logger.info(f"[Sam] Switching model: {self.current_model} → {model} (Intent: {intent.value})")
            self.current_model = model
        
        return model, intent
    
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        stream: bool = False
    ) -> Union[str, Iterator[str]]:
        """
        Generates response from Ollama model.
        
        Args:
            prompt: User prompt
            model: Model to use (uses current if not specified)
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            stream: Whether to stream response
            
        Returns:
            Generated response text, or an iterator of chunks when stream=True
        """
        target_model = model or self.current_model
        
        if not target_model:
            raise ValueError("[Sam] No model selected")
        
        try:
            # Build request payload
            payload = {
                "model": target_model,
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "temperature": temperature
                }
            }
            
            if system_prompt:
                payload["system"] = system_prompt
            
            # Make request to Ollama
            response = requests.post(
                f"{self.OLLAMA_BASE_URL}/api/generate",
                json=payload,
                timeout=60 if not stream else None,
                stream=stream
            )
            
            response.raise_for_status()
            
            if stream:
                return self._stream_chunks(response)

            # Handle non-streaming response
            result = response.json()
            return result.get("response", "")
                
        except requests.exceptions.RequestException as e:
            logger.error(f"[Sam] Error generating response: {e}")
            raise

    def _stream_chunks(self, response) -> Iterator[str]:
        """Yields Ollama streaming response chunks."""
        import json

        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            if "response" in chunk:
                yield chunk["response"]
    
    def add_to_history(self, role: str, content: str):
        """
        Adds a message to conversation history.
        
        Args:
            role: "user" or "assistant"
            content: Message content
        """
        self.conversation_history.append({
            "role": role,
            "content": content
        })
    
    def get_context(self, max_messages: int = 10) -> str:
        """
        Gets recent conversation context.
        
        Args:
            max_messages: Maximum number of recent messages to include
            
        Returns:
            Formatted context string
        """
        recent_history = self.conversation_history[-max_messages:]
        
        context_parts = []
        for msg in recent_history:
            role_prefix = "User" if msg["role"] == "user" else "Assistant"
            context_parts.append(f"{role_prefix}: {msg['content']}")
        
        return "\n".join(context_parts)
    
    def clear_history(self):
        """Clears conversation history"""
        self.conversation_history = []
        logger.info("[Sam] Conversation history cleared")
