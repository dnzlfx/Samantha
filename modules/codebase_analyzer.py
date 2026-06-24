#!/usr/bin/env python3
"""
Codebase Analyzer - Folder and file context analysis
Enables understanding of entire projects for agentic workflows
"""

import os
from pathlib import Path
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class CodebaseAnalyzer:
    """
    Analyzes codebases to provide context for agentic tasks.
    Scans folders, identifies key files, builds summaries.
    """
    
    def __init__(self):
        # File extensions to analyze
        self.code_extensions = {
            '.py', '.js', '.ts', '.jsx', '.tsx', '.java', '.c', '.cpp', '.h',
            '.go', '.rs', '.rb', '.php', '.cs', '.swift', '.kt', '.scala',
            '.sh', '.bash', '.zsh', '.html', '.css', '.scss', '.sql'
        }
        
        # Folders to ignore
        self.ignore_folders = {
            'node_modules', '__pycache__', '.git', '.venv', 'venv',
            'build', 'dist', '.next', '.cache', 'target', 'bin', 'obj'
        }
    
    def scan_folder(self, path: str, max_files: int = 100) -> Dict:
        """
        Scan folder and gather stats.
        
        Args:
            path: Folder path to scan
            max_files: Maximum files to include
            
        Returns:
            Dict with folder stats and file list
        """
        path = Path(path).resolve()
        
        if not path.exists():
            return {'error': 'Path does not exist'}
        
        if not path.is_dir():
            return {'error': 'Path is not a directory'}
        
        files = []
        total_lines = 0
        file_types = {}
        
        try:
            for root, dirs, filenames in os.walk(path):
                # Filter out ignored folders
                dirs[:] = [d for d in dirs if d not in self.ignore_folders]
                
                for filename in filenames:
                    file_path = Path(root) / filename
                    rel_path = file_path.relative_to(path)
                    
                    # Check extension
                    ext = file_path.suffix.lower()
                    if ext in self.code_extensions:
                        try:
                            # Count lines
                            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                lines = len(f.readlines())
                            
                            files.append({
                                'path': str(rel_path),
                                'lines': lines,
                                'size': file_path.stat().st_size,
                                'ext': ext
                            })
                            
                            total_lines += lines
                            file_types[ext] = file_types.get(ext, 0) + 1
                            
                            if len(files) >= max_files:
                                break
                        except Exception as e:
                            logger.debug(f"Could not read {file_path}: {e}")
                            continue
                
                if len(files) >= max_files:
                    break
            
            # Sort by lines descending (most important files first)
            files.sort(key=lambda x: x['lines'], reverse=True)
            
            return {
                'path': str(path),
                'total_files': len(files),
                'total_lines': total_lines,
                'file_types': file_types,
                'files': files[:max_files]
            }
            
        except Exception as e:
            logger.error(f"Error scanning folder: {e}")
            return {'error': str(e)}
    
    def identify_key_files(self, scan_result: Dict, task: str = None) -> List[str]:
        """
        Identify most relevant files for a task.
        
        Args:
            scan_result: Result from scan_folder()
            task: Optional task description to prioritize files
            
        Returns:
            List of file paths (most relevant first)
        """
        if 'error' in scan_result or 'files' not in scan_result:
            return []
        
        files = scan_result['files']
        
        # Priority keywords in filenames
        priority_keywords = {
            'main': 10,
            'index': 9,
            'app': 8,
            'server': 7,
            'api': 6,
            'config': 5,
            'routes': 4,
            'middleware': 4,
            'models': 4,
            'controllers': 4,
            'test': -5  # Deprioritize tests unless needed
        }
        
        # If task mentions specific concepts, boost those files
        if task:
            task_lower = task.lower()
            if 'auth' in task_lower:
                priority_keywords['auth'] = 12
            if 'api' in task_lower or 'endpoint' in task_lower:
                priority_keywords['api'] = 12
                priority_keywords['routes'] = 12
            if 'database' in task_lower or 'db' in task_lower:
                priority_keywords['model'] = 12
                priority_keywords['database'] = 12
            if 'test' in task_lower:
                priority_keywords['test'] = 12
        
        # Score files
        scored_files = []
        for file_info in files:
            path_lower = file_info['path'].lower()
            score = file_info['lines']  # Base score on file size
            
            # Apply keyword bonuses
            for keyword, bonus in priority_keywords.items():
                if keyword in path_lower:
                    score += bonus * 100
            
            scored_files.append((score, file_info['path']))
        
        # Sort by score
        scored_files.sort(reverse=True)
        
        # Return top files
        return [path for score, path in scored_files[:20]]
    
    def build_context_summary(self, scan_result: Dict, key_files: List[str]) -> str:
        """
        Build a concise context summary for LLM.
        
        Args:
            scan_result: Result from scan_folder()
            key_files: List of key file paths
            
        Returns:
            Context summary as string
        """
        if 'error' in scan_result:
            return f"Error: {scan_result['error']}"
        
        summary = f"""Codebase: {scan_result['path']}
Files: {scan_result['total_files']} ({scan_result['total_lines']} lines)

File types:"""
        
        for ext, count in sorted(scan_result['file_types'].items(), key=lambda x: x[1], reverse=True):
            summary += f"\n  {ext}: {count} files"
        
        summary += f"\n\nKey files (by relevance):"
        for i, file_path in enumerate(key_files[:10], 1):
            summary += f"\n  {i}. {file_path}"
        
        return summary
    
    def read_file_summary(self, file_path: str) -> str:
        """
        Read file and generate brief summary.
        
        Args:
            file_path: Path to file
            
        Returns:
            File summary
        """
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            # For Python, extract classes and functions
            if file_path.endswith('.py'):
                imports = [l.strip() for l in lines if l.startswith('import ') or l.startswith('from ')]
                classes = [l.strip() for l in lines if l.strip().startswith('class ')]
                functions = [l.strip() for l in lines if l.strip().startswith('def ')]
                
                summary = f"File: {file_path} ({len(lines)} lines)\n"
                if imports:
                    summary += f"Imports: {len(imports)}\n"
                if classes:
                    summary += f"Classes: {', '.join([c.split('(')[0].replace('class ', '') for c in classes[:5]])}\n"
                if functions:
                    summary += f"Functions: {', '.join([f.split('(')[0].replace('def ', '') for f in functions[:5]])}\n"
                
                return summary
            
            # For other files, just show first few lines
            return f"File: {file_path} ({len(lines)} lines)\n{chr(10).join(lines[:5])}"
            
        except Exception as e:
            return f"Could not read {file_path}: {e}"


# Test
if __name__ == "__main__":
    analyzer = CodebaseAnalyzer()
    
    print("=== Testing Codebase Analyzer ===\n")
    
    # Scan current directory
    result = analyzer.scan_folder('.')
    
    if 'error' not in result:
        print(f"Found {result['total_files']} files, {result['total_lines']} lines\n")
        
        # Identify key files
        key_files = analyzer.identify_key_files(result, "add authentication")
        
        # Build summary
        summary = analyzer.build_context_summary(result, key_files)
        print(summary)
