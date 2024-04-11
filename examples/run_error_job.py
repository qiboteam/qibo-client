from pathlib import Path
import qibo

from qibo_client import TII

# create the circuit you want to run
circuit = qibo.models.QFT(11)

# read the token from file
token_path = Path(__file__).parent / "token.txt"
with open(token_path) as f:
    token = f.read()

# authenticate to server through the client instance
client = TII(token)

# run the circuit
print(f"{'*'*20}\nPost first circuit")
result = client.run_circuit(circuit, nshots=100, device="sim")

print(result)
