#!/usr/bin/env python3
"""
LLM Provider Abstraction
Supports multiple LLM providers: Ollama (local) and OpenAI (cloud)
"""

import os
import logging
from typing import Iterator, Dict, List, Optional
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base class for LLM providers"""
    
    @abstractmethod
    def chat(self, messages: List[Dict], model: str, stream: bool = True) -> Iterator[Dict]:
        """
        Send chat messages and get response
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model name
            stream: Whether to stream response
            
        Yields:
            Response chunks
        """
        pass
    
    @abstractmethod
    def list_models(self) -> List[str]:
        """List available models"""
        pass


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider"""
    
    def __init__(self):
        try:
            import ollama
            self.ollama = ollama
            logger.info("[Ollama] Provider initialized")
        except ImportError:
            logger.error("[Ollama] Package not installed")
            raise
    
    def chat(self, messages: List[Dict], model: str, stream: bool = True) -> Iterator[Dict]:
        """Chat with Ollama model"""
        try:
            for chunk in self.ollama.chat(model=model, messages=messages, stream=stream):
                # Normalize format
                yield {
                    'provider': 'ollama',
                    'content': chunk.get('message', {}).get('content', ''),
                    'done': chunk.get('done', False)
                }
        except Exception as e:
            logger.error(f"[Ollama] Chat error: {e}")
            raise
    
    def list_models(self) -> List[str]:
        """List Ollama models"""
        try:
            models = self.ollama.list()
            return [m['name'] for m in models.get('models', [])]
        except Exception as e:
            logger.error(f"[Ollama] List models error: {e}")
            return []


class OpenAIProvider(LLMProvider):
    """OpenAI cloud LLM provider"""
    
    def __init__(self, api_key: Optional[str] = None):
        try:
            from openai import OpenAI
            
            # Get API key from parameter or environment
            self.api_key = api_key or os.getenv('OPENAI_API_KEY')
            
            if not self.api_key:
                raise ValueError("OpenAI API key not found. Set OPENAI_API_KEY environment variable.")
            
            self.client = OpenAI(api_key=self.api_key)
            logger.info("[OpenAI] Provider initialized")
            
        except ImportError:
            logger.error("[OpenAI] Package not installed. Run: pip install openai")
            raise
        except Exception as e:
            logger.error(f"[OpenAI] Initialization error: {e}")
            raise
    
    def chat(self, messages: List[Dict], model: str, stream: bool = True) -> Iterator[Dict]:
        """Chat with OpenAI model"""
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=stream
            )
            
            if stream:
                for chunk in response:
                    content = chunk.choices[0].delta.content if chunk.choices[0].delta.content else ''
                    yield {
                        'provider': 'openai',
                        'content': content,
                        'done': chunk.choices[0].finish_reason is not None
                    }
            else:
                yield {
                    'provider': 'openai',
                    'content': response.choices[0].message.content,
                    'done': True
                }
                
        except Exception as e:
            logger.error(f"[OpenAI] Chat error: {e}")
            raise
    
    def list_models(self) -> List[str]:
        """List common OpenAI models"""
        # OpenAI doesn't provide easy model listing, so we return common ones
        return [
            'gpt-4',
            'gpt-4-turbo',
            'gpt-4-turbo-preview',
            'gpt-3.5-turbo',
            'gpt-3.5-turbo-16k',
        ]


class LLMManager:
    """Manages multiple LLM providers and routes requests"""
    
    def __init__(self):
        self.providers = {}
        
        # Initialize Ollama (always available)
        try:
            self.providers['ollama'] = OllamaProvider()
        except Exception as e:
            logger.warning(f"[LLMManager] Ollama not available: {e}")
        
        # Initialize OpenAI (if API key available)
        try:
            self.providers['openai'] = OpenAIProvider()
        except Exception as e:
            logger.info(f"[LLMManager] OpenAI not available: {e}")
    
    def detect_provider(self, model: str) -> str:
        """
        Detect which provider to use based on model name
        
        Args:
            model: Model name
            
        Returns:
            Provider name ('ollama' or 'openai')
        """
        model_lower = model.lower()
        
        # OpenAI models
        if any(x in model_lower for x in ['gpt-', 'gpt4', 'gpt3', 'turbo']):
            return 'openai'
        
        # Default to Ollama
        return 'ollama'
    
    def chat(self, messages: List[Dict], model: str, stream: bool = True) -> Iterator[Dict]:
        """
        Chat with appropriate provider
        
        Args:
            messages: Chat messages
            model: Model name
            stream: Stream response
            
        Yields:
            Response chunks
        """
        provider_name = self.detect_provider(model)
        
        if provider_name not in self.providers:
            raise ValueError(f"Provider '{provider_name}' not available for model '{model}'")
        
        provider = self.providers[provider_name]
        
        logger.info(f"[LLMManager] Using {provider_name} for model {model}")
        
        for chunk in provider.chat(messages, model, stream):
            yield chunk
    
    def list_all_models(self) -> Dict[str, List[str]]:
        """List models from all providers"""
        all_models = {}
        
        for name, provider in self.providers.items():
            try:
                all_models[name] = provider.list_models()
            except Exception as e:
                logger.error(f"[LLMManager] Error listing {name} models: {e}")
                all_models[name] = []
        
        return all_models


# Convenience functions
def create_llm_manager() -> LLMManager:
    """Create and return LLM manager"""
    return LLMManager()


if __name__ == "__main__":
    # Test
    manager = create_llm_manager()
    
    print("Available models:")
    for provider, models in manager.list_all_models().items():
        print(f"\n{provider.upper()}:")
        for model in models:
            print(f"  - {model}")
