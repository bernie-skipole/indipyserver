
import asyncio

import xml.etree.ElementTree as ET

from datetime import datetime, timezone

import logging
logger = logging.getLogger(__name__)


class RemoteConnection:

    # All xml data should be contained in one of the following tags
    TAGS = ('getProperties',
            'newTextVector',
            'newNumberVector',
            'newSwitchVector',
            'newBLOBVector',
            'enableBLOB',
            'message',
            'delProperty',
            'defSwitchVector',
            'setSwitchVector',
            'defLightVector',
            'setLightVector',
            'defTextVector',
            'setTextVector',
            'defNumberVector',
            'setNumberVector',
            'defBLOBVector',
            'setBLOBVector'
           )

    DEFTAGS = ( 'defSwitchVector',
                'defLightVector',
                'defTextVector',
                'defNumberVector',
                'defBLOBVector'
              )


    def __init__(self, host, port,
                       blob_enable,
                       debug_enable ):

        self.indihost = host
        self.indiport = port

        # These will be created when a connection is made using
        # await asyncio.open_connection(self.indihost, self.indiport)
        self._writer = None
        self._reader = None

        #  These can be True or False.
        self.blob_enable = blob_enable
        self.debug_enable = debug_enable

        # This is a set of devicenames learnt on this remote connection
        # populated as devices are learnt, and used to check for duplicate names
        self.devicenames = set()

        # An object for communicating is set when this remote is added to the server
        self._commsobj = None

        # and shutdown routine sets this to True to stop coroutines
        self._stop = False


    @property
    def connected(self):
        "property showing connected status, True or False"
        if self._writer is None:
            return False
        else:
            return True

    async def _clear_connection(self):
        "Clears a connection"
        try:
            if self._writer is not None:
                self._writer.close()
                await self._writer.wait_closed()
        except Exception:
            logger.exception("Exception report from RemoteConnection._clear_connection method")
        await self.warning(f"Connection closed on {self.indihost}:{self.indiport}")
        self._writer = None
        self._reader = None

    def __contains__(self, item):
        "So a devicename can easily be checked if it is in this driver"
        return item in self.devicenames


    async def _monitor_connection(self):
        """Flag connection made or failed messages into the server"""
        # create a flag so 'remote connection made' message is only set once
        isconnected = False
        while not self._stop:
            await asyncio.sleep(0.1)
            if self.connected:
                if isconnected:
                    continue
                isconnected = True
                # a new connection has been made, send a getProperties down the link
                await self.send_getProperties()
                # broadcast a message to everyone else connected to the server
                if self._commsobj is not None:
                    timestamp = datetime.now(tz=timezone.utc)
                    timestamp = timestamp.replace(tzinfo = None)
                    tstring = timestamp.isoformat(sep='T')
                    messagedata = ET.Element('message')
                    messagedata.set("timestamp", tstring)
                    messagedata.set("message", f"Remote connection made to {self.indihost}:{self.indiport}")
                    await self._commsobj.run_tx(messagedata)
            else:
                # The connection has failed
                if isconnected:
                    isconnected = False
                    self.devicenames.clear()
                    # broadcast a message to everyone else connected to the server
                    if self._commsobj is not None:
                        # send a message to everyone else connected to the server
                        timestamp = datetime.now(tz=timezone.utc)
                        timestamp = timestamp.replace(tzinfo = None)
                        tstring = timestamp.isoformat(sep='T')
                        messagedata = ET.Element('message')
                        messagedata.set("timestamp", tstring)
                        messagedata.set("message", f"Remote connection to {self.indihost}:{self.indiport} lost")
                        await self._commsobj.run_tx(messagedata)


    def shutdown(self):
        "Shuts down the client, sets the flag self._stop to True"
        self._stop = True
        if self._commsobj is not None:
            self._commsobj.shutdown()

    @property
    def stop(self):
        "returns self._stop, being the instruction to stop the client"
        return self._stop


    async def warning(self, message):
        """The given string message will be logged at level WARNING,
           and will be sent to all drivers and connections."""
        try:
            logger.warning(message)
            if self._commsobj is not None:
                timestamp = datetime.now(tz=timezone.utc)
                timestamp = timestamp.replace(tzinfo=None)
                xmldata = ET.fromstring(f"<message timestamp=\"{timestamp.isoformat(sep='T')}\" message=\"{message}\" />")
                await self._commsobj.run_tx_everywhere(xmldata)
        except Exception :
            logger.exception("Exception report from RemoteConnection.warning method")


    async def _create_connection(self):
        "Create a connection to an INDI port"
        try:
            while not self._stop:
                t1 = None
                t2 = None
                try:
                    # start by openning a connection
                    await self.warning(f"Attempting to connect to {self.indihost}:{self.indiport}")
                    self._reader, self._writer = await asyncio.open_connection(self.indihost, self.indiport)
                    await self.warning(f"Connected to {self.indihost}:{self.indiport}")
                    await self._run_rx()
                except ConnectionRefusedError:
                    await self.warning(f"Connection refused on {self.indihost}:{self.indiport}")
                except ConnectionError:
                    await self.warning(f"Connection Lost on {self.indihost}:{self.indiport}")
                except OSError:
                    await self.warning(f"Connection Error on {self.indihost}:{self.indiport}")
                except Exception:
                    logger.exception(f"Connection Error on {self.indihost}:{self.indiport}")
                    await self.warning("Connection failed")
                await self._clear_connection()
                if self._stop:
                    break
                else:
                    await self.warning("Connection failed, re-trying...")
                # wait five seconds before re-trying, but keep checking
                # that self._stop has not been set
                count = 0
                while not self._stop:
                    await asyncio.sleep(0.5)
                    count += 1
                    if count >= 10:
                        break
        except Exception:
            logger.exception("Exception report from RemoteConnection._create_connection method")
            raise
        finally:
            await self._clear_connection()
            self.shutdown()


    async def send(self, xmldata):
        """Transmits xmldata, which is an xml.etree.ElementTree object out on the remote connection"""
        if not self.connected:
            return
        if self._stop:
            return
        try:
            if not self.blob_enable:
                if (xmldata.tag == "setBLOBVector") or  (xmldata.tag == "newBLOBVector"):
                    # blobs not enabled
                    return
            # send it out on the port
            binarydata = ET.tostring(xmldata)
            self._writer.write(binarydata)
            await self._writer.drain()
            # data has been transmitted
            if logger.isEnabledFor(logging.DEBUG):
                self._logtx(xmldata)
        except Exception:
            logger.exception(f"Sending error from RemoteConnection.send method for {self.indihost}:{self.indiport}")
            await self._clear_connection()


    async def _readdata(self, xmldata):
        """Called from communications object with  xmldata from other drivers
           . clients and connections. Sends it towards the remote connection"""
        if xmldata.tag == "enableBLOB":
            return
        await self.send(xmldata)


    def _logtx(self, xmldata):
        "log tx data with level debug"
        if not self.debug_enable:
            return
        binarydata = ET.tostring(xmldata)
        logger.debug("TX:: " + binarydata.decode())


    def _logrx(self, rxdata):
        "log rx data"
        if not self.debug_enable:
            return
        binarydata = ET.tostring(rxdata)
        logger.debug("RX:: " + binarydata.decode())


    async def _run_rx(self):
        """Receive and dispatch INDI XML elements from the connection TCP stream.

        Uses XMLPullParser for streaming, chunk-at-a-time parsing with no
        user-space accumulation.  Because INDI sends a sequence of top-level
        XML elements with no document root, the stream is wrapped in a
        synthetic <root> element.  "end" events whose depth returns to 1
        (direct children of the wrapper) mark complete INDI messages.
        """

        ### Note: using ET.XMLPullParser as contributed by arisada in submission to indipyclient


        def _make_parser():
            p = ET.XMLPullParser(events=("start", "end"))
            p.feed(b"<root>")
            d = 0
            root_elem = None
            for ev, el in p.read_events():
                if ev == "start":
                    d += 1
                    root_elem = el   # the synthetic <root> Element
            return p, d, root_elem

        parser, depth, root_elem = _make_parser()
        try:
            while self.connected and (not self._stop):
                await asyncio.sleep(0)
                data = await self._reader.read(65536)
                try:
                    parser.feed(data)
                except ET.ParseError:
                    logger.error("RemoteConnection: XML parse error, resetting parser state")
                    parser, depth, root_elem = _make_parser()
                    continue
                for event, element in parser.read_events():
                    if event == "start":
                        depth += 1
                    elif event == "end":
                        depth -= 1
                        if depth == 1:
                            # A complete top-level INDI element is ready.
                            await self._dispatch_xml(element)
                            if root_elem is not None:
                                root_elem.remove(element)
                            await asyncio.sleep(0)
        except ConnectionError:
            # re-raise this without creating a report, as it probably indicates
            # a normal connection drop
            raise
        except Exception:
            # possibly some other error, so report it
            logger.exception("Exception report from RemoteConnection._run_rx")
            raise


    async def _dispatch_xml(self, xmldata):
        "_run_rx dispatches to here, which does final checking/logging and sends on to _commsobj.run_tx"

        if not self.connected or self._stop:
            return

        if xmldata.tag not in self.TAGS:
            return

        if (not self.blob_enable) and (xmldata.tag in ("setBLOBVector", "newBLOBVector") ):
            # blobs not enabled
            return

        devicename = xmldata.get("device")
        vectorname = xmldata.get("name")

        if xmldata.tag in self.DEFTAGS:
            if (devicename is None) or (vectorname is None):
                return
            if devicename not in self.devicenames:
                self.devicenames.add(devicename)
            if xmldata.tag == "defBLOBVector":
                # every time a defBLOBVector is received, send an enable BLOB instruction
                senddata = ET.Element('enableBLOB')
                senddata.set("device", devicename)
                senddata.set("name", vectorname)
                if self.blob_enable:
                    senddata.text = "Also"
                else:
                    senddata.text = "Never"
                await self.send(senddata)

        # and pass data to other drivers and connections
        if self._commsobj is not None:
            await self._commsobj.run_tx(xmldata)
        # log it, then continue with next block
        if logger.isEnabledFor(logging.DEBUG):
            self._logrx(xmldata)


    async def send_getProperties(self):
        """Sends a getProperties request"""
        if self.connected:
            xmldata = ET.Element('getProperties')
            xmldata.set("version", "1.7")
            await self.send(xmldata)


    async def asyncrun(self):
        "Await this method to run the connectiont."
        self._stop = False
        try:

            async with asyncio.TaskGroup() as tg:
                tg.create_task( self._create_connection() )
                tg.create_task( self._monitor_connection() )

        except Exception:
            logger.exception("Remote connection shutdown")
        finally:
            self._stop = True
