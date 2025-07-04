"""
Prompt management package for paper2slides.

This package provides prompt management functionality including template loading,
variable substitution, and prompt rendering for different stages of the slide
generation process.
"""

from .manager import PromptManager, get_prompt_manager

__all__ = ['PromptManager', 'get_prompt_manager']
__version__ = '1.0.0'