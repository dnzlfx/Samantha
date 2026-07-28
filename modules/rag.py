"""
Samantha RAG manager.
File discovery and context injection for document-aware conversations.
"""

import logging
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class RAGManager:
    """
    Manages file discovery and context injection.
    Indexes files for quick lookup and retrieval.
    """
    
    DEFAULT_SCAN_PATHS = [
        str(Path.home() / "projects"),
        str(Path.home() / "documents" / "notes")
    ]
    
    def __init__(self, scan_paths: Optional[List[str]] = None):
        self.scan_paths = scan_paths or self.DEFAULT_SCAN_PATHS
        self.file_index: Dict[str, Dict] = {}
        self.indexed_count = 0
    
    def scan_directories(self, max_depth: int = 3):
        """
        Scans configured directories and indexes files.
        
        Args:
            max_depth: Maximum directory depth to scan
        """
        logger.info(f"[Sam] Starting file discovery in {len(self.scan_paths)} paths")
        
        for scan_path in self.scan_paths:
            if not os.path.exists(scan_path):
                logger.warning(f"[Sam] Path does not exist: {scan_path}")
                continue
            
            self._index_directory(scan_path, current_depth=0, max_depth=max_depth)
        
        logger.info(f"[Sam] Indexed {self.indexed_count} files")
    
    def _index_directory(self, directory: str, current_depth: int, max_depth: int):
        """
        Recursively indexes a directory.
        
        Args:
            directory: Directory to index
            current_depth: Current recursion depth
            max_depth: Maximum depth allowed
        """
        if current_depth >= max_depth:
            return
        
        try:
            for item in os.listdir(directory):
                item_path = os.path.join(directory, item)
                
                # Skip hidden files and common ignores
                if item.startswith('.') or item in ['node_modules', '__pycache__', 'venv', '.git']:
                    continue
                
                if os.path.isfile(item_path):
                    self._index_file(item_path)
                elif os.path.isdir(item_path):
                    self._index_directory(item_path, current_depth + 1, max_depth)
        
        except PermissionError:
            logger.warning(f"[Sam] Permission denied: {directory}")
        except Exception as e:
            logger.error(f"[Sam] Error indexing {directory}: {e}")
    
    def _index_file(self, filepath: str):
        """
        Indexes a single file with metadata.
        
        Args:
            filepath: Path to file
        """
        try:
            stat = os.stat(filepath)
            
            file_info = {
                'path': filepath,
                'filename': os.path.basename(filepath),
                'extension': Path(filepath).suffix,
                'size_bytes': stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'indexed_at': datetime.now().isoformat()
            }
            
            # Use file path as key
            self.file_index[filepath] = file_info
            self.indexed_count += 1
            
        except Exception as e:
            logger.error(f"[Sam] Error indexing file {filepath}: {e}")
    
    def search_files(
        self,
        query: str,
        by: str = "filename",
        limit: int = 10
    ) -> List[Dict]:
        """
        Searches indexed files.
        
        Args:
            query: Search query
            by: Search by 'filename', 'extension', or 'path'
            limit: Maximum results
            
        Returns:
            List of matching file info dicts
        """
        query_lower = query.lower()
        results = []
        
        for filepath, info in self.file_index.items():
            if by == "filename" and query_lower in info['filename'].lower():
                results.append(info)
            elif by == "extension" and query_lower == info['extension'].lower():
                results.append(info)
            elif by == "path" and query_lower in filepath.lower():
                results.append(info)
            
            if len(results) >= limit:
                break
        
        return results
    
    def inject_file(self, filepath: str) -> Optional[str]:
        """
        Reads file content for injection into conversation context.
        
        Args:
            filepath: Path to file to inject
            
        Returns:
            File content or None
        """
        try:
            # Check if file exists
            if not os.path.exists(filepath):
                logger.warning(f"[Sam] File not found: {filepath}")
                return None
            
            # Check file size (limit to 1MB for safety)
            file_size = os.path.getsize(filepath)
            if file_size > 1024 * 1024:  # 1MB
                logger.warning(f"[Sam] File too large to inject: {filepath} ({file_size} bytes)")
                return f"[File too large: {file_size} bytes. Maximum: 1MB]"
            
            # Read file content
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            logger.info(f"[Sam] Injected file: {filepath} ({len(content)} chars)")
            return content
            
        except Exception as e:
            logger.error(f"[Sam] Error reading file {filepath}: {e}")
            return None
    
    def get_file_info(self, filepath: str) -> Optional[Dict]:
        """
        Gets metadata for a specific file.
        
        Args:
            filepath: Path to file
            
        Returns:
            File info dict or None
        """
        return self.file_index.get(filepath)
    
    def get_stats(self) -> Dict:
        """
        Returns indexing statistics.
        
        Returns:
            Stats dict
        """
        extensions = {}
        total_size = 0
        
        for info in self.file_index.values():
            ext = info['extension'] or 'no_extension'
            extensions[ext] = extensions.get(ext, 0) + 1
            total_size += info['size_bytes']
        
        return {
            'total_files': self.indexed_count,
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'extensions': extensions,
            'scan_paths': self.scan_paths
        }
