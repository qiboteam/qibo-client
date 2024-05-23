# Qibo client

The documentation of the project can be found
[here](https://qibo.science/qibo-client/stable/).

## Install

Install first the package dependencies with the following commands.

We recommend to start with a fresh virtual environment to avoid dependencies
conflicts with previously installed packages.

```bash
python -m venv ./env
source activate ./env/bin/activate
```

The `qibo-client` package can be installed through `pip`:

```bash
pip install qibo-client
```

## Quick start

Once installed, the provider allows to run quantum circuit computations on the
TiiQ remote server.

:warning: Note: to run jobs on the remote cluster it is mandatory to own a
validated account.
Please, sign up to [this link](https://cloud.qibo.science) to
obtain the needed token to run computations on the cluster.

The following snippet provides a basic usage example.
Replace the `your-tii-qrc-token` string with your user token received during the
registration process.

```python
import qibo
import qibo_client

# create the circuit you want to run
circuit = qibo.models.QFT(5)

# authenticate to server through the client instance
token = "your-tii-qrc-token"
client = qibo_client.TII(token)

# run the circuit
result = client.run_circuit(circuit, nshots=1000, device="sim")
```
