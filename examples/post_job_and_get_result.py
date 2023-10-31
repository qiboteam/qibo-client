import qibo
from tiiq_provider import TiiProvider

# create the circuit you want to run
circuit = qibo.models.QFT(5)

# read the token from file
with open("token.txt", "r") as f:
    token = f.read()

# authenticate to server through the client instance
client = TiiProvider(token)

# run the circuit
result = client.run_circuit(circuit, nshots=100, device="qw5q_gold")
