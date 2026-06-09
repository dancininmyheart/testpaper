import json
import yaml
import os
from abc import ABC, abstractmethod
from typing import Any, Dict
from openai import OpenAI
import time
import re

class BaseAgent(ABC):
    def __init__(self, *, config: dict | None = None, config_path: str | None = None, agent_name: str = "base"):
        if config is None and config_path is None:
            config_path = "exam_generator/config.yaml"
            
        if config is not None:
            self.config = config
        else:
            from ..config_loader import load_config
            self.config = load_config(config_path)
        
        self.agent_name = agent_name
        self._clients: Dict[str, OpenAI] = {}

        model_config = self._get_model_config(agent_name)
        self.provider = model_config["provider"]
        self.api_key = model_config["api_key"]
        self.base_url = model_config["base_url"]
        self.model = model_config["model"]
        self.temperature = model_config["temperature"]
        
        self.client = self._get_client(self.provider)
        self.system_prompt = self._load_system_prompt()

    def _get_model_config(self, agent_name: str) -> Dict[str, Any]:
        """Resolve provider/model/temperature for an agent."""
        api_config = self.config.get("api", {})
        models_config = self.config.get("models", {})
        temperatures = self.config.get("temperature", {})
        provider_map = self.config.get("model_providers", {})

        default_provider = api_config.get("active_provider", "zhichuang")
        model_entry = models_config.get(agent_name, "gpt-4o")

        if isinstance(model_entry, dict):
            provider = model_entry.get("provider") or provider_map.get(agent_name) or default_provider
            model = model_entry.get("model") or model_entry.get("name")
            temperature = model_entry.get("temperature", temperatures.get(agent_name, 0.3))
        else:
            provider = provider_map.get(agent_name, default_provider)
            model = model_entry
            temperature = temperatures.get(agent_name, 0.3)

        if not model:
            raise ValueError(f"Model for agent '{agent_name}' is not configured.")

        # Allow resolve from config first, then environment fallback
        api_key = api_config.get(f"{provider}_key")
        if not api_key:
            api_key = os.environ.get(f"{provider.upper()}_KEY") or os.environ.get(f"EXAM_GEN_{provider.upper()}_KEY")
        if provider == "ds" and not api_key:
            api_key = os.environ.get("DEEPSEEK_KEY")

        base_url = api_config.get(f"{provider}_base_url")
        if not base_url:
            base_url = os.environ.get(f"{provider.upper()}_BASE_URL") or os.environ.get(f"EXAM_GEN_{provider.upper()}_BASE_URL")
        if provider == "ds" and not base_url:
            base_url = os.environ.get("DEEPSEEK_BASE_URL")

        if not api_key:
            raise ValueError(f"API key for provider '{provider}' not found.")
        if not base_url:
            raise ValueError(f"Base URL for provider '{provider}' not found.")

        return {
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "temperature": temperature,
        }

    def _get_client(self, provider: str) -> OpenAI:
        if provider not in self._clients:
            api_config = self.config.get("api", {})
            api_key = api_config.get(f"{provider}_key")
            if not api_key:
                api_key = os.environ.get(f"{provider.upper()}_KEY") or os.environ.get(f"EXAM_GEN_{provider.upper()}_KEY")
            if provider == "ds" and not api_key:
                api_key = os.environ.get("DEEPSEEK_KEY")

            base_url = api_config.get(f"{provider}_base_url")
            if not base_url:
                base_url = os.environ.get(f"{provider.upper()}_BASE_URL") or os.environ.get(f"EXAM_GEN_{provider.upper()}_BASE_URL")
            if provider == "ds" and not base_url:
                base_url = os.environ.get("DEEPSEEK_BASE_URL")

            if not api_key:
                raise ValueError(f"API key for provider '{provider}' not found.")
            if not base_url:
                raise ValueError(f"Base URL for provider '{provider}' not found.")

            self._clients[provider] = OpenAI(api_key=api_key, base_url=base_url)
        return self._clients[provider]

    @abstractmethod
    def _load_system_prompt(self) -> str:
        """Subclasses should return their specific system prompt."""
        pass

    @abstractmethod
    def run(self, input_data: Any) -> Any:
        """Perform the agent's task."""
        pass

    def _call_llm(self, user_message: str, response_format: str = "json_object", 
                  model: str = None, temperature: float = None, system_prompt: str = None,
                  agent_name: str = None, provider: str = None) -> str:
        """Unified LLM call with retry logic and streaming output."""
        if agent_name:
            model_config = self._get_model_config(agent_name)
            target_provider = provider or model_config["provider"]
            target_model = model or model_config["model"]
            default_temp = model_config["temperature"]
        else:
            target_provider = provider or self.provider
            target_model = model or self.model
            default_temp = self.temperature

        target_temp = temperature if temperature is not None else default_temp
        target_system = system_prompt or self.system_prompt
        target_client = self._get_client(target_provider)

        max_retries = 10
        for attempt in range(max_retries):
            try:
                kwargs = {
                    "model": target_model,
                    "messages": [
                        {"role": "system", "content": target_system},
                        {"role": "user", "content": user_message}
                    ],
                    "temperature": target_temp,
                    "stream": True
                }
                
                if response_format == "json_object":
                    kwargs["response_format"] = {"type": "json_object"}
                    # Ensure 'json' is in the messages (some providers are very strict)
                    if "json" not in user_message.lower() and "json" not in target_system.lower():
                        user_message += "\n\n(Please provide the output in valid JSON format)"
                        kwargs["messages"][1]["content"] = user_message # Update message in kwargs
                
                print(f"[*] Calling LLM ({target_provider}/{target_model}): ", end="", flush=True)
                response = target_client.chat.completions.create(**kwargs)
                
                full_content = ""
                for chunk in response:
                    if chunk.choices and chunk.choices[0].delta.content:
                        content = chunk.choices[0].delta.content
                        full_content += content
                        print(content, end="", flush=True)
                
                print("\n") # New line after stream ends
                return full_content.strip()
            except Exception as e:
                print(f"\nLLM Call failed (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise e
                time.sleep(5)

    def _extract_json(self, text: str) -> Any:
        """Safely extract JSON from LLM response."""
        try:
            # Try parsing as is
            return json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON block
            match = re.search(r'```json\n(.*?)\n```', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except:
                    pass
            # Last resort: try to find any { or [
            start = text.find('{')
            if start == -1: start = text.find('[')
            end = text.rfind('}')
            if end == -1: end = text.rfind(']')
            
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start:end+1])
                except:
                    pass
            raise ValueError(f"Could not parse JSON from: {text}")
