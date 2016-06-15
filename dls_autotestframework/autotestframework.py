#!/bin/env dls-python
'''
Automatic testing framework for the continuous integration/test facility.

The framework is based on the pyUnit library with extensions that generate
Test Any Protocol (TAP) output.  It is capable of running a test suite against
a number of user definable targets, generating a test suite report, an EPICS
database coverage report and (where possible) a protocol coverage report.


'''
from pkg_resources import require
require('numpy')
require('cothread')
import cothread
from cothread import *
from cothread.catools import *
import cothread.coselect
import re, os, socket, sys
import inspect
import shlex
from datetime import *
import unittest
import subprocess
import time
import traceback
import string
import types
import Queue
import socket
from runtests import *
from xml.dom.minidom import *
import urllib
import pyclbr
import traceback
import telnetlib
import getopt
import fcntl

helpText = """
Execute an automatic test suite.  Options are:
-h            Print this help
-d <level>    Sets the diagnostic level, 0..9.
-b            Performs a build before running the tests.
-i            Run IOC before running the tests.
-x <file>     Creates a JUNIT compatible XML results file
-g            Runs the GUI
-t <target>   Tests only on specified <target>
--hudson      The test suite is running under Hudson
-c <case>     Execute this case, may be specified multiple times
"""

def getClassName(object):
    '''Returns the class name of an object'''
    stuff = str(object.__class__)
    className = string.split(stuff, '.')[1]
    className = string.split(className, "'")[0]
    return className

# Phase constants
numPhases = 5
phaseVeryEarly = 0
phaseEarly = 1
phaseNormal = 2
phaseLate = 3
phaseVeryLate = 4

def killProcessAndChildren(pid):
    # First, kill off all the children
    str = subprocess.Popen('ps -o pid,ppid ax', shell=True, stdout=subprocess.PIPE).communicate()[0]
    lines = str.split('\n')[1:]
    for line in lines:
        pids = line.strip().split()
        if len(pids) == 2 and int(pids[1]) == pid:
            killProcessAndChildren(int(pids[0]))
    # If the parent still exists, kill it too
    str = subprocess.Popen('ps %s' % pid, shell=True, stdout=subprocess.PIPE).communicate()[0]
    lines = str.split('\n')
    if len(lines) > 1:
        p = subprocess.Popen("kill -KILL %d" % pid, shell=True)
        p.wait()

################################################
# Epics database record
class EpicsRecord(object):
    '''Represents an EPICS database record.'''

    def __init__(self, identifier, record, suite):
        self.identifier = identifier.strip('"')
        self.record = record
        self.fields = {}
        self.values = set([])
        self.valMonitor = None
        self.jogfMonitor = None
        self.jogrMonitor = None
        self.dmovMonitor = None
        self.rbvMonitor = None
        self.suite = suite

    def __str__(self):
        return "[%s, %s, %s]" % (self.identifier, self.record, self.fields)

    def addField(self, name, value):
        '''Adds a field to the EPICS record.  Strips double quotes from the value.'''
        self.fields[name] = value.strip('"')

    def monitorInd(self, value):
        '''Receives data from monitors placed on the record.'''
        self.suite.diagnostic("Pv %s=%s" % (value.name, value), 2)
        parts = value.name.split(".")
        if len(parts) == 1 or parts[1] == "VAL":
            # The value monitor
            if len(self.values) < 32:
                self.values.add(str(value))

    def createMonitors(self):
        '''Create monitors appropriate to the record type so
        that we can make an attempt at estimating the coverage.'''
        # Lets always have one on the VAL field
        self.valMonitor = camonitor(self.identifier, self.monitorInd)
        if self.record == "motor":
            self.dmovMonitor = camonitor(self.identifier+".DMOV", self.monitorInd)
            self.jogfMonitor = camonitor(self.identifier+".JOGF", self.monitorInd)
            self.jogrMonitor = camonitor(self.identifier+".JOGR", self.monitorInd)
            self.rbvMonitor = camonitor(self.identifier+".RBV", self.monitorInd)

    def coverageReport(self):
        '''Generates a coverage report for this record.'''
        text = "    %s(%s): " % (self.identifier, self.record)
        if self.record == "mbbo":
            text += self.mbbxCoverageReport()
        elif self.record == "mbbi":
            text += self.mbbxCoverageReport()
        elif self.record == "mbbiDirect":
            text += self.mbbxDirectCoverageReport()
        elif self.record == "mbboDirect":
            text += self.mbbxDirectCoverageReport()
        elif self.record == "bi":
            text += self.bxCoverageReport()
        elif self.record == "bo":
            text += self.bxCoverageReport()
        elif self.record == "longin":
            text += self.longxCoverageReport()
        elif self.record == "longout":
            text += self.longxCoverageReport()
        elif self.record == "calcout":
            text += self.calcxCoverageReport()
        elif self.record == "calc":
            text += self.calcxCoverageReport()
        elif self.record == "ao":
            text += self.axCoverageReport()
        elif self.record == "ai":
            text += self.axCoverageReport()
        elif self.record == "fanout":
            text += self.fanoutCoverageReport()
        elif self.record == "motor":
            text += self.motorCoverageReport()
        else:
            text += "unknown record type"
        text += "\n"
        return text

    def mbbxCoverageReport(self):
        '''Record types mbbo and mbbi.
        We expect all the values defined by the value fields to
        have occurred.'''
        text = ""
        names = ["ZRVL", "ONVL", "TWVL", "THVL", "FRVL", "FVVL", "SXVL",
            "SVVL", "EIVL", "NIVL", "TEVL", "ELVL", "TVVL", "TTVL", "FTVL", "FFVL"]
        for val in range(16):
            if names[val] in self.fields:
                if not str(val) in self.values:
                    if len(text) == 0:
                        text += "values not covered: "
                    else:
                        text += ", "
                    text += str(val)
        if len(text) == 0:
            text += "ok"
        return text

    def mbbxDirectCoverageReport(self):
        '''Record types mbbodirect and mbbidirect.
        We expect all the values defined by the number of bits field.'''
        text = ""
        numBits = 16
        if "NOBT" in self.fields:
            numBits = int(self.fields["NOBT"])
        # If range too big or not present
        text = ""
        if numBits > 4:
            if len(self.values) < 2:
                text = "not touched"
        else:
            for val in range(2**numBits):
                if not str(val) in self.values:
                    if len(text) == 0:
                        text += "values not covered: "
                    else:
                        text += ", "
                    text += str(val)
        if len(text) == 0:
            text += "ok"
        return text

    def bxCoverageReport(self):
        '''Record types bo and bi.
        We expect the values 0 and 1 to have occurred.'''
        text = ""
        for val in range(2):
            if not str(val) in self.values:
                if len(text) == 0:
                    text += "values not covered: "
                else:
                    text += ", "
                text += str(val)
        if len(text) == 0:
            text += "ok"
        return text

    def longxCoverageReport(self):
        '''Record types longin and longout.
        If the defined range covers 32 values or less, require
        all the values to have occurred.  Otherwise require
        just two values (ie. it changed during the test).
        Work out the configured range.'''
        start = 0
        length = 0
        if "LOPR" in self.fields and "HOPR" in self.fields:
            start = int(self.fields["LOPR"])
            length = int(self.fields["HOPR"]) - start
            if length < 0 or length > 32:
                length = 0
        # If range too big or not present
        text = ""
        if length == 0:
            if len(self.values) < 2:
                text = "not touched"
        else:
            for val in range(start, start+length):
                if not str(val) in self.values:
                    if len(text) == 0:
                        text += "values not covered: "
                    else:
                        text += ", "
                    text += str(val)
        if len(text) == 0:
            text += "ok"
        return text

    def calcxCoverageReport(self):
        '''Record types calc and calcout.
        All we can really do is check that the output changed
        during the test.'''
        if len(self.values) < 2:
            text = "not touched"
        else:
            text = "ok"
        return text

    def axCoverageReport(self):
        '''Record types ai and ao.
        Just check that the output changed during the test.
        We may be able to do something with the defined ranges later.'''
        if len(self.values) < 2:
            text = "not touched"
        else:
            text = "ok"
        return text

    def motorCoverageReport(self):
        '''Record type motor.
        Just check that the output changed during the test.
        We may be able to do something with other fields later.'''
        if len(self.values) < 2:
            text = "not touched"
        else:
            text = "ok"
        return text

    def fanoutCoverageReport(self):
        '''Record type fanout.
        I don't think there's anything we can do.
        Is there some way of detecting that the records
        at the other end of the output links are processed?'''
        text = "ok"
        return text

    def clearCoverage(self):
        '''Clears all stored coverage information for the record.'''
        self.values = set([])

################################################
# Epics database
class EpicsDatabase(object):
    '''Represents the whole EPICS database'''

    def __init__(self, suite):
        self.records = {}
        self.suite = suite

    def __str__(self):
        result = ""
        for key, record in self.records.iteritems():
            result = result + "\n" + str(record)
        return result

    def __len__(self):
        return len(self.records)

    def createMonitors(self):
        '''Create monitors for all the records in the database.'''
        for key, record in self.records.iteritems():
            record.createMonitors()

    def clearCoverage(self):
        '''Clear the coverage information of all the records in the database.'''
        for key, record in self.records.iteritems():
            record.clearCoverage()

    def coverageReport(self):
        '''Generate a coverage report for the database'''
        text = ""
        for key, record in self.records.iteritems():
            text += record.coverageReport()
        return text

    def addRecord(self, identifier, record):
        '''Add a record into the database.'''
        item = EpicsRecord(identifier, record, self.suite)
        self.records[identifier] = item
        return item

    def getToken(self):
        '''Returns the next token of the database text.'''
        token = self.lexer.get_token()
        return str(token)

    def readFile(self, filename):
        '''Reads and parses the database file.'''
        try:
            rFile = open(filename, "r")
        except IOError:
            print "Failed to open file \"%s\"" % filename
        else:
            self.lexer = shlex.shlex(rFile)
            self.lexer.whitespace_split = False
            self.parseDatabase()

    def parseDatabase(self):
        '''Parse the database file.'''
        token = self.getToken()
        while token == "record" or token == "grecord":
            self.parseRecord()
            token = self.getToken()

    def parseRecord(self):
        '''Parses a database record header.'''
        token = self.getToken()
        if token == "(":
            record = self.getToken()
            token = self.getToken()
            if token == ',':
                identifier = self.getToken()
                token = self.getToken()
                if token == ")":
                    self.parseRecordBody(self.addRecord(identifier, record))

    def parseRecordBody(self, item):
        '''Parses a record body.'''
        token = self.getToken()
        if token == "{":
            token = self.getToken()
            while token == "field":
                self.parseField(item)
                token = self.getToken()
            if token == "}":
                pass

    def parseField(self, item):
        '''Parses a record field.'''
        token = self.getToken()
        if token == "(":
            name = self.getToken()
            token = self.getToken()
            if token == ',':
                value = self.getToken()
                token = self.getToken()
                if token == ")":
                    item.addField(name, value)

################################################
# Test case super class
class TestCase(unittest.TestCase):
    '''The automatic test framework test case super class.  All test
    cases should be derived from this class.  It provides the
    API that test cases can use during tests.'''

    def __init__(self, suite):
        # Construct the super class
        unittest.TestCase.__init__(self)
        # Initialise things
        self.suite = suite
        self.suite.addTest(self)
        self.throwFail = True

    def fail(self, message):
        if self.throwFail:
            unittest.TestCase.fail(self, message)
        else:
            self.diagnostic('FAIL: %s' % message, 1)

    def getPv(self, pv, **kargs):
        '''Gets a value from a PV.  Can only throw fail exceptions
        when the underlying caget fails, no checking of the retrieved
        value is performed.'''
        d = caget(pv, throw=False, **kargs)
        if not d.ok:
            self.fail("caget failed: " + str(d))
        return d

    def putPv(self, pv, value, wait=True, **kargs):
        '''Sends a value to a PV.  Can throw a fail exceptions
        when the underlying caput fails.'''
        rc = caput(pv, value, wait=wait, throw=False, **kargs)
        if not rc:
            self.fail("caput failed: " + str(rc))

    def command(self, devName, text):
        '''Sends a command to a simulation device.'''
        self.suite.command(devName, text)

    def simulation(self, devName):
        '''Return simulation device.'''
        return self.suite.simulation(devName)

    def entity(self, name):
        '''Return an entity object.'''
        return self.suite.entity(name)

    def simulationDevicePresent(self, devName):
        '''Returns True if the device simulation is present.'''
        return self.suite.simulationDevicePresent(devName)

    def verify(self, left, right):
        '''Throws a fail exception if the two values are not identical.'''
        if left != right:
            self.fail("%s != %s" % (left, right))

    def verifyInRange(self, value, lower, upper):
        '''Throws a fail exception if the value does not lie within
        the specified range.'''
        if value < lower or value > upper:
            self.fail("%s not in %s..%s" % (value, lower, upper))

    def verifyPv(self, pv, value, **kargs):
        '''Reads the specified PV and checks it has the specified value.
        Throws a fail exception if the caget or the check fails.'''
        d = self.getPv(pv, **kargs)
        if d != value:
            self.fail("%s[%s] != %s" % (pv, d, value))
        return d

    def verifyPvFloat(self, pv, value, delta, datatype=float, **kargs):
        '''Reads the specified PV and checks it has the specified value
        within the given error.  Usually used for checking floating point
        values where equality is unreliable.  Throws a fail exception if
        the caget or the check fails.'''
        d = self.getPv(pv, datatype=datatype, **kargs)
        if d < (value - delta) or d > (value + delta):
            self.fail("%s[%s] != %s +/-%s" % (pv, d, value, delta))
        return d

    def verifyPvInRange(self, pv, lower, upper, **kargs):
        '''Reads the specified PV and checks itis within the given range.
        Throws a fail exception if the caget or the check fails.'''
        d = self.getPv(pv, **kargs)
        if d < lower or d > upper:
            self.fail("%s[%s] not in %s..%s" % (pv, d, lower, upper))
        return d

    def recvResponse(self, devName, rsp, numArgs=-1):
        '''Try to receive a response from the simulation.'''
        return self.suite.recvResponse(devName, rsp, numArgs)

    def sleep(self, time):
        '''Sleep for the specified number of seconds.'''
        Sleep(time)

    def diagnostic(self, text, level=0):
        '''Write the text as a TAP diagnostic line.'''
        self.suite.diagnostic(text, level)

    def param(self, name):
        '''Return a parameter.'''
        return self.suite.param(name)

    def verifyIocTelnet(self, text, timeout=0.0):
        '''Verifies that the text has been received since the last
           time the receive buffer was cleared.  Will wait for up
           to the timeout for the text to be received. '''
        if self.suite.target.iocTelnetConnection is None:
            self.fail('No telnet connection to IOC')
        elif self.suite.target.iocTelnetConnection.waitFor(text, timeout):
            pass
        else:
            self.fail('Timeout waiting for %s' % repr(text))

    def writeIocTelnet(self, text):
        '''Writes the text to the IOC telnet port.'''
        if self.suite.target.iocTelnetConnection is None:
            self.fail('No telnet connection to IOC')
        else:
            self.suite.target.iocTelnetConnection.write(text)

    def clearIocTelnet(self):
        '''Clears the IOC telnet ports receive buffer.'''
        if self.suite.target.iocTelnetConnection is None:
            self.fail('No telnet connection to IOC')
        else:
            self.suite.target.iocTelnetConnection.clearReceivedText()

    def moveMotorTo(self, pv, val):
        # Send the motor to the required position.  Note that the
        # operation of the DONE flag is somewhat unreliable, it will
        # often perform false transitions.  The MOVN flag is used
        # with the DONE flag to try and avoid false triggering of
        # the movement stages, especially the wait for the move to begin.
        self.putPv(pv, val, wait=False)
        # Wait for the move to start
        timeout = 10
        done = self.getPv(pv+".DMOV")
        movn = self.getPv(pv+".MOVN")
        while (done or not movn) and timeout > 0:
            self.sleep(1.0)
            timeout -= 1
            movn = self.getPv(pv+".MOVN")
            done = self.getPv(pv+".DMOV")
        # Wait for the move to complete
        timeout = 100
        done = self.getPv(pv+".DMOV")
        movn = self.getPv(pv+".MOVN")
        while (not done or movn) and timeout > 0:
            self.sleep(1.0)
            timeout -= 1
            movn = self.getPv(pv+".MOVN")
            done = self.getPv(pv+".DMOV")
        # If the move did not complete, fail
        if not done:
            self.fail("%s: Move to %s did not complete" % (pv, val))

    def verifyIocStdout(self, ioc, text, wait=0, discard=True):
        if not ioc.verifyStdout(text, wait, discard):
            self.fail('Could not find %s in %s.stdout' % (repr(text), ioc.name))

    def verifyIocStderr(self, ioc, text, wait=0, discard=True):
        if not ioc.verifyStderr(text, wait, discard):
            self.fail('Could not find %s in %s.stderr' % (repr(text), ioc.name))

################################################
# Test suite super class
class TestSuite(unittest.TestSuite):
    '''The automatic test framework test suite super class.  Each test suite should
    provide a class derived from this one that defines the cases to
    run and the targets to use.'''

    def __init__(self, diagnosticLevel=9):
        # Construct the super class
        unittest.TestSuite.__init__(self)
        # Initialise
        self.targets = []
        self.diagnosticLevel = diagnosticLevel
        self.doBuild = False
        self.runIoc = False
        self.runGui = False
        self.runSimulation = False
        self.onlyTarget = None
        self.selectedCases = []
        self.results = None
        self.serverSocketName = None
        self.resultSocket = None
        self.xmlFileName = None
        self.underHudson = False
        # Parse any command line arguments
        if self.processArguments():
            # Try to open a connection to the results server
            if self.serverSocketName is not None:
                self.resultSocket = socket.socket(socket.AF_UNIX)
                self.resultSocket.connect((self.serverSocketName))
            # Get the sub-class to define the tests and environment
            self.createTests()
            # Now run the tests
            self.runTests()

    def processArguments(self):
        """Process the command line arguments.
        """
        try:
            opts, args = getopt.gnu_getopt(sys.argv[1:], 'd:t:c:r:hbigex:',
                ['help', 'hudson', 'target=', 'case=', 'build', 'ioc', 'gui', 'simulation'])
        except getopt.GetoptError, err:
            return False
        for o, a in opts:
            if o in ('-h', '--help'):
                return False
            elif o in ('-d'):
                self.diagnosticLevel = int(a)
            elif o in ('-t', '--target'):
                self.onlyTarget = a
            elif o in ('-c', '--case'):
                self.selectedCases.append(a)
            elif o in ('-r'):
                self.serverSocketName = a
            elif o in ('-b', '--build'):
                self.doBuild = True
            elif o in ('-i', '--ioc'):
                self.runIoc = True
            elif o in ('-g', '--gui'):
                self.runGui = True
            elif o in ('-e', '--simulation'):
                self.runSimulation = True
            elif o in ('-x'):
                self.xmlFileName = a
            elif o in ('--hudson'):
                self.underHudson = True
        if len(args) > 0:
            print 'Too many arguments.'
            return False
        return True

    def addTarget(self, target):
        '''Add a target to the test suite.'''
        self.targets.append(target)

    def reportCoverage(self):
        '''Generate the coverage reports from the test run.'''
        self.diagnostic(self.target.reportCoverage())

    def autoCreateTests(self, moduleName):
        """
        Automatically create TestCase objects from the moduleName module.
        Any classes not of type TestCase, or which have a name ending
        in 'Base' are not instantiated.
        Call this function in the createTests method in a derived class
        of type TestSuite.

        None autoCreateTests(moduleName)
        """
        classes = pyclbr.readmodule(moduleName)
        for c in classes:
            if not (c.endswith("Base")):
                classobj = eval(c)
                if (issubclass(classobj, TestCase)):
                    classinstance = classobj(self)

    def addTest(self, test):
        '''Add a test case to the suite.'''
        className = getClassName(test)
        if not self.selectedCases or className in self.selectedCases:
            unittest.TestSuite.addTest(self, test)

    def command(self, devName, text):
        '''Send a command to a simulation device.'''
        self.target.command(devName, text)

    def simulation(self, devName):
        '''Return simulation device.'''
        return self.target.simulation(devName)

    def entity(self, name):
        '''Return an entity object.'''
        return self.target.getEntity(name)

    def simulationDevicePresent(self, devName):
        '''Returns True if the simulation device is present in the current target'''
        return self.target.simulationDevicePresent(devName)

    def recvResponse(self, devName, rsp, numArgs=-1):
        '''Try to receive a response from a simulation device.'''
        return self.target.recvResponse(devName, rsp, numArgs)

    def runTests(self):
        '''Runs this suite's tests.'''
        for self.target in self.targets:
            if self.onlyTarget is None or self.onlyTarget == self.target.name:
                self.target.prepare(self.doBuild, self.runIoc, self.runGui,
                    self.diagnosticLevel, self.runSimulation, self.underHudson, self)
                self.diagnostic("==============================")
                self.diagnostic("***** %s *****" % getClassName(self))
                self.results = TestResult(self.countTestCases(), sys.stdout, self)
                self.run(self.results)
                self.diagnostic("==============================")
                self.results.report()
                self.reportCoverage()
                self.results = None
                self.target.destroy()

    def diagnostic(self, text, level=0):
        '''Outputs text as a TAP diagnostic line.'''
        if self.results is not None and level <= self.diagnosticLevel:
            lines = string.split(text, '\n')
            for line in lines:
                self.results.diagnostic(line)

    def param(self, name):
        '''Return a parameter.'''
        return self.target.param(name)

    def sendToResultServer(self, text):
        if self.resultSocket is not None:
            self.resultSocket.send(text)

################################################
# Test results class
class TestResult(unittest.TestResult):
    '''The automatic test framework test result class.  It outputs text that
    conforms to the TAP protocol specification to a given stream.'''

    def __init__(self, numCases, stream, suite):
        unittest.TestResult.__init__(self)
        self.stream = stream
        self.numCases = numCases
        self.startTime = time.time()
        self.caseStartTime = self.startTime
        self.failures = []
        self.suite = suite
        self.xmlDoc = None
        self.xmlTop = None
        if suite.xmlFileName is not None:
            self.xmlDoc = getDOMImplementation().createDocument(None, "testsuite", None)
            self.xmlTop = self.xmlDoc.documentElement
        self.outputText("1..%s\n" % self.numCases)

    def getDescription(self, test):
        '''Return a description of a test.'''
        return test.shortDescription() or str(test)

    def addSuccess(self, test):
        '''Called when a test case has run successfully.'''
        self.outputText("ok %s - %s : %s\n" % (self.testsRun, getClassName(test), self.getDescription(test)))
        if self.xmlTop is not None:
            element = self.createCaseXmlElement(test)

    def createCaseXmlElement(self, test):
        # Calculate the elapsed time
        stopTime = time.time()
        timeTaken = float(stopTime - self.caseStartTime)
        self.caseStartTime = stopTime
        # Create the XML element
        element = self.xmlDoc.createElement("testcase")
        self.xmlTop.appendChild(element)
        element.setAttribute("classname", getClassName(self.suite))
        element.setAttribute("name", getClassName(test))
        element.setAttribute("time", str(timeTaken))
        return element

    def addError(self, test, err):
        '''Called when a test case fails due to an unexpected exception.'''
        self.addFailure(test, err)
        if err[0] is KeyboardInterrupt:
            self.shouldStop = 1

    def addFailure(self, test, err):
        '''Called when a test case fails.'''
        self.failures.append(self.testsRun)
        for text in apply(traceback.format_exception, err):
            for line in string.split(text, "\n"):
                self.outputText("# %s\n" % line)
        self.outputText("not ok %s - %s : %s\n" % (self.testsRun, getClassName(test), self.getDescription(test)))
        if self.xmlTop is not None:
            element = self.createCaseXmlElement(test)
            errorElement = self.xmlDoc.createElement("error")
            element.appendChild(errorElement)
            message = traceback.format_exception_only(err[0], err[1])[-1].strip()
            errorElement.setAttribute("message", message)
            textList = traceback.format_exception(err[0], err[1], err[2])
            text = ""
            for line in textList:
                text += line + '\n'
            textElement = self.xmlDoc.createTextNode(text)
            errorElement.appendChild(textElement)

    def report(self):
        '''Output the suite summary in TAP Test::Harness style to stdout (not the stream)'''
        # Calculate the elapsed time
        stopTime = time.time()
        timeTaken = float(stopTime - self.startTime)
        text = ""
        # Report any failures
        if len(self.failures) > 0:
            text += "FAILED test"
            if len(self.failures) > 1:
                text += "s"
            text += " "
            # generate a comma separated list of failed test numbers
            text += ','.join(map(str, self.failures))
            text += "\n"
        if self.testsRun > 0:
            # Now the overall summary
            percentSuccess = float(self.testsRun-len(self.failures)) / float(self.testsRun) * 100.0
            numPasses = self.testsRun - len(self.failures)
            text += "Passed %s/%s tests, %.2f%% okay, in %.2fs\n" % \
                (numPasses, self.testsRun, percentSuccess, timeTaken)
        # Output the report as diagnostic text
        if len(text) > 0:
            lines = text.split('\n')
            for line in lines:
                self.diagnostic(line)
        # Output the XML report if required
        if self.xmlDoc is not None:
            self.xmlTop.setAttribute("failures", str(len(self.failures)))
            self.xmlTop.setAttribute("tests", str(self.testsRun))
            self.xmlTop.setAttribute("time", str(timeTaken))
            self.xmlTop.setAttribute("timestamp", str(self.startTime))
            try:
                wFile = open(self.suite.xmlFileName, "w")
            except IOError:
                pass
            else:
                self.xmlDoc.writexml(wFile, indent="", addindent="  ", newl="\n")

    def diagnostic(self, text):
        '''Output the text as a TAP diagnostic line.'''
        self.outputText("# %s\n" % text)

    def outputText(self, text):
        self.stream.write(text)
        self.suite.sendToResultServer(text)

################################################
# Class that handles a telnet connection
class TelnetConnection(object):
    '''Manage a telnet connection, placing all received text in
       the receiveText member.'''
    def __init__(self, host, port, logFile=None):
        print "Opening telnet port %s:%s" % (host, port)
        self.telnet = telnetlib.Telnet()
        self.telnet.open(host, port)
        self.receivedText = ''
        self.logFile = None
        if logFile is not None:
            print "Opening telnet log file %s" % logFile
            self.logFile = open(logFile, 'a+')
        self.threadId = thread.start_new_thread(self.receiveThread, ())

    def receiveThread(self):
        going = True
        while going:
            text = self.telnet.read_some()
            going = len(text) > 0
            print text,
            self.receivedText += text
            if self.logFile is not None:
                self.logFile.write(text)
                self.logFile.flush()
                os.fsync(self.logFile.fileno())

    def close(self):
        self.telnet.close()

    def waitFor(self, text, timeout):
        '''Waits for the specified text to be received.  Any text
           in the receivedText variable is checked first.  Returns
           True if the text is found, False if not.'''
        timeRemaining = timeout
        items = []
        if type(text) == type(list()):
            items = text
        else:
            items.append(text)
        found = False
        while not found and timeRemaining > 0.0:
            for item in items:
                found = found or self.receivedText.find(item) >= 0
            if not found:
                Sleep(0.1)
                timeRemaining -= 0.1
        #print "Looking for %s in %s" % (repr(text), repr(self.receivedText))
        return found

    def write(self, text):
        self.telnet.write(text)

    def clearReceivedText(self):
        self.receivedText = ''

    def getReceivedText(self):
        return self.receivedText

################################################
# Class that launches a command line in parallel and then provides
# communication with stdin and stderr.
class AsynchronousProcess(object):
    '''Launch a process and provide communications.'''
    def __init__(self, runCmd, directory, logFile=None, name=''):
        self.receivedTextStdout = ''
        self.receivedTextStderr = ''
        self.processRunning = True
        self.logFile = None
        self.name = name
        if logFile is not None:
            print "Opening process log file %s" % logFile
            self.logFile = open(logFile, 'a+')
        self.process = subprocess.Popen(runCmd, cwd=directory, bufsize=1, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        #self.rxThreadIdStdout = thread.start_new_thread(self.receiveThreadStdout, ())
        self.rxThreadIdStdout = Spawn(self.receiveThreadStdout)
        #self.rxThreadIdStderr = thread.start_new_thread(self.receiveThreadStderr, ())
        self.rxThreadIdStderr = Spawn(self.receiveThreadStderr)

    def receiveThreadStdout(self):
        try:
            flags = fcntl.fcntl(self.process.stdout, fcntl.F_GETFL)
            fcntl.fcntl(self.process.stdout, fcntl.F_SETFL, flags | os.O_NONBLOCK | os.O_SYNC)
            while self.processRunning:
                #if select.select([self.process.stdout], [], [])[0]:
                if cothread.coselect.select([self.process.stdout], [], [])[0]:
                    text = self.process.stdout.read()
                    lines = text.split('\n')
                    for line in lines:
                        print '%s:o> %s' % (self.name, repr(line))
                    sys.stdout.flush()
                    self.receivedTextStdout += text
                    if self.logFile is not None:
                        self.logFile.write(text)
                        self.logFile.flush()
                        os.fsync(self.logFile.fileno())
        except Exception, e:
            # On any exception, just exit the thread
            pass

    def receiveThreadStderr(self):
        try:
            going = True
            flags = fcntl.fcntl(self.process.stderr, fcntl.F_GETFL)
            fcntl.fcntl(self.process.stderr, fcntl.F_SETFL, flags | os.O_NONBLOCK | os.O_SYNC)
            while self.processRunning:
                #if select.select([self.process.stderr], [], [])[0]:
                if cothread.coselect.select([self.process.stderr], [], [])[0]:
                    text = self.process.stderr.read()
                    lines = text.split('\n')
                    for line in lines:
                        print '%s:o> %s' % (self.name, repr(line))
                    sys.stdout.flush()
                    self.receivedTextStderr += text
                    if self.logFile is not None:
                        self.logFile.write(text)
                        self.logFile.flush()
                        os.fsync(self.logFile.fileno())
        except Exception, e:
            # On any exception, just exit the thread
            pass

    def kill(self):
        self.processRunning = False
        killProcessAndChildren(self.process.pid)

    def waitForStdout(self, text, timeout, discard):
        '''Waits for the specified text to be received.  Any text
           in the receivedText variable is checked first.  Returns
           True if the text is found, False if not.'''
        timeRemaining = timeout
        found = re.search(text, self.receivedTextStdout)
        while not found and timeRemaining > 0.0:
            Sleep(1.0)
            #time.sleep(1.0)
            timeRemaining -= 1.0
            found = re.search(text, self.receivedTextStdout)
        #print "Found=%s, Looking for %s in %s" % (found, repr(text), repr(self.receivedTextStdout))
        if discard and found:
            self.receivedTextStdout = self.receivedTextStdout[found.end():]
        return found

    def waitForStderr(self, text, timeout, discard):
        '''Waits for the specified text to be received.  Any text
           in the receivedText variable is checked first.  Returns
           True if the text is found, False if not.'''
        timeRemaining = timeout
        found = re.search(text, self.receivedTextStderr)
        while not found and timeRemaining > 0.0:
            Sleep(1.0)
            #time.sleep(1.0)
            timeRemaining -= 1.0
            found = re.search(text, self.receivedTextStderr)
        #print "Found=%s, Looking for %s in %s" % (found, repr(text), repr(self.receivedTextStderr))
        if discard and found:
            self.receivedTextStderr = self.receivedTextStderr[found.end():]
        return found

    def write(self, text):
        #if select.select([], [self.process.stdin], [], 0)[1]:
        if cothread.coselect.select([], [self.process.stdin], [], 0)[1]:
            self.process.stdin.write(text)
            self.process.stdin.flush()
            print text
            sys.stdout.flush()

    def clearReceivedTextStdout(self):
        self.receivedTextStdout = ''

    def getReceivedTextStdout(self):
        return self.receivedTextStdout

    def clearReceivedTextStderr(self):
        self.receivedTextStderr = ''

    def getReceivedTextStderr(self):
        return self.receivedTextStderr

    def sendSignal(self, signal):
        #p = subprocess.Popen("kill -%s %d" % (signal, self.process.pid), shell=True)
        #p.wait()
        self.process.send_signal(signal)

################################################
# Class that handles an IP power 9258 power switch
class PowerSwitch(object):
    '''Manage a power switch channel.'''
    def __init__(self, host, chan, user='admin', password='12345678'):
        self.host = host
        self.chan = chan
        self.user = user
        self.password = password
    def on(self):
        '''Switches the channel on, returns True for success.'''
        obj = urllib.urlopen('http://%s:%s@%s/Set.cmd?CMD=SetPower+P6%s=1' % \
            (self.user, self.password, self.host, self.chan))
        dom = xml.dom.minidom.parse(obj)
        reply = dom.getElementsByTagName('html')[0].firstChild.nodeValue
        return reply == ('P6%s=1' % self.chan)
    def off(self):
        '''Switches the channel off, returns True for success.'''
        obj = urllib.urlopen('http://%s:%s@%s/Set.cmd?CMD=SetPower+P6%s=0' % \
            (self.user, self.password, self.host, self.chan))
        dom = xml.dom.minidom.parse(obj)
        reply = dom.getElementsByTagName('html')[0].firstChild.nodeValue
        return reply == ('P6%s=0' % self.chan)
    def reset(self):
        self.off()
        Sleep(5)
        self.on()

################################################
# Class that handles the crate monitor
class CrateMonitor(object):
    '''Manage a crate monitor.'''
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.telnet = telnetlib.Telnet()
        self.telnet.open(host, port)
    def reset(self):
        '''Send a reset command.'''
        self.telnet.write('R,7E\r')

################################################
# Target definition class
class Target(object):
    '''Instances of this class define a target that the test suite is to
    be run against.'''

    def __init__(self, name, suite,
            # New API
            entities=[],
            # Original API
            iocDirectory="example",
            moduleBuildCmd="make clean uninstall; make",
            iocBuildCmd="make clean uninstall; make",
            iocBootCmd=None, epicsDbFiles="", simDevices=[],
            parameters={}, guiCmds=[], simulationCmds=[], environment=[],
            runIocInScreenUnderHudson=False, vxWorksIoc=False,
            iocHardwareName='',
            iocTelnetAddress=None, iocTelnetPort=None, iocTelnetLogFile=None,
            iocPowerControlAddress=None, iocPowerControlChan=None,
            iocCrateMonitorAddress=None, iocCrateMonitorPort=None):
        self.suite = suite
        self.name = name
        self.entities = entities
        self.suite.addTarget(self)
        # Convert original API to new API
        if len(self.entities) == 0:
            self.entities.append(ModuleEntity('#', buildCmd=moduleBuildCmd))
            self.entities.append(IocEntity('#', directory=iocDirectory, buildCmd=iocBuildCmd, bootCmd=iocBootCmd))
            for g in guiCmds:
                self.entities.append(GuiEntity('#', runCmd=g))
            epicsDbFiles = string.split(epicsDbFiles)
            for d in epicsDbFiles:
                self.entities.append(EpicsDbEntity('#', directory=iocDirectory, fileName=d))
            for d in simDevices:
                cmd = None
                if len(simulationCmds) > 0:
                    cmd = simulationCmds[0]
                    simulationCmds[0:1] = []
                rpc = None
                diag = None
                if d.rpc:
                    rpc = d.simulationPort
                else:
                    diag = d.simulationPort
                self.entities.append(SimulationEntity(d.name, runCmd=cmd, rpcPort=rpc, diagPort=diag))
            for c in simulationCmds:
                self.entities.append(SimulationEntity('#', runCmd=c))
            for e in environment:
                self.entities.append(EnvironmentEntity(e[0], value=e[1]))
            for name,value in parameters.iteritems():
                self.entities.append(ParameterEntity(name, value))

    def __del__(self):
        self.destroy()

    def prepare(self, doBuild, runIoc, runGui, diagnosticLevel, runSim, underHudson, suite):
        '''Prepares the target for execution of the test suite.'''
        if doBuild:
            for phase in range(numPhases):
                for e in self.entities:
                    e.build(phase)
        for phase in range(numPhases):
            for e in self.entities:
                e.run(phase, underHudson, runSim, runIoc, runGui, suite)
        for phase in range(numPhases):
            for e in self.entities:
                e.prepare(phase, diagnosticLevel, suite)

    def destroy(self):
        '''Returns the target to it's initial state.'''
        for phase in range(numPhases):
            for e in self.entities:
                e.destroy(phase)

    def reportCoverage(self):
        '''Returns the coverage reports.'''
        result = ""
        for e in self.entities:
            result += e.reportCoverage()
        return result

    def getEntity(self, name):
        '''Returns the first entity with the given name'''
        result = None
        for e in self.entities:
            if e.name == name:
                result = e
                break
        return result

    def command(self, devName, text):
        '''Send a command to a simulation device.'''
        e = self.getEntity(devName)
        if e is not None:
            e.command(text)

    def simulation(self, devName):
        '''Return simulation device for use with RPC calls.'''
        result = None
        e = self.getEntity(devName)
        if e is not None:
            result = e.rpcObject()
        return result

    def simulationDevicePresent(self, devName):
        '''Returns True if the simulation device is present in the current target'''
        return self.getEntity(devName) is not None

    def recvResponse(self, devName, rsp, numArgs):
        '''Try to receive a response from a simulation device.'''
        result = None
        e = self.getEntity(devName)
        if e is not None:
            result = e.recvResponse(rsp, numArgs)
        return result

    def param(self, name):
        '''Return a parameter.'''
        result = None
        e = self.getEntity(name)
        if e is not None:
            result = e.value
        return result

################################################
# Simulation device definition class
class SimDevice(object):
    '''Instances of this class define the simulation devices available
    with a target.'''

    def __init__(self, name, simulationPort, pythonShell=True, rpc = False):
        # Initialise
        self.sim = None
        self.simulationPort = simulationPort
        self.rpc = rpc
        self.name = name
        self.suite = None
        self.pythonShell = pythonShell

################################################
# Entity base class
class Entity(object):
    '''The base class for all entities.'''

    def __init__(self, name):
        self.name = name

    def build(self, phase):
        pass

    def run(self, phase, underHudson, runSim, runIoc, runGui, suite):
        pass

    def destroy(self, phase):
        pass

    def reportCoverage(self):
        return ''

    def prepare(self, phase, diagnosticLevel, suite):
        pass

    def rpcObject(self):
        return None

################################################
# IOC Entity definition class
class IocEntity(Entity):
    '''Instances of this class define IOCs.'''

    def __init__(self, name,
            buildCmd='make clean uninstall; make',
            buildPhase=phaseLate,
            directory=None,
            bootCmd=None,
            runInScreenUnderHudson=True,
            vxWorks=False,
            rtems=False,
            telnetAddress=None,
            telnetPort=None,
            telnetLogFile=None,
            crateMonitorAddress=None,
            crateMonitorPort=None,
            powerControlAddress=None,
            powerControlChan=None,
            automaticRun=True):
        Entity.__init__(self, name)
        self.buildCmd = buildCmd
        self.buildPhase = buildPhase
        self.directory = directory
        self.bootCmd = bootCmd
        self.runInScreenUnderHudson = runInScreenUnderHudson
        self.vxWorks = vxWorks
        self.rtems = rtems
        self.telnetAddress = telnetAddress
        self.telnetPort = telnetPort
        self.telnetLogFile = telnetLogFile
        self.automaticRun = automaticRun
        self.telnetConnection = None
        self.crateMonitor = None
        self.powerSwitch = None
        if crateMonitorAddress is not None and crateMonitorPort is not None:
            self.crateMonitor = CrateMonitor(crateMonitorAddress, crateMonitorPort)
        if powerControlAddress is not None and powerControlChan is not None:
            self.powerSwitch = PowerSwitch(powerControlAddress, powerControlChan)
        self.process = None

    def build(self, buildPhase):
        if self.buildCmd is not None and buildPhase == self.buildPhase:
            p = subprocess.Popen(self.buildCmd, cwd=self.directory, shell=True)
            p.wait()

    def run(self, phase, underHudson, runSim, runIoc, runGui, suite):
        self.underHudson = underHudson
        if phase == phaseNormal and runIoc and self.automaticRun:
            self.start()
            if not self.vxWorks and not self.rtems:
                Sleep(10)

    def start(self, noStartupScriptWait=False):
        if self.vxWorks:
            # vxWorks IOC
            self.prepareRedirector()
            self.telnetConnection = TelnetConnection(self.telnetAddress,
                    self.telnetPort, self.telnetLogFile)
            print 'Resetting IOC'
            if self.powerSwitch is not None:
                self.powerSwitch.reset()
            elif self.crateMonitor is not None:
                self.crateMonitor.reset()
            else:
                Sleep(1)
                self.telnetConnection.write('\r')
                Sleep(1)
                self.telnetConnection.write('reboot')
            print 'Waiting for auto-boot message'
            ok = self.telnetConnection.waitFor('Press any key to stop auto-boot', 60)
            print "    ok=%s" % ok
            if not noStartupScriptWait:
                print 'Waiting for script loaded message'
                ok = self.telnetConnection.waitFor('Done executing startup script', 120)
                print "    ok=%s" % ok
        elif self.rtems:
            # Connect up the telnet
            self.telnetConnection = TelnetConnection(self.telnetAddress,
                    self.telnetPort, self.telnetLogFile)
            # Reset the IOC
            print 'Resetting IOC'
            if self.powerSwitch is not None:
                self.powerSwitch.reset()
            elif self.crateMonitor is not None:
                self.crateMonitor.reset()
            else:
                Sleep(1)
                self.telnetConnection.write('\r')
                Sleep(1)
                self.telnetConnection.write('reset\r')
            print 'Waiting for boot message'
            ok = self.telnetConnection.waitFor('MVME5500>', 60)
            print "    ok=%s" % ok
            # Place the boot file in the TFTP directory
            os.system('scp ./base/bin/RTEMS-mvme5500/rtemsTestHarness* 172.23.240.2:/tftpboot/rtems/.')
            # Load the boot file
            self.telnetConnection.write('tftpGet -c172.23.248.38 -s172.23.240.2 -g172.23.240.254 -m255.255.240.0 -frtems/%s\r' % self.bootCmd)
            ok = self.telnetConnection.waitFor('MVME5500>', 60)
            Sleep(1)
            # Run the tests
            #self.telnetConnection.write('netShut\r')
            ok = self.telnetConnection.waitFor('MVME5500>', 60)
            Sleep(1)
            self.telnetConnection.write('go\r')
        else:
            self.process = AsynchronousProcess(self.bootCmd, self.directory, name=self.name)
            # Linux soft IOC
            #bootCmd = self.bootCmd
            #if self.runInScreenUnderHudson and self.underHudson:
            #    bootCmd = "screen -D -m -L " + bootCmd
            #self.process = subprocess.Popen(bootCmd,
            #    cwd=self.directory, shell=True)

    def destroy(self, phase):
        if self.process is not None and phase == phaseLate:
            self.stop()

    def stop(self):
        if self.vxWorks:
            pass
        else:
            #killProcessAndChildren(self.process.pid)
            #self.process = None
            #p = subprocess.Popen("stty sane", shell=True)
            #p.wait()
            self.process.kill()
            self.process = None

    def prepareRedirector(self):
        '''Programs the redirector to load the IOC executable.'''
        # The path of the executable
        iocPath = os.path.normpath(os.path.join(os.getcwd(), self.directory, self.bootCmd))
        print '@A:%s' % repr(iocPath)
        # Is the redirector already correct?
        str = subprocess.Popen('configure-ioc show %s' % self.name,
            shell=True, stdout=subprocess.PIPE).communicate()[0]
        pathNow = str.strip().split()[1]
        print '@1:%s' % repr(pathNow)
        if pathNow != iocPath:
            # No, so set it
            str = subprocess.Popen('configure-ioc edit %s %s' % (self.name, iocPath),
                shell=True, stdout=subprocess.PIPE).communicate()[0]
            print '@2:%s' % repr(str)
            # Wait for the redirector to report the correct path
            str = subprocess.Popen('configure-ioc show %s' % self.name,
                shell=True, stdout=subprocess.PIPE).communicate()[0]
            pathNow = str.strip().split()[1]
            print '@3:%s' % repr(pathNow)
            timeout = 100
            while pathNow != iocPath and timeout > 0:
                Sleep(2)
                timeout -= 2
                str = subprocess.Popen('configure-ioc show %s' % self.name,
                    shell=True, stdout=subprocess.PIPE).communicate()[0]
                pathNow = str.strip().split()[1]
                print '@4:%s' % repr(pathNow)
        return pathNow == iocPath

    def sendSignal(self, signal):
        if self.process is not None:
            self.process.sendSignal(signal)

    def verifyStdout(self, text, wait=0, discard=True):
        return self.process.waitForStdout(text, wait, discard)

    def verifyStderr(self, text, wait=0, discard=True):
        return self.process.waitForStderr(text, wait, discard)

    def writeStdin(self, text):
        self.process.write(text)

    def readStdout(self):
        return self.process.getReceivedTextStdout()

    def readStderr(self):
        return self.process.getReceivedTextStderr()

    def clearStdout(self):
        self.process.clearReceivedTextStdout()

    def clearStderr(self):
        self.process.clearReceivedTextStderr()


################################################
# Epics Database Entity definition class
class EpicsDbEntity(Entity):
    '''Instances of this class define EPICS databases that are to be monitored.'''

    def __init__(self, name,
            directory=None,
            fileName=None):
        Entity.__init__(self, name)
        self.directory = directory
        self.fileName = fileName
        self.suite = None
        self.database = None

    def run(self, phase, underHudson, runSim, runIoc, runGui, suite):
        self.suite = suite
        if phase == phaseEarly:
            # Work out the file name
            dbFileName = None
            if self.fileName is not None:
                if self.directory is None:
                    dbFileName = self.fileName
                else:
                    dbFileName = '%s/%s' % (self.directory, self.fileName)
            # Read the EPICS database
            self.database = EpicsDatabase(suite)
            if dbFileName is not None:
                self.database.readFile(dbFileName)
            # Create the monitors for the record coverage
            self.database.createMonitors()
            Sleep(3)
            # Initialise the coverage tracking
            self.database.clearCoverage()

    def reportCoverage(self):
        result = ""
        report = self.database.coverageReport()
        if report is not None:
            result = "==============================\n"
            result += "EPICS database %s coverage report:\n" % self.name
            result += report
        return result

################################################
# Build Entity definition class
class BuildEntity(Entity):
    '''Instances of this class define modules that are to be built.'''

    def __init__(self, name,
            buildCmd='make clean uninstall; make',
            buildPhase=phaseEarly,
            directory='.'):
        Entity.__init__(self, name)
        self.directory = directory
        self.buildCmd = buildCmd
        self.buildPhase = buildPhase

    def build(self, buildPhase):
        if self.buildCmd is not None and buildPhase == self.buildPhase:
            p = subprocess.Popen(self.buildCmd, cwd=self.directory, shell=True)
            p.wait()
# For backwards compatibility, define an alias for BuildEntity
class ModuleEntity(BuildEntity):
    pass

################################################
# Simulation Entity definition class
class SimulationEntity(Entity):
    '''Instances of this class define simulations that the suite uses.'''

    def __init__(self, name,
            rpcPort=None,
            diagPort=None,
            runCmd=None,
            pythonShell=True,
            directory='.'):
        Entity.__init__(self, name)
        self.rpcPort = rpcPort
        self.diagPort = diagPort
        self.runCmd = runCmd
        self.pythonShell = pythonShell
        self.directory = directory
        self.process = None
        self.rpcConnection = None
        self.rpcSimulation = None
        self.diagSimulation = None
        self.suite = None
        self.response = []

    def run(self, phase, underHudson, runSim, runIoc, runGui, suite):
        if phase == phaseEarly:
            if runSim and self.runCmd is not None:
                self.process = subprocess.Popen(self.runCmd, cwd=self.directory, shell=True)
                Sleep(10)

    def destroy(self, phase):
        if self.rpcSimulation is not None and phase == phaseEarly:
            self.rpcConnection.close()
            self.rpcSimulation = None
        if self.diagSimulation is not None and phase == phaseEarly:
            self.diagSimulation.close()
            self.diagSimulation = None
        if self.process is not None and phase == phaseLate:
            killProcessAndChildren(self.process.pid)
            self.process = None

    def rpcObject(self):
        return self.rpcSimulation

    def reportCoverage(self):
        result = ""
        branches = None
        coverage = None
        if self.rpcSimulation is not None:
            branches = self.rpcSimulation.branches
            coverage = self.rpcSimulation.coverage
        elif self.diagSimulation is not None:
            self.command("covbranches")
            branches = self.recvResponse("covbranches")
            self.command("coverage")
            coverage = self.recvResponse("coverage")
        if branches is not None or coverage is not None:
            result += "==============================\n"
            result += "Sim device %s coverage report:\n" % self.name
            if coverage is None:
                coverage = set()
            else:
                coverage = set(coverage)
            if branches is not None:
                for item in branches:
                    if item in coverage:
                        result += "    %s: ok\n" % item
                        coverage.remove(item)
                    else:
                        result += "    %s: not covered\n" % item
            for item in coverage:
                result += "    %s: ok but not declared\n" % item
        return result

    def prepare(self, phase, diagnosticLevel, suite):
        self.suite = suite
        if phase == phaseEarly:
            # Connect to the back door if required
            if self.rpcPort is not None:
                try:
                    import rpyc
                    self.rpcConnection = rpyc.classic.connect("localhost", port=self.rpcPort)
                    self.rpcSimulation = self.rpcConnection.root.simulation()
                    # Initialise the coverage tracking
                    self.rpcSimulation.clearCoverage()
                    # Initialise the diagnostic level
                    self.rpcSimulation.diaglevel = diagnosticLevel
                except Exception, e:
                    self.rpcSimulation = None
                    traceback.print_exc()
            elif self.diagPort is not None:
                try:
                    self.diagSimulation = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.diagSimulation.connect(("localhost", self.diagPort))
                    self.diagSimulation.settimeout(0.1)
                    self.response = []
                    self.swallowInput()
                    # Initialise the coverage tracking
                    self.command("covclear")
                    # Initialise the diagnostic level
                    self.command("diaglevel %s" % diagnosticLevel)
                except Exception, e:
                    self.diagSimulation = None
                    traceback.print_exc()

    def command(self, text):
        '''Send a command to the simulation through the diagnostic socket.'''
        if self.diagSimulation is not None:
            self.suite.diagnostic("Command[%s]: %s" % (self.name, text), 2)
            if self.pythonShell:
                self.diagSimulation.sendall('self.command(%s)\n' % repr(text))
            else:
                self.diagSimulation.sendall('%s\n' % text)

    def recvResponse(self, rsp, numArgs=-1):
        '''Try to receive a response from the simulation.'''
        result = None
        if self.diagSimulation is not None:
            # Get text tokens from the simulation
            try:
                text = self.diagSimulation.recv(1024)
                while text:
                    tokens = text.split()
                    self.response = self.response + tokens
                    text = self.diagSimulation.recv(1024)
            except socket.timeout:
                pass
            # Now find the line starting with the desired arg
            going = len(self.response) > 0
            while going:
                if self.response[0] == rsp:
                    break
                else:
                    while going and self.response[0] != ">>>":
                        self.response = self.response[1:]
                        going = len(self.response) > 0
                    if going:
                        self.response = self.response[1:]
                        going = len(self.response) > 0
            # Return the result, removing it from the response tokens
            if going:
                result = []
                self.response = self.response[1:]
                going = len(self.response) > 0
                while going and self.response[0] != ">>>":
                    result.append(self.response[0])
                    self.response = self.response[1:]
                    going = len(self.response) > 0
                if going:
                    self.response = self.response[1:]
                if numArgs >= 0:
                    if len(result) != numArgs:
                        result = None
        self.suite.diagnostic("Response[%s]: %s" % (self.name, result), 2)
        return result

    def swallowInput(self):
        '''Clears text from the socket connecting to the simulation.'''
        if self.diagSimulation is not None:
            try:
                while self.diagSimulation.recv(1024):
                    pass
            except socket.timeout:
                pass

################################################
# GUI Entity definition class
class GuiEntity(Entity):
    '''Instances of this class define GUIs that are run by the framework.'''

    def __init__(self, name,
            runCmd=None,
            directory='.'):
        Entity.__init__(self, name)
        self.runCmd = runCmd
        self.directory = directory
        self.process = None

    def run(self, phase, underHudson, runSim, runIoc, runGui, suite):
        if self.runCmd is not None and runGui and phase == phaseLate:
            self.process = subprocess.Popen(self.runCmd, cwd=self.directory, shell=True)
            Sleep(10)

    def destroy(self, phase):
        if self.process is not None and phase == phaseNormal:
            killProcessAndChildren(self.process.pid)
            self.process = None

################################################
# Environment variable definition class
class EnvironmentEntity(Entity):
    '''Instances of this class define environment variables.'''

    def __init__(self, name,
            value=''):
        Entity.__init__(self, name)
        self.value = value

    def run(self, phase, underHudson, runSim, runIoc, runGui, suite):
        if phase == phaseVeryEarly:
            os.environ[self.name] = self.value

################################################
# Parameter definition class
class ParameterEntity(Entity):
    '''Instances of this class define parameters.'''

    def __init__(self, name,
            value=''):
        Entity.__init__(self, name)
        self.value = value

###########################
def main():
    '''Main entry point for the DLS command.'''
    tests = RunTests()






