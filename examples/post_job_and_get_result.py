import qibo
import os
from tiiq_provider import TiiQProvider

# create the circuit you want to run
circuit = qibo.models.QFT(5)

# read the token from file
with open("token.txt", "r") as f:
    token = f.read()

# authenticate to server through the client instance
client = TiiQProvider(token)

# run the circuit
result = client.run_circuit(circuit, nshots=100, dev="qw5q_gold")
