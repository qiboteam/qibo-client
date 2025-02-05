from pathlib import Path

import qibo

from qibo_client import Client

# In this example we will run a circuit on the real quantum device ``etna`` hosted at TII
# It is a 16 qubits device, with qubits named
wire_names = [
    "A1",
    "A2",
    "A3",
    "A4",
    "A5",
    "A6",
    "B1",
    "B2",
    "B3",
    "B4",
    "B5",
    "D1",
    "D2",
    "D3",
    "D4",
    "D5",
]

# read the token from file
token_path = Path(__file__).parent / "token.txt"
token = token_path.read_text().replace("\n", "")

# authenticate to the server
client = Client(token)

# We define the circuit, and in order to specify which qubits to run on
# we set the ``wire_names`` argument.
# To find the names of the qubits used by a device, visit https://cloud.qibo.science/devices/.
# By default (``verbatim=False``) you don't have to worry about the transpilation of the circuit, which
# is in fact automatically taken care of.
# If instead you would like the circuit to be executed exactly as you pass it, set ``verbatim=True``
# below, but keep in mind that only a restricted set of native gates is supported by each device.
# Sending gates not present in this set will result in an error.

circuit = qibo.Circuit(16, wire_names=wire_names)
circuit.add(qibo.gates.H(0))
circuit.add(qibo.gates.H(1))
circuit.add(qibo.gates.X(0))
circuit.add(qibo.gates.Z(1))
circuit.add(qibo.gates.M(0, 1))

circuit.draw()

job = client.run_circuit(
    circuit, device="etna", project="personal", nshots=150, verbatim=False
)

print(job.result(wait=3, verbose=True))
