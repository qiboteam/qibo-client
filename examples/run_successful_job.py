import time
from pathlib import Path

import qibo

from qibo_client import Client

# create the circuit you want to run
num_qubits = 5
circuit = qibo.Circuit(num_qubits)
circuit.add(qibo.gates.GPI2(0, 0.0))
circuit.add(qibo.gates.GPI2(1, 0.0))
circuit.add(qibo.gates.GPI2(2, 0.0))
circuit.add(qibo.gates.M(0, 1, 2))

wire_names = [f"A{i}" for i in range(1, num_qubits + 1)]

# circuit.wire_names = wire_names

circuit.draw()

# read the token from file
token_path = Path(__file__).parent / "token.txt"
token = token_path.read_text()

# authenticate to server through the client instance
client = Client(token)

# run the circuit
start = time.time()
job = client.run_circuit(circuit, device="tii-sim", project="personal", nshots=150)
print(job.result())
print(f"Program done in {time.time() - start:.4f}s")
