import time
from pathlib import Path

import qibo

from qibo_client import Client

# create the circuit you want to run
circuit = qibo.models.QFT(5)

# read the token from file
token_path = Path(__file__).parent / "token.txt"
with open(token_path) as f:
    token = f.read()

# authenticate to server through the client instance
client = Client(token)

# run the circuit
print(f"{'*'*20}\nPost first circuit")
start = time.time()
result = client.run_circuit(circuit, nshots=100, device="sim")
print(result)
print(f"Program done in {time.time() - start:.4f}s")
