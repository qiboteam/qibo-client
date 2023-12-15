# TiiQ Provider

## Install

Install first the package dependencies with the following commands.

We recommend to start with a fresh virtual environment to avoid dependencies
conlficts with previously installed packages.

```bash
python -m venv ./env
source activate ./env/bin/activate
```

The `TiiQ Provider` package can be installed through `pip`:

```bash
pip install git+ssh://git@github.com/qiboteam/qibo-tii-provider.git
```

## Quickstart

Once installed, the provider allows to run quantum circuit computations on the
TiiQ remote server.

:warning: Note: to run jobs on the remote cluster it is mandatory to own a
validated account.
Please, sign up to [this link](http://http://login.qrccluster.com:8010/) to
obtain the needed token to run computations on the cluster.

The following snippet provides a basic usage example.
Replace the `your-tii-qrc-token` string with your user token received during the
registration process.

```python
import qibo
from qibo_tii_provider import TIIProvider

# create the circuit you want to run
circuit = qibo.models.QFT(5)

# authenticate to server through the client instance
token = "your-tii-qrc-token"
client = TIIProvider(token)

# run the circuit
result = client.run_circuit(circuit, nshots=1000, dev="sim")
```
