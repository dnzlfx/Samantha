#!/usr/bin/env python3
"""
Task Memory System - Stores and retrieves task execution history
Enables learning from past experiences
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
import hashlib
import logging

logger = logging.getLogger(__name__)


class TaskMemory:
    """
    Persistent memory of all tasks executed.
    Stores successes, failures, and learnings.
    """
    
    def __init__(self, db_path: str = None):
        """Initialize task memory database"""
        if db_path is None:
            brain_dir = Path.home() / '.samantha' / 'brain'
            brain_dir.mkdir(parents=True, exist_ok=True)
            db_path = brain_dir / 'task_memory.db'
        
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Create database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Tasks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_hash TEXT UNIQUE,
                task_description TEXT,
                task_type TEXT,
                steps_json TEXT,
                result TEXT,
                error TEXT,
                execution_time REAL,
                model_used TEXT,
                ram_available REAL,
                timestamp TEXT,
                learnings TEXT
            )
        ''')
        
        # Performance stats table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                avg_time REAL DEFAULT 0,
                last_updated TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def _hash_task(self, task: str) -> str:
        """Generate hash for task similarity detection"""
        # Normalize and hash
        normalized = task.lower().strip()
        return hashlib.md5(normalized.encode()).hexdigest()
    
    def store_task(self, 
                   task: str, 
                   task_type: str,
                   steps: List[Dict],
                   result: str,
                   error: Optional[str] = None,
                   execution_time: float = 0,
                   model_used: str = "",
                   ram_available: float = 0,
                   learnings: str = "") -> int:
        """
        Store completed task in memory.
        
        Args:
            task: Task description
            task_type: Type (code, analysis, etc)
            steps: List of steps executed
            result: 'success' or 'failed'
            error: Error message if failed
            execution_time: Seconds taken
            model_used: LLM model used
            ram_available: RAM available in GB
            learnings: Insights learned
            
        Returns:
            Task ID
        """
        task_hash = self._hash_task(task)
        steps_json = json.dumps(steps)
        timestamp = datetime.now().isoformat()
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
                INSERT INTO tasks (
                    task_hash, task_description, task_type, steps_json,
                    result, error, execution_time, model_used,
                    ram_available, timestamp, learnings
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (task_hash, task, task_type, steps_json, result, error,
                  execution_time, model_used, ram_available, timestamp, learnings))
            
            task_id = cursor.lastrowid
            
            # Update performance stats
            self._update_performance(cursor, task_type, result, execution_time)
            
            conn.commit()
            logger.info(f"[Memory] Stored task {task_id}: {task[:50]}...")
            return task_id
            
        except sqlite3.IntegrityError:
            # Task already exists, update it
            cursor.execute('''
                UPDATE tasks SET
                    steps_json=?, result=?, error=?, execution_time=?,
                    model_used=?, ram_available=?, timestamp=?, learnings=?
                WHERE task_hash=?
            ''', (steps_json, result, error, execution_time, model_used,
                  ram_available, timestamp, learnings, task_hash))
            conn.commit()
            logger.info(f"[Memory] Updated existing task: {task[:50]}...")
            return -1
        finally:
            conn.close()
    
    def _update_performance(self, cursor, task_type: str, result: str, exec_time: float):
        """Update performance statistics"""
        cursor.execute('''
            SELECT success_count, failure_count, avg_time
            FROM performance WHERE task_type=?
        ''', (task_type,))
        
        row = cursor.fetchone()
        
        if row:
            success, failure, avg_time = row
            if result == 'success':
                success += 1
            else:
                failure += 1
            
            # Update running average
            total = success + failure
            new_avg = ((avg_time * (total - 1)) + exec_time) / total
            
            cursor.execute('''
                UPDATE performance SET
                    success_count=?, failure_count=?, avg_time=?, last_updated=?
                WHERE task_type=?
            ''', (success, failure, new_avg, datetime.now().isoformat(), task_type))
        else:
            # First entry for this type
            cursor.execute('''
                INSERT INTO performance (task_type, success_count, failure_count, avg_time, last_updated)
                VALUES (?, ?, ?, ?, ?)
            ''', (task_type, 1 if result == 'success' else 0,
                  0 if result == 'success' else 1,
                  exec_time, datetime.now().isoformat()))
    
    def get_similar_tasks(self, task: str, limit: int = 5) -> List[Dict]:
        """
        Find similar tasks from history.
        
        Args:
            task: Task description
            limit: Max results
            
        Returns:
            List of similar tasks
        """
        task_hash = self._hash_task(task)
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # First try exact match
        cursor.execute('''
            SELECT task_description, result, steps_json, learnings, execution_time
            FROM tasks WHERE task_hash=?
            ORDER BY timestamp DESC LIMIT ?
        ''', (task_hash, limit))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                'task': row[0],
                'result': row[1],
                'steps': json.loads(row[2]),
                'learnings': row[3],
                'time': row[4]
            })
        
        # If no exact match, find by keywords
        if not results:
            keywords = task.lower().split()[:3]  # First 3 words
            query = f"%{keywords[0]}%"
            
            cursor.execute('''
                SELECT task_description, result, steps_json, learnings, execution_time
                FROM tasks WHERE LOWER(task_description) LIKE ?
                ORDER BY timestamp DESC LIMIT ?
            ''', (query, limit))
            
            for row in cursor.fetchall():
                results.append({
                    'task': row[0],
                    'result': row[1],
                    'steps': json.loads(row[2]),
                    'learnings': row[3],
                    'time': row[4]
                })
        
        conn.close()
        return results
    
    def get_success_rate(self, task_type: str = None) -> Dict:
        """
        Get success rate statistics.
        
        Args:
            task_type: Optional filter by type
            
        Returns:
            Stats dict
        """
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if task_type:
            cursor.execute('''
                SELECT success_count, failure_count, avg_time
                FROM performance WHERE task_type=?
            ''', (task_type,))
        else:
            cursor.execute('''
                SELECT SUM(success_count), SUM(failure_count), AVG(avg_time)
                FROM performance
            ''')
        
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0] is not None:
            success, failure = row[0], row[1]
            total = success + failure
            return {
                'success_rate': (success / total * 100) if total > 0 else 0,
                'total_tasks': total,
                'avg_time': row[2] or 0
            }
        
        return {'success_rate': 0, 'total_tasks': 0, 'avg_time': 0}
    
    def get_recent_failures(self, limit: int = 10) -> List[Dict]:
        """Get recent failed tasks for learning"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT task_description, error, steps_json, timestamp
            FROM tasks WHERE result='failed'
            ORDER BY timestamp DESC LIMIT ?
        ''', (limit,))
        
        failures = []
        for row in cursor.fetchall():
            failures.append({
                'task': row[0],
                'error': row[1],
                'steps': json.loads(row[2]),
                'timestamp': row[3]
            })
        
        conn.close()
        return failures


# Test
if __name__ == "__main__":
    memory = TaskMemory()
    
    # Store a task
    task_id = memory.store_task(
        task="add authentication",
        task_type="code",
        steps=[{"description": "Install JWT", "action": "execute"}],
        result="success",
        execution_time=45.2,
        model_used="llama3.1:8b",
        ram_available=2.5
    )
    
    print(f"Stored task: {task_id}")
    
    # Find similar
    similar = memory.get_similar_tasks("add auth")
    print(f"Found {len(similar)} similar tasks")
    
    # Stats
    stats = memory.get_success_rate()
    print(f"Success rate: {stats['success_rate']:.1f}%")
