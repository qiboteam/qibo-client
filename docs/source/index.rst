.. qibo-tii-provider documentation master file, created by
   sphinx-quickstart on Fri Dec 15 11:46:09 2023.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

Welcome to qibo-tii-provider's documentation!
=============================================

Qqibo-tii-provider is the front end interface to the Qibo labs.

The main purpose of the project is to create a client tool written in python
able to launch quantum computations through HTTP.

Example usage
=============

The following example shows how to launch a computation on the TII cluster.

.. code-block:: python

   >>> from qibo-tii-provider import TIIProvider
   >>> import qibo
   >>> circuit = qibo.models.QFT(5)
   >>> client = TIIProvider("your qibo token")
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
