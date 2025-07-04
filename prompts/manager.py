"""
Prompt management system for paper2slides.

This module provides a PromptManager class that handles loading and rendering
of prompt templates from YAML configuration files.
"""

import yaml
from pathlib import Path
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class PromptManager:
    """
    Manages prompt templates and renders them with variables.
    
    The PromptManager loads prompts from a YAML configuration file and provides
    methods to render them with specific variables for different stages of the
    slide generation process.
    """
    
    def __init__(self, config_path: str = None):
        """
        Initialize the PromptManager.
        
        Args:
            config_path: Path to the YAML configuration file. If None, uses
                        the default config.yaml in the prompts directory.
        """
        if config_path is None:
            # Default to config.yaml in the same directory as this file
            config_path = Path(__file__).parent / "config.yaml"
        
        self.config_path = Path(config_path)
        self.config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """
        Load the YAML configuration file.
        
        Returns:
            Dict containing the loaded configuration.
            
        Raises:
            FileNotFoundError: If the config file doesn't exist.
            yaml.YAMLError: If the config file is malformed.
        """
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                logger.info(f"Loaded prompt configuration from {self.config_path}")
                return config
        except FileNotFoundError:
            raise FileNotFoundError(f"Prompt configuration file not found: {self.config_path}")
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Error parsing YAML configuration: {e}")
    
    def get_system_message(self, stage_name: str) -> str:
        """
        Get the system message for a specific stage.
        
        Args:
            stage_name: Name of the stage ('initial', 'update', or 'revise').
            
        Returns:
            The system message string for the specified stage.
            
        Raises:
            KeyError: If the stage_name is not found in the configuration.
        """
        try:
            return self.config['stages'][stage_name]['system']
        except KeyError:
            available_stages = list(self.config['stages'].keys())
            raise KeyError(f"Stage '{stage_name}' not found. Available stages: {available_stages}")
    
    def get_prompt(self, stage_name: str, **kwargs) -> str:
        """
        Get and render a prompt template for a specific stage.
        
        Args:
            stage_name: Name of the stage ('initial', 'update', or 'revise').
            **kwargs: Variables to substitute in the template.
            
        Returns:
            The rendered prompt string with variables substituted.
            
        Raises:
            KeyError: If the stage_name is not found or required variables are missing.
        """
        try:
            # Merge defaults with provided kwargs
            context = {**self.config.get('defaults', {}), **kwargs}
            
            # Get the template
            template = self.config['stages'][stage_name]['template']
            
            # Render the template
            rendered = template.format(**context)
            
            logger.debug(f"Rendered prompt for stage '{stage_name}' with {len(context)} variables")
            return rendered
            
        except KeyError as e:
            if stage_name not in self.config['stages']:
                available_stages = list(self.config['stages'].keys())
                raise KeyError(f"Stage '{stage_name}' not found. Available stages: {available_stages}")
            else:
                # Missing variable in template
                raise KeyError(f"Missing required variable for template rendering: {e}")
        except Exception as e:
            raise ValueError(f"Error rendering prompt for stage '{stage_name}': {e}")
    
    def validate_variables(self, stage_name: str, **kwargs) -> bool:
        """
        Validate that all required variables are provided for a stage.
        
        Args:
            stage_name: Name of the stage to validate.
            **kwargs: Variables to check.
            
        Returns:
            True if all required variables are provided.
            
        Raises:
            ValueError: If required variables are missing.
        """
        try:
            template = self.config['stages'][stage_name]['template']
            
            # Extract required variables from template
            import string
            formatter = string.Formatter()
            required_vars = []
            
            for _, field_name, _, _ in formatter.parse(template):
                if field_name is not None and field_name not in required_vars:
                    required_vars.append(field_name)
            
            # Check which variables are available (defaults + provided)
            available_vars = set(self.config.get('defaults', {}).keys()) | set(kwargs.keys())
            missing_vars = set(required_vars) - available_vars
            
            if missing_vars:
                raise ValueError(f"Missing required variables for stage '{stage_name}': {missing_vars}")
            
            return True
            
        except KeyError:
            available_stages = list(self.config['stages'].keys())
            raise KeyError(f"Stage '{stage_name}' not found. Available stages: {available_stages}")
    
    def list_stages(self) -> list:
        """
        Get a list of available stage names.
        
        Returns:
            List of stage names available in the configuration.
        """
        return list(self.config['stages'].keys())
    
    def get_defaults(self) -> Dict[str, Any]:
        """
        Get the default variables from the configuration.
        
        Returns:
            Dict containing default variables.
        """
        return self.config.get('defaults', {})
    
    def reload_config(self) -> None:
        """
        Reload the configuration from the file.
        
        This is useful if the configuration file has been modified and you
        want to pick up the changes without recreating the PromptManager.
        """
        self.config = self._load_config()
        logger.info("Prompt configuration reloaded")


# Convenience function for backward compatibility
def get_prompt_manager(config_path: str = None) -> PromptManager:
    """
    Factory function to create a PromptManager instance.
    
    Args:
        config_path: Optional path to configuration file.
        
    Returns:
        PromptManager instance.
    """
    return PromptManager(config_path)