import yaml

def load_config():
    with open("./resources/config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)