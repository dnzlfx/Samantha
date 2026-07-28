"""
Samantha Code Sandbox.
Autonomous code execution with real-time output and auto-correction.
"""

import logging
import subprocess
import sys
import os
import tempfile
import shlex
from typing import Dict, Optional
from pathlib import Path

from .llm_manager import Intent

logger = logging.getLogger(__name__)


class SandboxExecutor:
    """
    Executes code in an isolated sandbox environment with real-time output display
    and autonomous error correction capabilities.
    """
    
    SANDBOX_DIR = "/tmp/sam_sandbox"
    MAX_RETRIES = 3
    DEFAULT_TIMEOUT = 30  # seconds
    DOCKER_IMAGE = "python:3.11-slim"  # Lightweight Python image
    
    def __init__(self, model_manager=None):
        self.model_manager = model_manager
        self._ensure_sandbox_exists()
        self.docker_available = self._check_docker()
    
    def _check_docker(self) -> bool:
        """Check if Docker is available and running"""
        try:
            result = subprocess.run(
                ['docker', 'info'],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False
    
    def _ensure_sandbox_exists(self):
        """Creates sandbox directory if it doesn't exist"""
        Path(self.SANDBOX_DIR).mkdir(parents=True, exist_ok=True)
        logger.info(f"[Sam] Sandbox directory ready: {self.SANDBOX_DIR}")
    
    def execute_in_docker(self, code: str, timeout: int = DEFAULT_TIMEOUT) -> Dict:
        """
        Execute Python code in an isolated Docker container.
        Provides security isolation for untrusted code.
        
        Args:
            code: Python code to execute
            timeout: Execution timeout in seconds
            
        Returns:
            Dict with success, output, error
        """
        if not self.docker_available:
            logger.warning("[Sam] Docker not available, falling back to local execution")
            return self.execute_realtime(code, auto_correct=False)
        
        try:
            # Write code to temp file
            code_file = os.path.join(self.SANDBOX_DIR, "docker_code.py")
            with open(code_file, 'w') as f:
                f.write(code)
            
            # Run in Docker with:
            # - Read-only root filesystem (--read-only)
            # - No network access (--network=none)
            # - Limited memory (--memory=256m)
            # - Auto-remove container (--rm)
            # - Mount only the code file
            docker_cmd = [
                'docker', 'run', '--rm',
                '--read-only',
                '--network=none',
                '--memory=256m',
                '--cpus=1',
                '-v', f'{code_file}:/app/code.py:ro',
                '-w', '/app',
                self.DOCKER_IMAGE,
                'python', '/app/code.py'
            ]
            
            print("🐳 Ejecutando en Docker (aislado)...")
            
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            output = result.stdout
            error = result.stderr
            
            if output:
                print(output)
            if error and result.returncode != 0:
                print(f"Error: {error}")
            
            return {
                'success': result.returncode == 0,
                'output': output,
                'error': error if result.returncode != 0 else None,
                'docker': True
            }
            
        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'output': '',
                'error': f'Timeout ({timeout}s) - container killed',
                'docker': True
            }
        except Exception as e:
            logger.error(f"[Sam] Docker execution failed: {e}")
            # Fallback to local
            return self.execute_realtime(code, auto_correct=False)
    
    def execute_realtime(
        self,
        code: str,
        filename: str = "test.py",
        timeout: int = DEFAULT_TIMEOUT,
        auto_correct: bool = True
    ) -> Dict:
        """
        Executes code with real-time output streaming to console.
        
        Args:
            code: Python code to execute
            filename: Name for the code file
            timeout: Execution timeout in seconds
            auto_correct: Whether to attempt auto-correction on errors
            
        Returns:
            Dict with success, output, error, and iterations count
        """
        filepath = os.path.join(self.SANDBOX_DIR, filename)
        iterations = 0
        current_code = code
        
        for attempt in range(self.MAX_RETRIES if auto_correct else 1):
            iterations += 1
            
            # Write code to file
            try:
                with open(filepath, 'w') as f:
                    f.write(current_code)
                logger.info(f"[Sam] Code written to {filepath}")
            except Exception as e:
                return {
                    'success': False,
                    'output': '',
                    'error': f"Failed to write code file: {e}",
                    'iterations': iterations,
                    'final_code': current_code
                }
            
            # Execute with real-time output
            print(f"\n{'='*60}")
            print(f"🔄 Ejecutando código (intento {attempt + 1}/{self.MAX_RETRIES if auto_correct else 1})...")
            print(f"{'='*60}\n")
            
            result = self._execute_with_streaming(filepath, timeout)
            
            if result['success']:
                print(f"\n{'='*60}")
                print("✅ CÓDIGO EJECUTADO EXITOSAMENTE")
                print(f"{'='*60}\n")
                
                return {
                    'success': True,
                    'output': result['output'],
                    'error': None,
                    'iterations': iterations,
                    'final_code': current_code
                }
            else:
                print(f"\n{'='*60}")
                print(f"❌ Error detectado en intento {attempt + 1}")
                print(f"{'='*60}")
                print(f"Error: {result['error']}\n")
                
                # Attempt auto-correction if enabled and not last attempt
                if auto_correct and attempt < self.MAX_RETRIES - 1 and self.model_manager:
                    logger.info(f"[Sam] Attempting auto-correction...")
                    corrected_code = self._auto_correct(current_code, result['error'])
                    
                    if corrected_code and corrected_code != current_code:
                        print(f"🔧 Generando corrección automática...\n")
                        current_code = corrected_code
                    else:
                        logger.warning("[Sam] Auto-correction failed to generate new code")
                        break
                else:
                    break
        
        # All attempts failed
        return {
            'success': False,
            'output': result['output'],
            'error': result['error'],
            'iterations': iterations,
            'final_code': current_code
        }
    
    def _execute_with_streaming(self, filepath: str, timeout: int) -> Dict:
        """
        Executes a Python file with line-by-line streaming output.
        
        Args:
            filepath: Path to Python file
            timeout: Execution timeout
            
        Returns:
            Dict with success, output, and error
        """
        try:
            # Start process with real-time output capability
            process = subprocess.Popen(
                ['python3', filepath],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True,
                cwd=self.SANDBOX_DIR
            )
            
            output_lines = []
            error_lines = []
            
            # Read stdout in real-time
            try:
                while True:
                    # Check if process finished
                    if process.poll() is not None:
                        break
                    
                    # Read line from stdout
                    line = process.stdout.readline()
                    if line:
                        # Display immediately
                        print(line.rstrip())
                        sys.stdout.flush()  # CRITICAL: Force immediate display
                        output_lines.append(line.rstrip())
                
                # Read any remaining output
                remaining_stdout = process.stdout.read()
                if remaining_stdout:
                    print(remaining_stdout.rstrip())
                    sys.stdout.flush()
                    output_lines.append(remaining_stdout.rstrip())
                
                # Read stderr
                stderr_output = process.stderr.read()
                if stderr_output:
                    error_lines.append(stderr_output)
                
                return_code = process.wait(timeout=timeout)
                
                if return_code == 0:
                    return {
                        'success': True,
                        'output': '\n'.join(output_lines),
                        'error': None
                    }
                else:
                    return {
                        'success': False,
                        'output': '\n'.join(output_lines),
                        'error': '\n'.join(error_lines)
                    }
                    
            except subprocess.TimeoutExpired:
                process.kill()
                return {
                    'success': False,
                    'output': '\n'.join(output_lines),
                    'error': f"⏱️ Timeout: Execution exceeded {timeout} seconds"
                }
                
        except Exception as e:
            logger.error(f"[Sam] Execution error: {e}")
            return {
                'success': False,
                'output': '',
                'error': str(e)
            }
    
    def _auto_correct(self, code: str, error: str) -> Optional[str]:
        """
        Uses LLM to generate corrected code based on error.
        
        Args:
            code: Original code that failed
            error: Error message/traceback
            
        Returns:
            Corrected code or None
        """
        if not self.model_manager:
            return None
        
        correction_prompt = f"""El siguiente código Python falló con un error. Analiza el error y genera el código corregido.

CÓDIGO ORIGINAL:
```python
{code}
```

ERROR:
```
{error}
```

Instrucciones:
- Identifica la causa raíz del error
- Genera el código completamente corregido
- Retorna SOLO el código Python corregido, sin explicaciones ni markdown
- El código debe ser funcional y completo

CÓDIGO CORREGIDO:
"""
        
        try:
            # Use coding model for correction
            coding_model = self.model_manager.models.get(Intent.CODING) or self.model_manager.current_model
            if not coding_model:
                return None

            corrected = self.model_manager.generate(
                prompt=correction_prompt,
                model=coding_model,
                temperature=0.2  # Low temperature for precise corrections
            )
            
            # Clean up response (remove markdown if present)
            corrected = corrected.strip()
            if corrected.startswith('```python'):
                corrected = corrected[len('```python'):].strip()
            if corrected.endswith('```'):
                corrected = corrected[:-3].strip()
            
            return corrected
            
        except Exception as e:
            logger.error(f"[Sam] Auto-correction failed: {e}")
            return None
    
    def execute_command_realtime(
        self,
        command: str,
        timeout: int = DEFAULT_TIMEOUT,
        shell: bool = False,
        cwd: Optional[str] = None
    ) -> Dict:
        """
        Executes an arbitrary system command with real-time output.
        Used for running non-Python commands.
        
        Args:
            command: Command to execute
            timeout: Execution timeout
            shell: Whether to use shell execution
            cwd: Working directory
            
        Returns:
            Dict with success, output, error, return_code
        """
        # Sanitize command if not using shell
        if not shell:
            command_parts = shlex.split(command)
        else:
            command_parts = command
        
        logger.info(f"[Sam] Executing command: {command}")
        
        print(f"\n{'='*60}")
        print(f"🚀 Ejecutando: {command}")
        print(f"{'='*60}\n")
        
        try:
            process = subprocess.Popen(
                command_parts if not shell else command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True,
                shell=shell,
                cwd=cwd or self.SANDBOX_DIR
            )
            
            output_lines = []
            
            # Stream output in real-time
            while True:
                if process.poll() is not None:
                    break
                
                line = process.stdout.readline()
                if line:
                    print(line.rstrip())
                    sys.stdout.flush()
                    output_lines.append(line.rstrip())
            
            # Read remaining
            remaining = process.stdout.read()
            if remaining:
                print(remaining.rstrip())
                sys.stdout.flush()
                output_lines.append(remaining.rstrip())
            
            stderr_output = process.stderr.read()
            error_lines = stderr_output.split('\n') if stderr_output else []
            
            return_code = process.wait(timeout=timeout)
            
            print(f"\n{'='*60}")
            if return_code == 0:
                print("✅ Comando completado exitosamente")
            else:
                print(f"❌ Comando terminó con código {return_code}")
            print(f"{'='*60}\n")
            
            return {
                'success': return_code == 0,
                'output': '\n'.join(output_lines),
                'error': stderr_output if stderr_output else None,
                'return_code': return_code
            }
            
        except subprocess.TimeoutExpired:
            process.kill()
            return {
                'success': False,
                'output': '\n'.join(output_lines),
                'error': f"Timeout: Command exceeded {timeout} seconds",
                'return_code': -1
            }
        except Exception as e:
            logger.error(f"[Sam] Command execution failed: {e}")
            return {
                'success': False,
                'output': '',
                'error': str(e),
                'return_code': -1
            }
    
    def cleanup(self):
        """Cleans up sandbox directory"""
        import shutil
        try:
            shutil.rmtree(self.SANDBOX_DIR)
            self._ensure_sandbox_exists()
            logger.info("[Sam] Sandbox cleaned")
        except Exception as e:
            logger.error(f"[Sam] Sandbox cleanup failed: {e}")
