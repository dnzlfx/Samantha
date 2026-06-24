#!/usr/bin/env python3
"""
Session Manager - Gestión de sesiones numeradas para Samantha
"""

import os
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple

LOG_DIR = str(Path.home() / ".samantha" / "sessions")


class SessionManager:
    """Gestiona el guardado y carga de sesiones numeradas"""
    
    def __init__(self, log_dir: str = LOG_DIR):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
    
    def get_next_session_number(self) -> int:
        """Obtiene el siguiente número de sesión disponible"""
        try:
            sessions = self._get_session_files()
            if not sessions:
                return 1
            
            # Extraer números de sesión de los archivos
            numbers = []
            for filename in sessions:
                if filename.startswith("session_") and filename.endswith(".md"):
                    try:
                        num_str = filename.replace("session_", "").replace(".md", "")
                        numbers.append(int(num_str))
                    except ValueError:
                        continue
            
            return max(numbers) + 1 if numbers else 1
        except:
            return 1
    
    def save_session_with_number(self, messages: List[Dict], modelo: str, count: int) -> Tuple[Optional[str], Optional[int]]:
        """
        Guarda una sesión con número consecutivo
        
        Returns:
            Tuple[filepath, session_number] o (None, None) si falla
        """
        try:
            session_num = self.get_next_session_number()
            filename = f"session_{session_num:03d}.md"
            filepath = os.path.join(self.log_dir, filename)
            
            # Guardar metadata en JSON
            metadata = {
                "session_number": session_num,
                "timestamp": datetime.now().isoformat(),
                "model": modelo,
                "message_count": count,
                "messages": messages
            }
            
            json_filepath = filepath.replace(".md", ".json")
            
            # Guardar formato markdown (para lectura humana)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# Samantha - Sesión #{session_num}\n")
                f.write(f"**Fecha**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"**Modelo**: {modelo}\n")
                f.write(f"**Mensajes**: {count}\n\n")
                f.write("---\n\n")
                
                for msg in messages[1:]:  # Skip system prompt
                    if msg['role'] == 'user':
                        f.write(f"\n## 👤 Usuario\n{msg['content']}\n")
                    elif msg['role'] == 'assistant':
                        f.write(f"\n## 🤖 Samantha\n{msg['content']}\n")
            
            # Guardar formato JSON (para carga programática)
            with open(json_filepath, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
            
            return filepath, session_num
        except Exception as e:
            print(f"Error guardando sesión: {e}")
            return None, None
    
    def list_available_sessions(self) -> List[Dict]:
        """
        Lista todas las sesiones disponibles con metadata
        
        Returns:
            Lista de diccionarios con info de cada sesión
        """
        sessions = []
        
        try:
            json_files = [f for f in os.listdir(self.log_dir) if f.startswith("session_") and f.endswith(".json")]
            json_files.sort()
            
            for filename in json_files:
                filepath = os.path.join(self.log_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                    
                    # Obtener preview del primer mensaje del usuario
                    preview = "Sin mensajes"
                    for msg in metadata.get('messages', [])[1:]:  # Skip system
                        if msg['role'] == 'user':
                            preview = msg['content'][:60] + "..." if len(msg['content']) > 60 else msg['content']
                            break
                    
                    sessions.append({
                        'number': metadata.get('session_number'),
                        'date': metadata.get('timestamp'),
                        'model': metadata.get('model'),
                        'message_count': metadata.get('message_count', 0),
                        'preview': preview
                    })
                except Exception as e:
                    continue
        except FileNotFoundError:
            pass
        
        return sessions
    
    def load_session_by_number(self, session_number: int) -> Optional[List[Dict]]:
        """
        Carga los mensajes de una sesión específica
        
        Args:
            session_number: Número de la sesión a cargar
        
        Returns:
            Lista de mensajes o None si no existe
        """
        try:
            filename = f"session_{session_number:03d}.json"
            filepath = os.path.join(self.log_dir, filename)
            
            if not os.path.exists(filepath):
                return None
            
            with open(filepath, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            return metadata.get('messages')
        except Exception as e:
            print(f"Error cargando sesión: {e}")
            return None
    
    def get_session_metadata(self, session_number: int) -> Optional[Dict]:
        """Obtiene metadata de una sesión sin cargar todos los mensajes"""
        try:
            filename = f"session_{session_number:03d}.json"
            filepath = os.path.join(self.log_dir, filename)
            
            if not os.path.exists(filepath):
                return None
            
            with open(filepath, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            # No devolver los mensajes, solo metadata
            return {
                'number': metadata.get('session_number'),
                'date': metadata.get('timestamp'),
                'model': metadata.get('model'),
                'message_count': metadata.get('message_count', 0)
            }
        except:
            return None
    
    def _get_session_files(self) -> List[str]:
        """Obtiene lista de archivos de sesión"""
        try:
            return [f for f in os.listdir(self.log_dir) if f.startswith("session_")]
        except FileNotFoundError:
            return []


# Funciones de conveniencia para compatibilidad
def get_next_session_number() -> int:
    """Obtiene el siguiente número de sesión"""
    manager = SessionManager()
    return manager.get_next_session_number()


def save_session_with_number(messages: List[Dict], modelo: str, count: int) -> Tuple[Optional[str], Optional[int]]:
    """Guarda sesión con número"""
    manager = SessionManager()
    return manager.save_session_with_number(messages, modelo, count)


def list_available_sessions() -> List[Dict]:
    """Lista sesiones disponibles"""
    manager = SessionManager()
    return manager.list_available_sessions()


def load_session_by_number(session_number: int) -> Optional[List[Dict]]:
    """Carga sesión por número"""
    manager = SessionManager()
    return manager.load_session_by_number(session_number)
