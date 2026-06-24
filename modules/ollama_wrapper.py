#!/usr/bin/env python3
"""
Ollama Wrapper with OpenAI Support
Transparently routes to OpenAI for GPT models, Ollama for others
"""

import os
from typing import Iterator, Dict, List

# Import real ollama
import ollama as _ollama


def chat(model: str, messages: List[Dict], stream: bool = True, **kwargs) -> Iterator[Dict]:
    """
    Chat function that routes to appropriate provider
    
    Args:
        model: Model name (gpt-4 → OpenAI, others → Ollama)
        messages: Chat messages
        stream: Stream response
        
    Yields:
        Response chunks in ollama format
    """
    model_lower = model.lower()
    
    # Detect if OpenAI model (GPT or Codex)
    if any(x in model_lower for x in ['gpt-', 'gpt4', 'gpt3', 'gpt5', 'turbo', 'codex']):
        # Route to OpenAI
        try:
            from openai import OpenAI
            
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                print("[OpenAI] ⚠️ No API key - set OPENAI_API_KEY in .env")
                print("[OpenAI] Falling back to Ollama")
                # Fallback to ollama
                for chunk in _ollama.chat(model=model, messages=messages, stream=stream, **kwargs):
                    yield chunk
                return
            
            client = OpenAI(api_key=api_key)
            
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=stream
            )
            
            if stream:
                for chunk in response:
                    content = chunk.choices[0].delta.content if chunk.choices[0].delta.content else ''
                    # Convert to ollama format
                    yield {
                        'message': {'content': content},
                        'done': chunk.choices[0].finish_reason is not None
                    }
            else:
                yield {
                    'message': {'content': response.choices[0].message.content},
                    'done': True
                }
                
        except Exception as e:
            print(f"[OpenAI] Error: {e}")
            print("[OpenAI] Falling back to Ollama")
            # Fallback to ollama
            for chunk in _ollama.chat(model=model, messages=messages, stream=stream, **kwargs):
                yield chunk
    else:
        # Use Ollama
        for chunk in _ollama.chat(model=model, messages=messages, stream=stream, **kwargs):
            yield chunk


def list() -> Dict:
    """
    List available models from both providers
    """
    result = {'models': []}
    
    # Get Ollama models
    try:
        ollama_models = _ollama.list()
        
        # Convert Model objects to dicts if needed
        if hasattr(ollama_models, 'models'):
            for model in ollama_models.models:
                result['models'].append({
                    'name': model.model,
                    'size': model.size
                })
        elif isinstance(ollama_models, dict) and 'models' in ollama_models:
            result['models'].extend(ollama_models['models'])
            
    except Exception as e:
        print(f"[Ollama] Error listing models: {e}")
    
    # Always show OpenAI models (with status)
    has_api_key = bool(os.getenv('OPENAI_API_KEY'))
    status = '' if (has_api_key and os.getenv('OPENAI_API_KEY') != 'your-api-key-here') else ' [needs API key]'
    
    openai_models = [
        {'name': f'gpt-5-codex{status}', 'size': 0},
        {'name': f'gpt-5-codex-mini{status}', 'size': 0},
        {'name': f'gpt-4{status}', 'size': 0},
        {'name': f'gpt-4-turbo{status}', 'size': 0},
        {'name': f'gpt-3.5-turbo{status}', 'size': 0},
    ]
    result['models'].extend(openai_models)
    
    return result


def pull(model: str, **kwargs):
    """Pull model - only works for Ollama"""
    return _ollama.pull(model, **kwargs)


def push(model: str, **kwargs):
    """Push model - only works for Ollama"""
    return _ollama.push(model, **kwargs)


def delete(model: str, **kwargs):
    """Delete model - only works for Ollama"""
    return _ollama.delete(model, **kwargs)


def show(model: str, **kwargs):
    """Show model info - only works for Ollama"""
    return _ollama.show(model, **kwargs)


# Export all ollama functions
__all__ = ['chat', 'list', 'pull', 'push', 'delete', 'show']
