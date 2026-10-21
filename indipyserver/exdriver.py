
import asyncio, copy

import xml.etree.ElementTree as ET

import logging
logger = logging.getLogger(__name__)




class ExVector:

    def __init__(self, name, deftag):
        "Object which only holds a name and vectortype"
        self.name = name
        self.vectortype = deftag[3:]


class ExDriver:

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

    NEWTAGS = ('newTextVector',
               'newNumberVector',
               'newSwitchVector',
               'newBLOBVector'
              )


    def __init__(self, program, *args, debug_enable=False):
        "Executes a third party indi driver, communicates by stdin stdout"

        self.program = program
        self.args = args
        self.debug_enable = debug_enable
        self.proc = None

        # An object for communicating is set when this driver is added to the server
        self._commsobj = None

        # This dictionary will be populated with devicename:{vectorname:vector}
        # where vector is an ExVector object
        self.devicenames = {}

        self.snoopall = False           # gets set to True if it is snooping everything
        self.snoopdevices = set()       # gets set to a set of device names
        self.snoopvectors = set()       # gets set to a set of (devicename,vectorname) tuples

        self._remainder = b""    # Used to store intermediate data
        self._stop = False       # Gets set to True to stop communications


    def shutdown(self):
        self._stop = True
        if self._commsobj is not None:
            self._commsobj.shutdown()
        if self.proc is not None:
            self.proc.terminate()


    def __contains__(self, item):
        "So a devicename can easily be checked if it is in this driver"
        return item in self.devicenames


    async def _readdata(self, root):
        """Called from communications object with received xmldata
           and sends it towards the driver"""

        if self._stop:
            return

        if root.tag == "enableBLOB":
            return

        if root.tag == "getProperties":
            await self.xml_to_ext(root)
            return

        devicename = root.get("device")
        propertyname = root.get("name")

        if root.tag in self.NEWTAGS:
            if devicename is None:
                # invalid
                return
            if devicename in self.devicenames:
                await self.xml_to_ext(root)
                return
            else:
                # not for this driver
                return

        # so not in NEWTAGS
        # Check if this driver is snooping on this device/vector
        if self.snoopall:
            await self.xml_to_ext(root)
        elif devicename and (devicename in self.snoopdevices):
            await self.xml_to_ext(root)
        elif devicename and propertyname and ((devicename, propertyname) in self.snoopvectors):
            await self.xml_to_ext(root)


    async def xml_to_ext(self, root):
        "Pass data to the external driver"

        binarydata = ET.tostring(root)

        # log the received data
        if logger.isEnabledFor(logging.DEBUG) and self.debug_enable:
            logger.debug(f"RX:: {binarydata.decode('utf-8')}")

        binarydata += b"\n"
        self.proc.stdin.write(binarydata)
        await self.proc.stdin.drain()



    async def _run_tx(self):
        """Get data from driver and dispatch INDI XML elements.

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
            while not self._stop:
                await asyncio.sleep(0)
                data = await self.proc.stdout.read(65536)
                try:
                    parser.feed(data)
                except ET.ParseError:
                    logger.error("ExDriver: XML parse error, resetting parser state")
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
                            await asyncio.sleep(0)
        except Exception:
            logger.exception("Exception report from ExDriver._run_tx")
            raise


    async def _dispatch_xml(self, xmldata):
        "_run_tx dispatches to here, which does final checking/logging and sends on to _commsobj.run_tx"

        if self._stop:
            return

        if xmldata.tag not in self.TAGS:
            return

        devicename = xmldata.get("device")
        if devicename and xmldata.tag in self.DEFTAGS:
            # its a definition
            if devicename not in self.devicenames:
                self.devicenames[devicename] = {}
            vectorname = xmldata.get("name")
            if vectorname:
                if vectorname not in self.devicenames[devicename]:
                    # add this vector to the self.devicenames[devicename] dictionary
                    self.devicenames[devicename][vectorname] = ExVector(vectorname, xmldata.tag)
        # check for a getProperties being sent, record what is being snooped
        if xmldata.tag == "getProperties":
            vectorname = xmldata.get("name")
            if devicename is None:
                self.snoopall = True
            elif vectorname is None:
                self.snoopdevices.add(devicename)
            else:
                self.snoopvectors.add((devicename,vectorname))

        # transmit this data towards the server
        await self._commsobj.run_tx(xmldata)

        if logger.isEnabledFor(logging.DEBUG) and self.debug_enable:
            binarydata = ET.tostring(xmldata)
            logger.debug(f"TX:: {binarydata.decode('utf-8')}")


    async def _run_err(self):
        """gets binary string of data from exdriver proc.stderr
           and logs it to logging.error."""

        while not self._stop:
            bindata = await self.proc.stderr.readline()
            if not bindata:
                await asyncio.sleep(0.02)
                continue
            logger.error(bindata.decode('utf-8'))


    async def asyncrun(self):
        "Runs the external driver"

        self._stop = False

        try:

            self.proc = await asyncio.create_subprocess_exec(self.program,
                                                             *self.args,
                                                       stdin=asyncio.subprocess.PIPE,
                                                       stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.PIPE)

            # wait for external program to start
            await asyncio.sleep(0.1)
            # send a getProperties into the driver
            await self._readdata( ET.fromstring("""<getProperties version="1.7" />""") )

            async with asyncio.TaskGroup() as tg:
                tg.create_task( self._run_tx() )           # Get data from driver and send it towards the server
                tg.create_task( self._run_err() )          # data from exdriver proc.stderr and logs it to logging.error
        except Exception:
            logger.exception("Driver shutdown")
        finally:
            self._stop = True
