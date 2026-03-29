import yaml
import os
from dotenv import load_dotenv

load_dotenv()


def load_config():
    """Load config.yaml from project root"""
    project_root = os.path.dirname(os.path.abspath(__file__))
    while not os.path.exists(os.path.join(project_root, "config.yaml")):
        project_root = os.path.dirname(project_root)
    config_path = os.path.join(project_root, "config.yaml")
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def load_athena_token():
    """
    Read Athena API token from athena_token.txt (gitignored).
    """
    # Find project root
    project_root = os.path.dirname(os.path.abspath(__file__))
    while not os.path.exists(os.path.join(project_root, "config.yaml")):
        project_root = os.path.dirname(project_root)

    token_path = os.path.join(project_root, "athena_token.txt")

    if os.path.exists(token_path):
        with open(token_path, "r") as f:
            token = f.read().strip()
        if token and token != "PASTE_YOUR_ATHENA_API_KEY_HERE":
            print("🔑 Athena API token loaded from athena_token.txt")
            return token

    # Fallback: environment variable
    token = os.getenv("ATHENA_API_KEY")
    if token:
        print("🔑 Athena API token loaded from environment variable")
        return token

    print("⚠️  Warning: Athena API token not found.")
    print("   Option 1 (recommended): Paste your token in athena_token.txt")
    print("   Option 2 (fallback): Set ATHENA_API_KEY in your .env file")
    return None


app_config = load_config()
athena_token = load_athena_token()
