import time
from pathlib import Path

from qibo_client import Client

# read the token from file
token_path = Path(__file__).parent / "token.txt"
token = token_path.read_text()

# authenticate to server through the client instance
start = time.time()
client = Client(token)
print(f"Program done in {time.time() - start:.4f}s")
