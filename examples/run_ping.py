import time
from pathlib import Path

from qibo_client import TII

# read the token from file
token_path = Path(__file__).parent / "token.txt"
with open(token_path) as f:
    token = f.read()

# authenticate to server through the client instance
start = time.time()
client = TII(token)
print(f"Program done in {time.time() - start:.4f}s")
