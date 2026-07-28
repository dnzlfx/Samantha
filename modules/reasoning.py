#!/usr/bin/env python3
"""
Reasoning Engine - Chain-of-thought and Task Decomposition
Enables agentic workflow with visible thinking process
"""

import json
from typing import List, Dict, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class Step:
    """Represents a single step in a task plan"""
    id: int
    description: str
    action: str  # 'read', 'write', 'analyze', 'execute'
    target: Optional[str] = None  # file path or command
    status: str = 'pending'  # 'pending', 'running', 'done', 'failed'
    result: Optional[str] = None


class ThinkingEngine:
    """
    Generates chain-of-thought reasoning for complex tasks.
    Shows visible thinking process to user.
    Optimized for low-RAM environments.
    """
    
    def __init__(self, llm_chat_function):
        """
        Args:
            llm_chat_function: Function to call LLM (ollama.chat or similar)
        """
        self.llm_chat = llm_chat_function
        self.available_ram = self._get_available_ram()
    
    def _get_available_ram(self):
        """Get available RAM in GB"""
        try:
            import psutil
            return psutil.virtual_memory().available / (1024**3)
        except:
            return 4.0  # Assume 4GB if can't detect
    
    def _select_thinking_model(self):
        """Select best thinking model based on available RAM"""
        # If we have enough RAM (>2.5GB), try R1
        if self.available_ram > 2.5:
            return ['deepseek-r1:14b', 'llama3.1:8b', 'dolphin-llama3:8b']
        # Low RAM - use smaller, more efficient models
        else:
            return ['llama3.1:8b', 'dolphin-llama3:8b', 'uncensored-llama2:latest']
    
    def _select_decompose_model(self):
        """Select best decomposition model based on available RAM"""
        if self.available_ram > 3.0:
            return ['jarviscoder:latest', 'deepseek-coder-v2:16b', 'qwen2.5-coder:7b']
        else:
            # Smaller but still capable code models
            return ['qwen2.5-coder:7b', 'llama3.1:8b', 'dolphin-llama3:8b']
    
    def analyze_task(self, task: str, context: Dict = None) -> str:
        """
        Analyze task and generate reasoning about approach.
        RAM-optimized: uses smaller models when memory is limited.
        
        Args:
            task: User's task description
            context: Additional context (files, folder info, etc.)
            
        Returns:
            Thinking process as string
        """
        context_str = ""
        if context:
            if 'files' in context:
                context_str += f"\n\nAvailable files:\n{chr(10).join(context['files'][:5])}"  # Limit to 5
            if 'folder' in context:
                context_str += f"\n\nWorking directory: {context['folder']}"
        
        # Shorter prompt for memory efficiency
        prompt = f"""Analyze: {task}{context_str}

Think through:
1. Goal?
2. Steps needed?
3. Best approach?

Be concise."""

        messages = [{"role": "user", "content": prompt}]
        
        # Use RAM-aware model selection
        models_to_try = self._select_thinking_model()
        
        thinking = ""
        for model in models_to_try:
            try:
                # Use non-streaming for lower memory
                response = self.llm_chat(model=model, messages=messages, stream=False)
                thinking = response.get('message', {}).get('content', '')
                if thinking:
                    logger.info(f"[Thinking] Used: {model} (RAM: {self.available_ram:.1f}GB)")
                    break
            except Exception as e:
                logger.warning(f"[Thinking] {model} failed: {e}")
                continue
        
        if not thinking:
            thinking = f"Task: {task}\nApproach: Execute systematically."
        
        return thinking
    
    def decompose_task(self, task: str, thinking: str = None, context: Dict = None) -> List[Step]:
        """
        Break task into executable steps.
        RAM-optimized with smaller models and concise prompts.
        
        Args:
            task: User's task description
            thinking: Previous thinking output (optional)
            context: Additional context
            
        Returns:
            List of Steps
        """
        context_str = ""
        if context and 'files' in context:
            # Limit file list for memory
            context_str = f"\n\nKey files:\n{chr(10).join(context['files'][:5])}"
        
        # Shorter prompt
        thinking_summary = f"\n\nPrior analysis:\n{thinking[:200]}" if thinking else ""

        prompt = f"""Task: {task}{context_str}{thinking_summary}

Create JSON array of steps:
[
  {{"description": "...", "action": "read|write|analyze|execute", "target": "file.py"}}
]

Keep it simple and actionable. Return ONLY JSON:"""

        messages = [{"role": "user", "content": prompt}]
        
        # Use RAM-aware model selection
        models_to_try = self._select_decompose_model()
        
        response = ""
        for model in models_to_try:
            try:
                # Non-streaming for lower memory
                result = self.llm_chat(model=model, messages=messages, stream=False)
                response = result.get('message', {}).get('content', '')
                if response:
                    logger.info(f"[Decompose] Used: {model}")
                    break
            except Exception as e:
                logger.warning(f"[Decompose] {model} failed: {e}")
                continue
                
        try:
            # Parse JSON
            if '```' in response:
                response = response.split('```json')[-1].split('```')[0]
            
            steps_data = json.loads(response.strip())
            
            steps = []
            for i, step_dict in enumerate(steps_data):
                step = Step(
                    id=i + 1,
                    description=step_dict.get('description', '')[:100],  # Truncate long descriptions
                    action=step_dict.get('action', 'execute'),
                    target=step_dict.get('target')
                )
                steps.append(step)
            
            return steps
            
        except Exception as e:
            logger.error(f"Failed to decompose: {e}")
            return [Step(id=1, description=task[:100], action='execute', target=None)]
    
    def refine_step(self, step: Step, previous_results: List[str] = None) -> str:
        """
        Generate detailed execution plan for a specific step.
        
        Args:
            step: The step to refine
            previous_results: Results from previous steps
            
        Returns:
            Refined execution instructions
        """
        prev_context = ""
        if previous_results:
            prev_context = "\n\nPrevious step results:\n" + "\n".join(previous_results[-3:])
        
        prompt = f"""Generate detailed execution instructions for this step:

Step: {step.description}
Action: {step.action}
Target: {step.target or 'N/A'}{prev_context}

Provide specific, concrete instructions on exactly what to do."""

        messages = [{"role": "user", "content": prompt}]
        
        instructions = ""
        try:
            for chunk in self.llm_chat(model='deepseek-coder-v2:16b', messages=messages, stream=True):
                content = chunk.get('message', {}).get('content', '')
                instructions += content
        except Exception as e:
            logger.error(f"Failed to refine step: {e}")
            instructions = step.description
        
        return instructions


def extract_thinking(text: str) -> str:
    """Extract content from <thinking> tags"""
    if '<thinking>' in text and '</thinking>' in text:
        start = text.find('<thinking>') + len('<thinking>')
        end = text.find('</thinking>')
        return text[start:end].strip()
    return text


# Test function
if __name__ == "__main__":
    import sys
    sys.path.append('..')
    import modules.ollama_wrapper as ollama
    
    engine = ThinkingEngine(ollama.chat)
    
    # Test task analysis
    print("=== Testing Task Analysis ===\n")
    thinking = engine.analyze_task("Add JWT authentication to Express API")
    print(thinking)
    
    # Test decomposition
    print("\n\n=== Testing Task Decomposition ===\n")
    steps = engine.decompose_task("Add JWT authentication to Express API", thinking)
    
    for step in steps:
        print(f"{step.id}. {step.description}")
        print(f"   Action: {step.action}, Target: {step.target}")
