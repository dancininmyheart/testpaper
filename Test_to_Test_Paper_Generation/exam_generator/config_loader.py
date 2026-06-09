import os
import re
import yaml

def load_config(config_path: str) -> dict:
    """Load config.yaml and expand environment variable placeholders like ${VAR:-DEFAULT}."""
    with open(config_path, "r", encoding="utf-8") as f:
        content = f.read()
    
    # regex pattern to match ${VAR:-DEFAULT} or ${VAR}
    pattern = re.compile(r'\$\{(?P<var>[A-Za-z0-9_]+)(?::-(?P<default>[^}]*))?\}')
    
    def replace_env(match):
        var_name = match.group("var")
        default_val = match.group("default")
        if default_val is None:
            default_val = ""
        return os.environ.get(var_name, default_val)
        
    content_expanded = pattern.sub(replace_env, content)
    return yaml.safe_load(content_expanded)
