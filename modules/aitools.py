"""
SAM v2.0 - AI Tools Module
Advanced AI features to maximize local Ollama usage:
- RAG (Retrieval Augmented Generation)
- Code Review/Explain
- Translation
- Summarization
- Model Benchmarking
- Model Presets
"""

import logging
import os
import time
import json
from typing import Dict, List
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


class AITools:
    """
    Advanced AI tools for maximizing local Ollama models.
    """
    
    # Presets storage
    PRESETS_FILE = Path.home() / ".config" / "sam" / "model_presets.json"
    
    # Supported document extensions for RAG
    RAG_EXTENSIONS = {'.txt', '.md', '.py', '.js', '.ts', '.php', '.html', '.css', 
                      '.json', '.yaml', '.yml', '.sh', '.sql', '.csv'}
    
    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url
        self.loaded_context = []  # RAG context
        self.presets = self._load_presets()
        
        # Ensure config dir exists
        self.PRESETS_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info("[Sam] AITools initialized")
    
    def _load_presets(self) -> Dict:
        """Load model presets from file"""
        if self.PRESETS_FILE.exists():
            try:
                with open(self.PRESETS_FILE, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {}
    
    def _save_presets(self):
        """Save presets to file"""
        with open(self.PRESETS_FILE, 'w') as f:
            json.dump(self.presets, f, indent=2)
    
    # ================================================================
    # RAG - RETRIEVAL AUGMENTED GENERATION
    # ================================================================
    
    def rag_load(self, filepath: str) -> Dict:
        """
        Load a document into RAG context.
        
        Args:
            filepath: Path to document to load
        """
        path = Path(filepath)
        
        if not path.exists():
            return {'success': False, 'error': f'File not found: {filepath}'}
        
        ext = path.suffix.lower()
        
        # Handle PDF (requires pypdf)
        if ext == '.pdf':
            try:
                from pypdf import PdfReader
                reader = PdfReader(filepath)
                content = ""
                for page in reader.pages[:20]:  # Max 20 pages
                    content += page.extract_text() + "\n"
            except ImportError:
                return {'success': False, 'error': 'pypdf not installed. Run: pip install pypdf'}
            except Exception as e:
                return {'success': False, 'error': f'PDF error: {e}'}
        
        elif ext in self.RAG_EXTENSIONS:
            try:
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except Exception as e:
                return {'success': False, 'error': str(e)}
        else:
            return {'success': False, 'error': f'Unsupported format: {ext}'}
        
        # Truncate if too long (keep ~8000 chars for context window)
        if len(content) > 8000:
            content = content[:8000] + "\n...[truncated]..."
        
        # Add to context
        self.loaded_context.append({
            'file': path.name,
            'path': str(path),
            'content': content,
            'loaded_at': datetime.now().isoformat()
        })
        
        return {
            'success': True,
            'file': path.name,
            'chars': len(content),
            'total_docs': len(self.loaded_context)
        }
    
    def rag_list(self) -> List[Dict]:
        """List loaded RAG documents"""
        return [{
            'file': doc['file'],
            'chars': len(doc['content']),
            'loaded_at': doc['loaded_at']
        } for doc in self.loaded_context]
    
    def rag_clear(self):
        """Clear all RAG context"""
        self.loaded_context = []
        return {'success': True, 'message': 'Context cleared'}
    
    def rag_get_context(self) -> str:
        """Get combined RAG context for AI prompt"""
        if not self.loaded_context:
            return ""
        
        context = "=== DOCUMENTOS CARGADOS ===\n\n"
        for doc in self.loaded_context:
            context += f"--- {doc['file']} ---\n{doc['content']}\n\n"
        context += "=== FIN DOCUMENTOS ===\n\n"
        return context
    
    # ================================================================
    # CODE REVIEW & EXPLAIN
    # ================================================================
    
    def review_code(self, filepath: str, model: str = "llama3.1:8b") -> Dict:
        """
        Perform AI code review on a file.
        
        Args:
            filepath: Path to code file
            model: Ollama model to use
        """
        if not os.path.exists(filepath):
            return {'success': False, 'error': 'File not found'}
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()
        except Exception as e:
            return {'success': False, 'error': str(e)}
        
        if len(code) > 10000:
            code = code[:10000] + "\n...[truncated]..."
        
        prompt = f"""Revisa el siguiente código y proporciona:
1. Problemas potenciales o bugs
2. Sugerencias de mejora
3. Buenas prácticas que faltan
4. Calificación general (1-10)

Sé conciso y directo.

Código ({Path(filepath).suffix}):
```
{code}
```"""
        
        result = self._ollama_generate(prompt, model)
        
        if result['success']:
            return {
                'success': True,
                'file': filepath,
                'review': result['response'],
                'model': model
            }
        return result
    
    def explain_code(self, filepath: str, model: str = "llama3.1:8b") -> Dict:
        """
        Explain what a code file does.
        
        Args:
            filepath: Path to code file
            model: Ollama model to use
        """
        if not os.path.exists(filepath):
            return {'success': False, 'error': 'File not found'}
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()
        except Exception as e:
            return {'success': False, 'error': str(e)}
        
        if len(code) > 8000:
            code = code[:8000] + "\n...[truncated]..."
        
        prompt = f"""Explica qué hace este código de manera clara y concisa:

1. Propósito general
2. Funciones/clases principales y qué hacen
3. Flujo de ejecución
4. Dependencias importantes

Código ({Path(filepath).suffix}):
```
{code}
```"""
        
        result = self._ollama_generate(prompt, model)
        
        if result['success']:
            return {
                'success': True,
                'file': filepath,
                'explanation': result['response'],
                'model': model
            }
        return result
    
    # ================================================================
    # TRANSLATION
    # ================================================================
    
    def translate(self, text: str, target_lang: str = "español", 
                  source_lang: str = "auto", model: str = "llama3.1:8b") -> Dict:
        """
        Translate text using local AI.
        
        Args:
            text: Text to translate
            target_lang: Target language
            source_lang: Source language or 'auto'
            model: Ollama model to use
        """
        if not text.strip():
            return {'success': False, 'error': 'No text provided'}
        
        prompt = f"""Traduce el siguiente texto a {target_lang}.
Solo responde con la traducción, sin explicaciones adicionales.

Texto a traducir:
{text}"""
        
        result = self._ollama_generate(prompt, model)
        
        if result['success']:
            return {
                'success': True,
                'original': text,
                'translated': result['response'].strip(),
                'target': target_lang,
                'model': model
            }
        return result
    
    # ================================================================
    # SUMMARIZATION
    # ================================================================
    
    def summarize(self, text: str, max_sentences: int = 3, 
                  model: str = "llama3.1:8b") -> Dict:
        """
        Summarize text using local AI.
        
        Args:
            text: Text to summarize
            max_sentences: Maximum sentences in summary
            model: Ollama model to use
        """
        if not text.strip():
            return {'success': False, 'error': 'No text provided'}
        
        prompt = f"""Resume el siguiente texto en máximo {max_sentences} oraciones.
Sé conciso y captura los puntos más importantes.

Texto:
{text}"""
        
        result = self._ollama_generate(prompt, model)
        
        if result['success']:
            return {
                'success': True,
                'summary': result['response'].strip(),
                'original_length': len(text),
                'model': model
            }
        return result
    
    def summarize_file(self, filepath: str, model: str = "llama3.1:8b") -> Dict:
        """Summarize a file's contents"""
        if not os.path.exists(filepath):
            return {'success': False, 'error': 'File not found'}
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        except Exception as e:
            return {'success': False, 'error': str(e)}
        
        if len(text) > 10000:
            text = text[:10000]
        
        return self.summarize(text, max_sentences=5, model=model)
    
    # ================================================================
    # MODEL BENCHMARKING
    # ================================================================
    
    def benchmark_model(self, model: str) -> Dict:
        """
        Benchmark a single Ollama model.
        
        Returns tokens/second and response time.
        """
        prompt = "Escribe un párrafo corto sobre inteligencia artificial."
        
        start = time.time()
        result = self._ollama_generate(prompt, model)
        elapsed = time.time() - start
        
        if result['success']:
            response = result['response']
            # Estimate tokens (~4 chars per token)
            tokens = len(response) / 4
            tokens_per_sec = tokens / elapsed if elapsed > 0 else 0
            
            return {
                'success': True,
                'model': model,
                'time_seconds': round(elapsed, 2),
                'tokens_approx': int(tokens),
                'tokens_per_sec': round(tokens_per_sec, 1),
                'response_length': len(response)
            }
        return {'success': False, 'model': model, 'error': result.get('error')}
    
    def benchmark_all(self, models: List[str] = None) -> List[Dict]:
        """
        Benchmark multiple models and compare.
        
        Args:
            models: List of model names, or None for all available
        """
        if not models:
            # Get available models from Ollama
            try:
                import requests
                response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    models = [m['name'] for m in data.get('models', [])][:5]  # Top 5
            except:
                return [{'success': False, 'error': 'Could not get model list'}]
        
        results = []
        for model in models:
            print(f"  Benchmarking {model}...")
            result = self.benchmark_model(model)
            results.append(result)
        
        # Sort by tokens/sec
        results.sort(key=lambda x: x.get('tokens_per_sec', 0), reverse=True)
        return results
    
    # ================================================================
    # MODEL PRESETS
    # ================================================================
    
    def preset_save(self, name: str, model: str, role: str = None, 
                    temperature: float = None) -> Dict:
        """
        Save a model preset.
        
        Args:
            name: Preset name
            model: Model to use
            role: Optional system role/prompt
            temperature: Optional temperature setting
        """
        self.presets[name] = {
            'model': model,
            'role': role,
            'temperature': temperature,
            'created': datetime.now().isoformat()
        }
        self._save_presets()
        
        return {'success': True, 'preset': name, 'model': model}
    
    def preset_load(self, name: str) -> Dict:
        """Load a preset by name"""
        if name not in self.presets:
            return {'success': False, 'error': f'Preset not found: {name}'}
        
        return {'success': True, 'preset': name, **self.presets[name]}
    
    def preset_list(self) -> List[Dict]:
        """List all saved presets"""
        return [{
            'name': name,
            'model': data['model'],
            'role': data.get('role', '')[:30] if data.get('role') else None
        } for name, data in self.presets.items()]
    
    def preset_delete(self, name: str) -> Dict:
        """Delete a preset"""
        if name in self.presets:
            del self.presets[name]
            self._save_presets()
            return {'success': True, 'deleted': name}
        return {'success': False, 'error': 'Preset not found'}
    
    # ================================================================
    # OLLAMA HELPERS
    # ================================================================
    
    def _ollama_generate(self, prompt: str, model: str) -> Dict:
        """Generate response from Ollama"""
        try:
            import requests
            
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    'model': model,
                    'prompt': prompt,
                    'stream': False
                },
                timeout=120
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'response': data.get('response', ''),
                    'model': model
                }
            else:
                return {'success': False, 'error': f'Ollama error: {response.status_code}'}
                
        except Exception as e:
            logger.error(f"[Sam] Ollama generate failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def list_models(self) -> List[str]:
        """Get list of available Ollama models"""
        try:
            import requests
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [m['name'] for m in data.get('models', [])]
        except:
            pass
        return []
    
    # ================================================================
    # VOICE TO TEXT (requires whisper)
    # ================================================================
    
    def transcribe_audio(self, audio_path: str) -> Dict:
        """
        Transcribe audio to text using Whisper.
        Requires: pip install openai-whisper
        
        Args:
            audio_path: Path to audio file (mp3, wav, etc.)
        """
        if not os.path.exists(audio_path):
            return {'success': False, 'error': 'Audio file not found'}
        
        try:
            import whisper
            
            # Load model (uses 'base' for speed, 'small' for better accuracy)
            model = whisper.load_model("base")
            result = model.transcribe(audio_path)
            
            return {
                'success': True,
                'text': result['text'],
                'language': result.get('language', 'unknown'),
                'file': audio_path
            }
            
        except ImportError:
            return {'success': False, 'error': 'Whisper not installed. Run: pip install openai-whisper'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
