#!/usr/bin/env python3
"""
Intent Detector - Autonomous Decision Making
Detects user intent and automatically calls appropriate APIs without confirmation.
"""

import re
from typing import Dict, Optional, List, Tuple
from enum import Enum


class Intent(Enum):
    """User intent categories"""
    BIOGRAPHY = "biography"
    WEATHER = "weather"
    NEWS = "news"
    DEFINITION = "definition"  
    TRANSLATION = "translation"
    CALCULATION = "calculation"
    COUNTRY_INFO = "country"
    BOOK_SEARCH = "book"
    RECIPE = "recipe"
    TRIVIA = "trivia"
    GITHUB = "github"
    STACKOVERFLOW = "stackoverflow"
    CRYPTO = "crypto"
    IP_INFO = "ip_info"
    # Visual intents
    ANALYZE_IMAGE = "analyze_image"
    TAKE_PHOTO = "take_photo"
    READ_SCREEN = "read_screen"
    # Contextual visual queries
    WHAT_AM_I_HOLDING = "what_holding"
    WHAT_DO_YOU_SEE = "what_see"
    VISUAL_CONFIRMATION = "visual_confirm"  # "así?" "correcto?" etc.
    # Screen monitoring
    START_SCREEN_WATCH = "start_screen_watch"
    STOP_SCREEN_WATCH = "stop_screen_watch"
    WHAT_TO_DO = "what_to_do"
    IS_THIS_CORRECT = "is_this_correct"
    UNKNOWN = "unknown"


class IntentDetector:
    """
    Detects user intent from natural language queries.
    Automatically determines which API to call.
    """
    
    # Pattern matching for intent detection
    INTENT_PATTERNS = {
        Intent.BIOGRAPHY: [
            r'\b(quien es|quién es|who is)\s+',  # "quien es elon musk"
            r'\b(que es|qué es|what is)\s+([A-Z][a-z]+\s+[A-Z])',  # "que es Albert Einstein"  
            r'\b(biografía de|biography of|háblame de|cuéntame sobre|tell me about)\s+',
        ],
        Intent.WEATHER: [
            r'\b(clima|weather|temperatura|temperature|tiempo)\b',
            r'\b(qué clima|what weather|how hot|how cold)\b',
            r'\b(va a llover|will it rain|hace calor|is it hot)\b',
        ],
        Intent.NEWS: [
            r'\b(noticias|news|últimas noticias|latest news)\b',
            r'\b(qué pasa|what\'s happening|acontecimientos|events)\b',
            r'\b(actualidad|current events)\b',
        ],
        Intent.DEFINITION: [
            r'\b(qué significa|what does.*mean|que significa)\b',
            r'\b(definición de|definition of|define)\b',
        ],
        Intent.TRANSLATION: [
            r'\b(traduce|translate|traducir|cómo se dice|how do you say)\b',
            r'\b(en inglés|in english|en español|in spanish)\b',
        ],
        Intent.CALCULATION: [
            r'\b(cuánto es|how much is|calcula|calculate|resuelve|solve)\b.*[\d+\-*/()]',
            r'^\d+\s*[\+\-\*/]\s*\d+',  # "5 + 3"
            r'\b(raíz|square root|factorial|logaritmo)\b',
        ],
        Intent.COUNTRY_INFO: [
            r'\b(país|country|pais)\s+',  # "pais mexico"
            r'\b(capital de|capital of|población de|population of)\s+',
            r'\b(info.*país|info.*country)\b',
        ],
        Intent.BOOK_SEARCH: [
            r'\blibro\s+',  # "libro 1984"
            r'\bbook\s+',
            r'\b(busca.*libro|search.*book|recomienda.*libro|recommend.*book)\b',
        ],
        Intent.RECIPE: [
            r'\b(receta|recipe)\s+(de|para|of|for)\s+',  # "receta de tacos"
            r'\b(cómo cocinar|how to cook|cómo preparar|how to make)\s+',
            r'\b(ingredientes|ingredients)\b',
        ],
        Intent.CRYPTO: [
            r'\b(bitcoin|btc|ethereum|eth|crypto|criptomoneda)\b',
            r'\b(precio.*bitcoin|bitcoin.*precio|cuánto.*bitcoin|cuanto.*bitcoin)\b',
            r'\b(a cuánto|a cuanto)\s+(está|esta)\s+(el|la)?\s*(bitcoin|eth|crypto)',
        ],
        Intent.IP_INFO: [
            r'\b(mi ip|my ip|cual es mi ip|mi dirección ip|my ip address)\b',
            r'\b(ip publica|ip pública|public ip|external ip)\b',
        ],
        Intent.ANALYZE_IMAGE: [
            r'\b(?:qué|que) ves\b',
            r'\banaliza.*imagen\b',
            r'\bdescribe.*(?:imagen|foto)\b',
            r'\b(?:qué|que) hay en.*imagen\b',
        ],
        Intent.TAKE_PHOTO: [
            r'\btoma.*foto\b',
            r'\bcaptura.*imagen\b',
            r'\bsaca.*foto\b',
        ],
        Intent.READ_SCREEN: [
            r'\blee.*pantalla\b',
            r'\b(?:qué|que) dice.*pantalla\b',
            r'\bocr\b',
            r'\bextrae.*texto\b',
        ],
        Intent.WHAT_AM_I_HOLDING: [
            r'\b(?:qué|que) (?:estoy )?(?:sosteniendo|tengo)\b',
            r'\b(?:qué|que) (?:es )?esto\b',
            r'\b(?:qué|que) hay (?:en mi mano|aquí)\b',
        ],
        Intent.WHAT_DO_YOU_SEE: [
            r'\b(?:qué|que) ves\b',
            r'\bmírame\b',
            r'\b(?:qué|que) hay\b',
            r'\bdescribe\b',
        ],
        Intent.VISUAL_CONFIRMATION: [
            r'\b(?:así|ahi)\b\??',
            r'\bcorrecto\b\??',
            r'\b(?:está|esta) bien\b\??',
            r'\b(?:sí|si)\b\??',
            r'\b(?:exacto|perfecto)\b',
        ],
        Intent.START_SCREEN_WATCH: [
            r'\bempieza a ver\b',
            r'\bmonitorea.*(?:pantalla|escritorio)\b',
            r'\bobserva.*escritorio\b',
            r'\bve.*escritorio\b',
        ],
        Intent.STOP_SCREEN_WATCH: [
            r'\bdeja de ver\b',
            r'\bpara de (?:ver|monitorear)\b',
            r'\bdetente\b',
        ],
        Intent.WHAT_TO_DO: [
            r'\b(?:qué|que) (?:hago|tengo que hacer)\b',
            r'\b(?:cómo|como) (?:lo )?(?:arreglo|soluciono|fix)\b',
            r'\bqué debo hacer\b',
        ],
        Intent.IS_THIS_CORRECT: [
            r'\b(?:así|ahi) (?:está|esta) bien\b\??',
            r'\b(?:está|esta) correcto\b\??',
            r'\bestá bien (?:así|ahi)\b\??',
        ],
    }
    
    # Keywords that indicate need for web search
    WEB_SEARCH_KEYWORDS = [
        'últimas', 'latest', 'recientes', 'recent', 'actuales', 'current',
        'hoy', 'today', 'ayer', 'yesterday', 'esta semana', 'this week',
        'qué pasa', 'what\'s happening', 'noticias', 'news'
    ]
    
    def detect_intent(self, query: str) -> Tuple[Intent, float]:
        """
        Detect the primary intent from a user query.
        
        Returns:
            Tuple of (Intent, confidence_score)
        """
        query_lower = query.lower()
        
        # Check each intent pattern
        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    # Calculate confidence based on pattern specificity
                    confidence = 0.8 if re.search(pattern, query_lower, re.IGNORECASE) else 0.6
                    return (intent, confidence)
        
        return (Intent.UNKNOWN, 0.0)
    
    def detect_all_intents(self, query: str) -> List[Tuple[Intent, float]]:
        """
        Detect ALL intents in a query (for multi-intent queries).
        
        Example: "cual es el clima y quien es elon musk"
        Returns: [(WEATHER, 0.8), (BIOGRAPHY, 0.8)]
        """
        query_lower = query.lower()
        found_intents = []
        
        # Check each intent pattern
        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    confidence = 0.8
                    found_intents.append((intent, confidence))
                    break  # Only count each intent once
        
        # Return unique intents sorted by confidence
        return sorted(set(found_intents), key=lambda x: x[1], reverse=True)
    
    def needs_web_search(self, query: str) -> bool:
        """Check if query needs real-time web search."""
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in self.WEB_SEARCH_KEYWORDS)
    
    def extract_entity(self, query: str, intent: Intent) -> Optional[str]:
        """
        Extract the main entity/subject from query based on intent.
        NOW with better cleaning - removes query words.
        
        Examples:
            "quien es elon musk" -> "elon musk"
            "que clima es en san luis potosi" -> "san luis potosi"
            "receta de tacos" -> "tacos"
        """
        query_lower = query.lower()
        
        # Words to remove from extracted entity
        NOISE_WORDS = [
            'que', 'qué', 'cual', 'cuál', 'donde', 'dónde',
            'quien', 'quién', 'como', 'cómo', 'cuando', 'cuándo',
            'es', 'está', 'esta', 'en', 'de', 'el', 'la', 'los', 'las',
            'what', 'where', 'who', 'how', 'when', 'is', 'in', 'at', 'the',
            'clima', 'weather', 'temperatura', 'temperature',
        ]
        
        if intent == Intent.BIOGRAPHY:
            # Extract person name after "quien es", "who is", etc.
            patterns = [
                r'(?:quien es|quién es|who is|tell me about|háblame de)\s+(.+)',
                r'(?:biografía de|biography of)\s+(.+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    entity = match.group(1).strip()
                    # Clean noise words
                    entity_words = entity.split()
                    cleaned = ' '.join(w for w in entity_words if w not in NOISE_WORDS)
                    return cleaned or entity
        
        elif intent == Intent.WEATHER:
            # Extract city name - clean all weather-related words
            patterns = [
                r'(?:clima|weather|temperatura|temperature)\s+(?:en|in|de|of|es en|es|está en|esta en)\s+(.+)',
                r'(?:qué clima|what weather|que clima)\s+(?:hace|is|hay|está|esta)?\s*(?:en|in)?\s+(.+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    entity = match.group(1).strip()
                    # Clean noise words
                    entity_words = entity.split()
                    cleaned = ' '.join(w for w in entity_words if w not in NOISE_WORDS)
                    return cleaned or entity
        
        elif intent == Intent.COUNTRY_INFO:
            # Extract country name
            patterns = [
                r'(?:país|country|pais)\s+(.+)',
                r'(?:capital de|capital of|población de|population of)\s+(.+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    return match.group(1).strip()
        
        elif intent == Intent.BOOK_SEARCH:
            # Extract book title
            patterns = [
                r'libro\s+(.+)',
                r'book\s+(.+)',
                r'libro.*(?:sobre|de|llamado|called)\s+(.+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    return match.group(1).strip()
        
        elif intent == Intent.RECIPE:
            # Extract dish name
            patterns = [
                r'receta.*(?:de|para|of|for)\s+(.+)',
                r'cómo (?:cocinar|preparar|hacer|cook|make)\s+(.+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    return match.group(1).strip()
        
        elif intent == Intent.CRYPTO:
            # Extract crypto name
            patterns = [
                r'\b(bitcoin|btc|ethereum|eth)\b',
                r'(?:precio.*|cuanto.*)\b(bitcoin|eth|btc|ethereum)\b',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    return match.group(1).strip()
            return "bitcoin"  # Default
        
        # Return cleaned query if no specific entity found
        return query.strip()
    
    def extract_entity(self, query: str, intent: Intent) -> Optional[str]:
        """
        Extract the main entity/subject from query based on intent.
        
        Examples:
            "quien es elon musk" -> "elon musk"
            "clima en madrid" -> "madrid"
            "receta de tacos" -> "tacos"
        """
        query_lower = query.lower()
        
        if intent == Intent.BIOGRAPHY:
            # Extract person name after "quien es", "who is", etc.
            patterns = [
                r'(?:quien es|quién es|who is|tell me about|háblame de)\s+(.+)',
                r'(?:biografía de|biography of)\s+(.+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    return match.group(1).strip()
        
        elif intent == Intent.WEATHER:
            # Extract city name
            patterns = [
                r'(?:clima en|weather in|temperatura en|temperature in)\s+(.+)',
                r'(?:clima de|weather of)\s+(.+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    return match.group(1).strip()
        
        elif intent == Intent.COUNTRY_INFO:
            # Extract country name
            patterns = [
                r'(?:país|country|pais)\s+(.+)',
                r'(?:capital de|capital of|población de|population of)\s+(.+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    return match.group(1).strip()
        
        elif intent == Intent.BOOK_SEARCH:
            # Extract book title
            patterns = [
                r'libro.*(?:sobre|de|llamado|called)\s+(.+)',
                r'busca.*libro.*"([^"]+)"',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    return match.group(1).strip()
        
        elif intent == Intent.RECIPE:
            # Extract dish name
            patterns = [
                r'receta.*(?:de|para|of|for)\s+(.+)',
                r'cómo (?:cocinar|preparar|hacer|cook|make)\s+(.+)',
            ]
            for pattern in patterns:
                match = re.search(pattern, query_lower)
                if match:
                    return match.group(1).strip()
        
        # Return cleaned query if no specific entity found
        return query.strip()
    
    def should_auto_execute(self, intent: Intent, confidence: float) -> bool:
        """
        Determine if we should auto-execute API call without asking.
        
        Rules:
        - High confidence (>0.7) -> auto execute
        - Medium confidence (0.5-0.7) -> auto execute for safe intents
        - Low confidence (<0.5) -> don't auto execute
        """
        if confidence >= 0.7:
            return True
        
        if confidence >= 0.5:
            # Safe intents that can auto-execute even with medium confidence
            safe_intents = [
                Intent.WEATHER, Intent.DEFINITION, Intent.COUNTRY_INFO,
                Intent.TRIVIA, Intent.BIOGRAPHY
            ]
            return intent in safe_intents
        
        return False
    
    def get_api_action(self, intent: Intent) -> Optional[str]:
        """
        Map intent to specific API action/command.
        
        Returns the command name that should be executed.
        """
        intent_to_action = {
            Intent.BIOGRAPHY: 'wiki',
            Intent.WEATHER: 'clima',
            Intent.NEWS: 'search_web',
            Intent.DEFINITION: 'define',
            Intent.COUNTRY_INFO: 'pais',
            Intent.BOOK_SEARCH: 'libro',
            Intent.RECIPE: 'receta',
            Intent.GITHUB: 'github',
            Intent.STACKOVERFLOW: 'so',
            Intent.CRYPTO: 'crypto',
            Intent.IP_INFO: 'miip',
        }
        
        return intent_to_action.get(intent)
