.. qibo-client documentation master file, created by
   sphinx-quickstart on Fri Dec 15 11:46:09 2023.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

What is qibo-client?
====================

Qibo-client is the front end interface to quantum computing labs using Qibo.

The main purpose of the project is to create a client tool written in python
able to launch quantum computations through HTTP.

Installation instructions
=========================

Install first the package dependencies with the following commands.

We recommend to start with a fresh virtual environment to avoid dependencies
conlficts with previously installed packages.

.. code-block:: bash

   $ python -m venv ./env
   source activate ./env/bin/activate

The qibo-client package can be installed through pip:

.. code-block:: bash

   pip install qibo-client


Tutorials
=========

Once installed, the provider allows to run quantum circuit computations on the
remote server.

.. note::
   In order to run jobs on the remote cluster it is mandatory to own a validated
   account. Please, sign up to
   `this link https://www.qrccluster.com`_ to obtain the needed
   token to run computations on the cluster.

The following example shows how to launch a computation on the TII cluster.
Remember to replace `your qibo token` string with your actual valid token
receive after registration.

.. code-block:: python

   >>> from qibo_client import TII
   >>> import qibo
   >>> circuit = qibo.models.QFT(5)
   >>> client = TII("your qibo token")
   >>> result = client.run_circuit(circuit, nshots=100, device="sim")
   >>> print(result)

API reference
=============

.. toctree::
   :maxdepth: 2
   :caption: Contents:

   modules


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
