"""
Samantha memory manager.
Long-term memory using SQLite for conversation history and learned patterns.
"""

import logging
import sqlite3
from typing import Dict, List, Optional
from datetime import datetime
import json
from pathlib import Path

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Manages long-term memory storage for Samantha using SQLite.
    Stores conversations, learned patterns, and user preferences.
    """
    
    DB_PATH = str(Path.home() / ".samantha" / "sam_brain.db")
    
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or self.DB_PATH
        self._ensure_db_directory()
        self.connection = None
        self.initialize_database()
    
    def _ensure_db_directory(self):
        """Ensures database directory exists"""
        db_dir = Path(self.db_path).parent
        db_dir.mkdir(parents=True, exist_ok=True)
    
    def initialize_database(self):
        """Creates database tables if they don't exist"""
        try:
            self.connection = sqlite3.connect(self.db_path)
            cursor = self.connection.cursor()
            
            # Conversations table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    user_input TEXT NOT NULL,
                    assistant_response TEXT NOT NULL,
                    model_used TEXT,
                    context_type TEXT,
                    intent TEXT
                )
            ''')
            
            # Learned patterns table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS learned_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_type TEXT NOT NULL,
                    pattern_data JSON NOT NULL,
                    frequency INTEGER DEFAULT 1,
                    last_used DATETIME DEFAULT CURRENT_TIMESTAMP,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # User preferences table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    preference_key TEXT UNIQUE NOT NULL,
                    preference_value TEXT NOT NULL,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes for faster queries
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_conversations_timestamp 
                ON conversations(timestamp)
            ''')
            
            cursor.execute('''
                CREATE INDEX IF NOT EXISTS idx_learned_patterns_type 
                ON learned_patterns(pattern_type)
            ''')
            
            self.connection.commit()
            logger.info(f"[Sam] Database initialized: {self.db_path}")
            
        except Exception as e:
            logger.error(f"[Sam] Database initialization failed: {e}")
    
    def log_conversation(
        self,
        user_input: str,
        assistant_response: str,
        model_used: str,
        context_type: str = "general",
        intent: str = "general"
    ):
        """
        Logs a conversation exchange.
        
        Args:
            user_input: User's input
            assistant_response: Sam's response
            model_used: Which model generated the response
            context_type: Type of conversation
            intent: Detected intent
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                INSERT INTO conversations 
                (user_input, assistant_response, model_used, context_type, intent)
                VALUES (?, ?, ?, ?, ?)
            ''', (user_input, assistant_response, model_used, context_type, intent))
            
            self.connection.commit()
            
        except Exception as e:
            logger.error(f"[Sam] Failed to log conversation: {e}")
    
    def get_recent_conversations(self, limit: int = 10) -> List[Dict]:
        """
        Retrieves recent conversation history.
        
        Args:
            limit: Maximum number of conversations to retrieve
            
        Returns:
            List of conversation dicts
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                SELECT id, timestamp, user_input, assistant_response, 
                       model_used, context_type, intent
                FROM conversations
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            
            conversations = []
            for row in rows:
                conversations.append({
                    'id': row[0],
                    'timestamp': row[1],
                    'user_input': row[2],
                    'assistant_response': row[3],
                    'model_used': row[4],
                    'context_type': row[5],
                    'intent': row[6]
                })
            
            return conversations
            
        except Exception as e:
            logger.error(f"[Sam] Failed to retrieve conversations: {e}")
            return []
    
    def search_conversations(self, query: str, limit: int = 5) -> List[Dict]:
        """
        Searches conversation history for relevant context.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of matching conversations
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                SELECT id, timestamp, user_input, assistant_response, 
                       model_used, context_type, intent
                FROM conversations
                WHERE user_input LIKE ? OR assistant_response LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (f'%{query}%', f'%{query}%', limit))
            
            rows = cursor.fetchall()
            
            results = []
            for row in rows:
                results.append({
                    'id': row[0],
                    'timestamp': row[1],
                    'user_input': row[2],
                    'assistant_response': row[3],
                    'model_used': row[4],
                    'context_type': row[5],
                    'intent': row[6]
                })
            
            return results
            
        except Exception as e:
            logger.error(f"[Sam] Conversation search failed: {e}")
            return []
    
    def learn_pattern(self, pattern_type: str, pattern_data: Dict):
        """
        Stores or updates a learned pattern.
        
        Args:
            pattern_type: Type of pattern (e.g., "common_query", "preferred_model")
            pattern_data: Pattern data as dict
        """
        try:
            cursor = self.connection.cursor()
            pattern_json = json.dumps(pattern_data)
            
            # Check if pattern exists
            cursor.execute('''
                SELECT id, frequency FROM learned_patterns
                WHERE pattern_type = ? AND pattern_data = ?
            ''', (pattern_type, pattern_json))
            
            existing = cursor.fetchone()
            
            if existing:
                # Update frequency and last_used
                cursor.execute('''
                    UPDATE learned_patterns
                    SET frequency = frequency + 1,
                        last_used = CURRENT_TIMESTAMP
                    WHERE id = ?
                ''', (existing[0],))
            else:
                # Insert new pattern
                cursor.execute('''
                    INSERT INTO learned_patterns (pattern_type, pattern_data)
                    VALUES (?, ?)
                ''', (pattern_type, pattern_json))
            
            self.connection.commit()
            
        except Exception as e:
            logger.error(f"[Sam] Failed to learn pattern: {e}")
    
    def get_patterns(self, pattern_type: str, limit: int = 10) -> List[Dict]:
        """
        Retrieves learned patterns of a specific type.
        
        Args:
            pattern_type: Type of patterns to retrieve
            limit: Maximum number of patterns
            
        Returns:
            List of pattern dicts
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                SELECT id, pattern_data, frequency, last_used
                FROM learned_patterns
                WHERE pattern_type = ?
                ORDER BY frequency DESC, last_used DESC
                LIMIT ?
            ''', (pattern_type, limit))
            
            rows = cursor.fetchall()
            
            patterns = []
            for row in rows:
                patterns.append({
                    'id': row[0],
                    'data': json.loads(row[1]),
                    'frequency': row[2],
                    'last_used': row[3]
                })
            
            return patterns
            
        except Exception as e:
            logger.error(f"[Sam] Failed to retrieve patterns: {e}")
            return []
    
    def set_preference(self, key: str, value: str):
        """
        Sets a user preference.
        
        Args:
            key: Preference key
            value: Preference value
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_preferences (preference_key, preference_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
            ''', (key, value))
            
            self.connection.commit()
            
        except Exception as e:
            logger.error(f"[Sam] Failed to set preference: {e}")
    
    def get_preference(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Gets a user preference.
        
        Args:
            key: Preference key
            default: Default value if not found
            
        Returns:
            Preference value or default
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                SELECT preference_value FROM user_preferences
                WHERE preference_key = ?
            ''', (key,))
            
            result = cursor.fetchone()
            return result[0] if result else default
            
        except Exception as e:
            logger.error(f"[Sam] Failed to get preference: {e}")
            return default
    
    # ================================================================
    # USER LEARNING SYSTEM
    # ================================================================
    
    def ensure_aliases_table(self):
        """Creates aliases table if it doesn't exist"""
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alias TEXT UNIQUE NOT NULL,
                    value TEXT NOT NULL,
                    alias_type TEXT DEFAULT 'text',
                    usage_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_used DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.connection.commit()
        except Exception as e:
            logger.error(f"[Sam] Failed to create aliases table: {e}")
    
    def learn_alias(self, alias: str, value: str, alias_type: str = "text") -> bool:
        """
        Learns a new alias or updates existing one.
        
        Args:
            alias: The trigger word/phrase
            value: What it expands to
            alias_type: 'text', 'command', or 'project'
        
        Returns:
            True if successful
        """
        self.ensure_aliases_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_aliases (alias, value, alias_type, usage_count, last_used)
                VALUES (?, ?, ?, COALESCE((SELECT usage_count FROM user_aliases WHERE alias = ?), 0), CURRENT_TIMESTAMP)
            ''', (alias.lower(), value, alias_type, alias.lower()))
            self.connection.commit()
            logger.info(f"[Sam] Learned alias: {alias} → {value[:50]}...")
            return True
        except Exception as e:
            logger.error(f"[Sam] Failed to learn alias: {e}")
            return False
    
    def forget_alias(self, alias: str) -> bool:
        """
        Forgets/removes an alias.
        
        Args:
            alias: The alias to remove
            
        Returns:
            True if removed, False if not found
        """
        self.ensure_aliases_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('DELETE FROM user_aliases WHERE alias = ?', (alias.lower(),))
            self.connection.commit()
            return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"[Sam] Failed to forget alias: {e}")
            return False
    
    def get_alias(self, alias: str) -> Optional[str]:
        """
        Gets value for an alias and increments usage count.
        
        Args:
            alias: The alias to look up
            
        Returns:
            The value or None
        """
        self.ensure_aliases_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('SELECT value FROM user_aliases WHERE alias = ?', (alias.lower(),))
            result = cursor.fetchone()
            if result:
                # Increment usage
                cursor.execute('''
                    UPDATE user_aliases SET usage_count = usage_count + 1, last_used = CURRENT_TIMESTAMP
                    WHERE alias = ?
                ''', (alias.lower(),))
                self.connection.commit()
                return result[0]
            return None
        except Exception as e:
            logger.error(f"[Sam] Failed to get alias: {e}")
            return None
    
    def get_all_aliases(self) -> List[Dict]:
        """
        Gets all learned aliases.
        
        Returns:
            List of alias dicts
        """
        self.ensure_aliases_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                SELECT alias, value, alias_type, usage_count, created_at, last_used
                FROM user_aliases
                ORDER BY usage_count DESC, last_used DESC
            ''')
            
            aliases = []
            for row in cursor.fetchall():
                aliases.append({
                    'alias': row[0],
                    'value': row[1],
                    'type': row[2],
                    'usage_count': row[3],
                    'created_at': row[4],
                    'last_used': row[5]
                })
            return aliases
        except Exception as e:
            logger.error(f"[Sam] Failed to get aliases: {e}")
            return []
    
    def expand_aliases(self, text: str) -> str:
        """
        Expands all known aliases in text.
        
        Args:
            text: Text to process
            
        Returns:
            Text with aliases expanded
        """
        self.ensure_aliases_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('SELECT alias, value FROM user_aliases ORDER BY LENGTH(alias) DESC')
            
            expanded = text
            for alias, value in cursor.fetchall():
                # Case-insensitive word boundary replacement
                import re
                pattern = r'\b' + re.escape(alias) + r'\b'
                if re.search(pattern, expanded, re.IGNORECASE):
                    expanded = re.sub(pattern, value, expanded, flags=re.IGNORECASE)
                    # Update usage count
                    cursor.execute('''
                        UPDATE user_aliases SET usage_count = usage_count + 1, last_used = CURRENT_TIMESTAMP
                        WHERE alias = ?
                    ''', (alias,))
            
            self.connection.commit()
            return expanded
        except Exception as e:
            logger.error(f"[Sam] Failed to expand aliases: {e}")
            return text
    # ================================================================
    # NOTES / KNOWLEDGE BASE
    # ================================================================
    
    def ensure_notes_table(self):
        """Creates notes table if it doesn't exist"""
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT DEFAULT 'general',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.connection.commit()
        except Exception as e:
            logger.error(f"[Sam] Failed to create notes table: {e}")
    
    def save_note(self, name: str, content: str, category: str = "general") -> bool:
        """Save or update a note"""
        self.ensure_notes_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO notes (name, content, category, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ''', (name.lower(), content, category))
            self.connection.commit()
            return True
        except Exception as e:
            logger.error(f"[Sam] Failed to save note: {e}")
            return False
    
    def get_note(self, name: str) -> Optional[str]:
        """Get a note by name"""
        self.ensure_notes_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('SELECT content FROM notes WHERE name = ?', (name.lower(),))
            result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(f"[Sam] Failed to get note: {e}")
            return None
    
    def delete_note(self, name: str) -> bool:
        """Delete a note"""
        self.ensure_notes_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('DELETE FROM notes WHERE name = ?', (name.lower(),))
            self.connection.commit()
            return cursor.rowcount > 0
        except:
            return False
    
    def list_notes(self, category: str = None) -> List[Dict]:
        """List all notes"""
        self.ensure_notes_table()
        try:
            cursor = self.connection.cursor()
            if category:
                cursor.execute('SELECT name, category, updated_at FROM notes WHERE category = ? ORDER BY updated_at DESC', (category,))
            else:
                cursor.execute('SELECT name, category, updated_at FROM notes ORDER BY updated_at DESC')
            return [{'name': r[0], 'category': r[1], 'updated': r[2]} for r in cursor.fetchall()]
        except:
            return []
    
    # ================================================================
    # QUICK SCRIPTS
    # ================================================================
    
    def ensure_scripts_table(self):
        """Creates scripts table"""
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS scripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    commands TEXT NOT NULL,
                    description TEXT,
                    run_count INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.connection.commit()
        except Exception as e:
            logger.error(f"[Sam] Failed to create scripts table: {e}")
    
    def save_script(self, name: str, commands: str, description: str = "") -> bool:
        """Save a quick script"""
        self.ensure_scripts_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO scripts (name, commands, description)
                VALUES (?, ?, ?)
            ''', (name.lower(), commands, description))
            self.connection.commit()
            return True
        except:
            return False
    
    def get_script(self, name: str) -> Optional[str]:
        """Get script commands"""
        self.ensure_scripts_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('SELECT commands FROM scripts WHERE name = ?', (name.lower(),))
            result = cursor.fetchone()
            if result:
                cursor.execute('UPDATE scripts SET run_count = run_count + 1 WHERE name = ?', (name.lower(),))
                self.connection.commit()
                return result[0]
            return None
        except:
            return None
    
    def delete_script(self, name: str) -> bool:
        """Delete a script"""
        self.ensure_scripts_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('DELETE FROM scripts WHERE name = ?', (name.lower(),))
            self.connection.commit()
            return cursor.rowcount > 0
        except:
            return False
    
    def list_scripts(self) -> List[Dict]:
        """List all scripts"""
        self.ensure_scripts_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('SELECT name, description, run_count FROM scripts ORDER BY run_count DESC')
            return [{'name': r[0], 'desc': r[1], 'runs': r[2]} for r in cursor.fetchall()]
        except:
            return []
    
    # ================================================================
    # REMINDERS / SCHEDULED TASKS
    # ================================================================
    
    def ensure_reminders_table(self):
        """Creates reminders table"""
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message TEXT NOT NULL,
                    trigger_time DATETIME NOT NULL,
                    completed INTEGER DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            self.connection.commit()
        except Exception as e:
            logger.error(f"[Sam] Failed to create reminders table: {e}")
    
    def add_reminder(self, message: str, trigger_time) -> bool:
        """Add a reminder"""
        self.ensure_reminders_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                INSERT INTO reminders (message, trigger_time)
                VALUES (?, ?)
            ''', (message, trigger_time.isoformat() if hasattr(trigger_time, 'isoformat') else trigger_time))
            self.connection.commit()
            return True
        except Exception as e:
            logger.error(f"[Sam] Failed to add reminder: {e}")
            return False
    
    def get_pending_reminders(self) -> List[Dict]:
        """Get reminders that are due"""
        self.ensure_reminders_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                SELECT id, message, trigger_time FROM reminders
                WHERE completed = 0 AND trigger_time <= datetime('now', 'localtime')
                ORDER BY trigger_time
            ''')
            return [{'id': r[0], 'message': r[1], 'time': r[2]} for r in cursor.fetchall()]
        except:
            return []
    
    def complete_reminder(self, reminder_id: int) -> bool:
        """Mark reminder as completed"""
        self.ensure_reminders_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('UPDATE reminders SET completed = 1 WHERE id = ?', (reminder_id,))
            self.connection.commit()
            return True
        except:
            return False
    
    def list_reminders(self) -> List[Dict]:
        """List upcoming reminders"""
        self.ensure_reminders_table()
        try:
            cursor = self.connection.cursor()
            cursor.execute('''
                SELECT id, message, trigger_time FROM reminders
                WHERE completed = 0
                ORDER BY trigger_time
                LIMIT 10
            ''')
            return [{'id': r[0], 'message': r[1], 'time': r[2]} for r in cursor.fetchall()]
        except:
            return []
    
    def close(self):
        """Closes database connection"""
        if self.connection:
            self.connection.close()
            logger.info("[Sam] Database connection closed")
