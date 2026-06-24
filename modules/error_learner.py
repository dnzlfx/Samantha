#!/usr/bin/env python3
"""
Error Learning System - Analyzes failures and suggests improvements
Builds knowledge base of common errors and solutions
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from collections import Counter
import logging

logger = logging.getLogger(__name__)


class ErrorLearner:
    """
    Learns from errors to prevent repetition.
    Builds knowledge of error patterns and fixes.
    """
    
    def __init__(self, llm_chat_function, db_path: str = None):
        """
        Initialize error learner.
        
        Args:
            llm_chat_function: LLM for analyzing errors
            db_path: Path to knowledge database
        """
        self.llm_chat = llm_chat_function
        
        if db_path is None:
            brain_dir = Path.home() / '.samantha' / 'brain'
            brain_dir.mkdir(parents=True, exist_ok=True)
            db_path = brain_dir / 'error_knowledge.db'
        
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Create knowledge base schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS error_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_type TEXT,
                error_pattern TEXT UNIQUE,
                frequency INTEGER DEFAULT 1,
                fixes_json TEXT,
                prevention_tips TEXT,
                last_seen TEXT,
                resolved_count INTEGER DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS learnings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT,
                insight TEXT,
                confidence REAL DEFAULT 0.5,
                usage_count INTEGER DEFAULT 0,
                success_rate REAL DEFAULT 0,
                created TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def analyze_failure(self, task: str, error: str, context: Dict = None) -> Dict:
        """
        Analyze why a task failed using LLM.
        
        Args:
            task: The failed task
            error: Error message
            context: Additional context
            
        Returns:
            Analysis dict with insights
        """
        context_str = ""
        if context:
            if 'steps' in context:
                context_str += f"\nSteps attempted: {len(context['steps'])}"
            if 'model' in context:
                context_str += f"\nModel: {context['model']}"
        
        prompt = f"""Analyze this error:

Task: {task}
Error: {error}{context_str}

Provide concise analysis:
1. Root cause?
2. How to fix?
3. How to prevent future?

Be brief and actionable."""

        try:
            response = self.llm_chat(
                model='llama3.1:8b',
                messages=[{"role": "user", "content": prompt}],
                stream=False
            )
            
            analysis = response.get('message', {}).get('content', '')
            
            # Store in knowledge base
            self._store_error_pattern(error, analysis)
            
            return {
                'error': error,
                'analysis': analysis,
                'stored': True
            }
            
        except Exception as e:
            logger.error(f"[ErrorLearner] Failed to analyze: {e}")
            return {
                'error': error,
                'analysis': 'Could not analyze',
                'stored': False
            }
    
    def _store_error_pattern(self, error: str, analysis: str):
        """Store error pattern in knowledge base"""
        # Simplify error to pattern (remove specific values)
        pattern = self._extract_pattern(error)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO error_patterns (error_pattern, error_type, fixes_json, last_seen)
                VALUES (?, ?, ?, ?)
            ''', (pattern, self._classify_error(error),
                  json.dumps([analysis]), datetime.now().isoformat()))
            
            conn.commit()
            logger.info(f"[ErrorLearner] Stored new pattern: {pattern[:50]}...")
            
        except sqlite3.IntegrityError:
            # Pattern exists, update frequency
            cursor.execute('''
                UPDATE error_patterns SET
                    frequency = frequency + 1,
                    last_seen = ?
                WHERE error_pattern = ?
            ''', (datetime.now().isoformat(), pattern))
            
            conn.commit()
            logger.info(f"[ErrorLearner] Updated pattern frequency: {pattern[:50]}...")
        
        finally:
            conn.close()
    
    def _extract_pattern(self, error: str) -> str:
        """Extract generic pattern from specific error"""
        # Remove file paths
        import re
        pattern = re.sub(r'/[\w/]+\.[\w]+', '/PATH/FILE', error)
        # Remove numbers
        pattern = re.sub(r'\d+', 'N', pattern)
        # Remove quotes content
        pattern = re.sub(r'"[^"]*"', '"..."', pattern)
        return pattern[:200]  # Limit length
    
    def _classify_error(self, error: str) -> str:
        """Classify error type"""
        error_lower = error.lower()
        
        if 'file' in error_lower or 'path' in error_lower:
            return 'file_error'
        elif 'memory' in error_lower or 'ram' in error_lower:
            return 'memory_error'
        elif 'syntax' in error_lower:
            return 'syntax_error'
        elif 'import' in error_lower or 'module' in error_lower:
            return 'import_error'
        elif 'permission' in error_lower:
            return 'permission_error'
        else:
            return 'general_error'
    
    def suggest_fix(self, error: str) -> Optional[str]:
        """
        Suggest fix based on known patterns.
        
        Args:
            error: Error message
            
        Returns:
            Suggested fix or None
        """
        pattern = self._extract_pattern(error)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT fixes_json, frequency
            FROM error_patterns
            WHERE error_pattern = ?
        ''', (pattern,))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            fixes = json.loads(row[0])
            frequency = row[1]
            return {
                'fix': fixes[0] if fixes else "No fix recorded",
                'seen_before': frequency,
                'confidence': min(frequency / 5.0, 1.0)  # Max confidence at 5 occurrences
            }
        
        return None
    
    def get_common_errors(self, limit: int = 10) -> List[Dict]:
        """Get most common error patterns"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT error_type, error_pattern, frequency, fixes_json
            FROM error_patterns
            ORDER BY frequency DESC
            LIMIT ?
        ''', (limit,))
        
        errors = []
        for row in cursor.fetchall():
            fixes = json.loads(row[3])
            errors.append({
                'type': row[0],
                'pattern': row[1],
                'frequency': row[2],
                'fix': fixes[0] if fixes else "Unknown"
            })
        
        conn.close()
        return errors
    
    def add_learning(self, category: str, insight: str, confidence: float = 0.5):
        """Add a general learning to knowledge base"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO learnings (category, insight, confidence, created)
            VALUES (?, ?, ?, ?)
        ''', (category, insight, confidence, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        logger.info(f"[ErrorLearner] Added learning: {insight[:50]}...")
    
    def get_learnings(self, category: str = None) -> List[Dict]:
        """Retrieve learnings"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if category:
            cursor.execute('''
                SELECT insight, confidence, usage_count
                FROM learnings WHERE category = ?
                ORDER BY confidence DESC, usage_count DESC
            ''', (category,))
        else:
            cursor.execute('''
                SELECT category, insight, confidence, usage_count
                FROM learnings
                ORDER BY confidence DESC, usage_count DESC
            ''')
        
        learnings = []
        for row in cursor.fetchall():
            if category:
                learnings.append({
                    'insight': row[0],
                    'confidence': row[1],
                    'usage': row[2]
                })
            else:
                learnings.append({
                    'category': row[0],
                    'insight': row[1],
                    'confidence': row[2],
                    'usage': row[3]
                })
        
        conn.close()
        return learnings


# Test
if __name__ == "__main__":
    def mock_llm(model, messages, stream):
        return {'message': {'content': 'Root cause: file not found. Fix: check path.'}}
    
    learner = ErrorLearner(mock_llm)
    
    # Analyze error
    analysis = learner.analyze_failure(
        "read config",
        "FileNotFoundError: config.json not found"
    )
    print(f"Analysis: {analysis}")
    
    # Get suggestion
    suggestion = learner.suggest_fix("FileNotFoundError: data.json not found")
    print(f"Suggestion: {suggestion}")
    
    # Common errors
    common = learner.get_common_errors()
    print(f"Common errors: {len(common)}")
