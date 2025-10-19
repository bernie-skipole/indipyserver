# indipyserver
Server for the INDI protocol, written in Python

This package provides an IPyServer class used to serve the INDI protocol on a port.

INDI - Instrument Neutral Distributed Interface.

See https://en.wikipedia.org/wiki/Instrument_Neutral_Distributed_Interface

Drivers controlling instrumentation can be written, typically using the IPyDriver class from the associated indipydriver package, this server opens a port to which an INDI client can connect.

You would create a script something like:


    import asyncio
    from indipyserver import IPyServer
    import ... your own modules creating driver1, driver2 ...

    server = IPyServer(driver1, driver2, host="localhost", port=7624, maxconnections=5)
    asyncio.run(server.asyncrun())

A connected client can then control all the drivers. The above illustrates multiple drivers can be served, however it could equally be one or none at all.


## Third party drivers

IPyServer can also run third party INDI drivers created with other languages or tools, using an add_exdriver method to include executable drivers.

For example, using drivers available from indilib:

    import asyncio
    from indipyserver import IPyServer

    server = IPyServer(host="localhost", port=7624, maxconnections=5)

    server.add_exdriver("indi_simulator_telescope")
    server.add_exdriver("indi_simulator_ccd")
    asyncio.run(server.asyncrun())


Please note: The author has no relationship with indilib, these indipyserver and indipydriver packages are independently developed implementations. However they were developed with reference to the INDI version 1.7 specification, and are intended to interwork with other implementations that also meets that spec.


## Networked instruments

IPyServer also has an add_remote method which can be used to add connections to remote servers, creating a tree network of servers:

    import asyncio
    from indipyserver import IPyServer
    import ... your own modules creating DriverA, DriverB ...

    server = IPyServer(DriverA, DriverB, host="localhost", port=7624, maxconnections=5)

    server.add_remote(host="nameofserverB", port=7624, blob_enable=True)
    server.add_remote(host="nameofserverC", port=7624, blob_enable=True)

    asyncio.run(server.asyncrun())


![INDI Network](https://github.com/bernie-skipole/indipyserver/raw/main/docs/source/usage/images/rem2.png)

With such a layout, the client can control all the instruments.

Drivers made with indipydriver, third party executable drivers and remote connections can all be served together.

Further documentation can be found at:

https://indipyserver.readthedocs.io/en/latest/index.html
