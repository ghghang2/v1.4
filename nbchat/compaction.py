"""Token counting and history compaction for managing context size."""

from __future__ import annotations

import threading
from typing import List, Tuple, Optional
from nbchat.ui.chat_builder import build_messages
from nbchat.core.client import get_client


class CompactionEngine:
    """Compacts chat history when token count exceeds threshold."""
    
    def __init__(self, threshold: int, tail_messages: int = 5, 
                 summary_prompt: str = None, summary_model: str = None,
                 system_prompt: str = ""):
        self.threshold = threshold
        self.tail_messages = tail_messages
        self.summary_prompt = summary_prompt or (
            "Summarize the conversation so far, focusing on:\n"
            "1. Key decisions made\n"
            "2. Important file paths and edits\n"
            "3. Tool calls and their outcomes (summarize large outputs)\n"
            "4. Next steps planned\n"
            "Keep it concise but preserve teach-a-man-to-fish information."
        )
        self.summary_model = summary_model
        self.system_prompt = system_prompt
        self._cache = {}  # message hash -> token count
        self._cache_lock = threading.Lock()
    
    def _estimate_tokens(self, text: str) -> int:
        """Simple token estimation: ~4 characters per token."""
        return max(1, len(text) // 4)
    
    def total_tokens(self, history: List[Tuple[str, str, str, str, str]]) -> int:
        """Calculate total tokens in history with simple caching."""
        total = 0
        for role, content, tool_id, tool_name, tool_args in history:
            # Create a simple hash for caching (ignore role as it affects tokens minimally)
            msg_hash = hash((content, tool_args))
            with self._cache_lock:
                if msg_hash in self._cache:
                    total += self._cache[msg_hash]
                    continue
            
            # Estimate and cache
            msg_tokens = self._estimate_tokens(content)
            if tool_args:
                msg_tokens += self._estimate_tokens(tool_args)
            
            with self._cache_lock:
                self._cache[msg_hash] = msg_tokens
                total += msg_tokens
        
        return total
    
    def should_compact(self, history: List[Tuple[str, str, str, str, str]]) -> bool:
        """Check if history exceeds token threshold."""
        return self.total_tokens(history) >= self.threshold
    
    def compact_history(self, history: List[Tuple[str, str, str, str, str]]) -> List[Tuple[str, str, str, str, str]]:
        """
        Summarise older messages, keep recent tail.
        
        Returns new history or raises exception on failure.
        """
        if len(history) <= self.tail_messages:
            return history  # Not enough to compact
            
        older = history[:-self.tail_messages]
        tail = history[-self.tail_messages:]
        
        # Build messages for summarisation with original system prompt
        messages = build_messages(older, self.system_prompt)
        messages.append({"role": "user", "content": self.summary_prompt})
        
        # Request summary - must succeed or raise
        try:
            client = get_client()
            response = client.chat.completions.create(
                model=self.summary_model,
                messages=messages,
                max_tokens=512,
            )
        except Exception as e:
            raise RuntimeError(f"Summarization failed: {e}")
        
        # Clear cache since history structure changes
        with self._cache_lock:
            self._cache.clear()
        
        summary_text = response.choices[0].message.content
        
        # New history: summary (as system message) + tail
        # Use role "system" for API compatibility
        return [("system", summary_text, "", "", "")] + tail


# For convenience
__all__ = ["CompactionEngine"]