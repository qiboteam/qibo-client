import qibo

from qibo_tii_provider import TIIProvider

# create the circuit you want to run
circuit = qibo.models.QFT(5)

# read the token from file
with open("token.txt") as f:
    token = f.read()

# authenticate to server through the client instance
client = TIIProvider(token)

# run the circuit
print(f"{'*'*20}\nPost first circuit")
result = client.run_circuit(circuit, nshots=100, device="sim")

print(result)
