import time
from pathlib import Path

import qibo

from qibo_client import Client

# create the circuit you want to run
circuit = qibo.Circuit(17)
circuit.add(qibo.gates.GPI2(0, 0.0))
circuit.add(qibo.gates.GPI2(1, 0.0))
circuit.add(qibo.gates.GPI2(2, 0.0))
circuit.add(qibo.gates.M(0, 1, 2))

wire_names = [f"A{i}" for i in range(1, 18)]

circuit.wire_names = wire_names

circuit.draw()

# read the token from file
token_path = Path(__file__).parent / "token.txt"
token = token_path.read_text()

# authenticate to server through the client instance
client = Client(token)  # , url="http://localhost:8011")

# run the circuit
print(f"{'*'*20}\nPost circuit")
start = time.time()
job = client.run_circuit(circuit, device="tii-sim", project="personal", nshots=150)
print(f"Program done in {time.time() - start:.4f}s")
