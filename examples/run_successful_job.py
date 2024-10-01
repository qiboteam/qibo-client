import time
from pathlib import Path

import qibo

from qibo_client import Client

# create the circuit you want to run
c = qibo.Circuit(11)
c.add(qibo.gates.GPI2(0, 0))
c.add(qibo.gates.M(10))
result = c(nshots=100)

print(c.draw())

# read the token from file
token_path = Path(__file__).parent / "token.txt"
token = token_path.read_text()

# authenticate to server through the client instance
client = Client(token)

# run the circuit
print(f"{'*'*20}\nPost circuit")
start = time.time()
job = client.run_circuit(circuit, nshots=100, device="sim")
print(job.result())
print(f"Program done in {time.time() - start:.4f}s")
