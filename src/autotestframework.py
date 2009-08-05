#!/bin/env python2.4
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
require('dls.serial_sim')
import cothread
from cothread import *
from cothread.catools import *
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
import dls.serial_sim
import Queue
import socket
from runtests import *

helpText = """
Execute an automatic test suite.  Options are:
-h            Print this help
-d <level>    Sets the diagnostic level, 0..9.
-b            Performs a build before running the tests.
-i            Run IOC before running the tests.
"""
################################################
# Epics database record
class EpicsRecord(object):
    '''Represents an EPICS database record.'''

    #########################
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
        
    #########################
    def __str__(self):
        return "[%s, %s, %s]" % (self.identifier, self.record, self.fields)
        
    #########################
    def addField(self, name, value):
        '''Adds a field to the EPICS record.  Strips double quotes from the value.'''
        self.fields[name] = value.strip('"')

    #########################
    def monitorInd(self, value):
        '''Receives data from monitors placed on the record.'''
        self.suite.diagnostic("Pv %s=%s" % (value.name, value), 2)
        parts = value.name.split(".")
        if len(parts) == 1 or parts[1] == "VAL":
            # The value monitor
            if len(self.values) < 32:
                self.values.add(str(value))
    
    #########################
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

    #########################
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
        
    #########################
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
        
    #########################
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
        
    #########################
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

    #########################
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

    #########################
    def calcxCoverageReport(self):
        '''Record types calc and calcout.
        All we can really do is check that the output changed
        during the test.'''
        if len(self.values) < 2:
            text = "not touched"
        else:
            text = "ok"
        return text

    #########################
    def axCoverageReport(self):
        '''Record types ai and ao.
        Just check that the output changed during the test.
        We may be able to do something with the defined ranges later.'''
        if len(self.values) < 2:
            text = "not touched"
        else:
            text = "ok"
        return text

    #########################
    def motorCoverageReport(self):
        '''Record type motor.
        Just check that the output changed during the test.
        We may be able to do something with other fields later.'''
        if len(self.values) < 2:
            text = "not touched"
        else:
            text = "ok"
        return text

    #########################
    def fanoutCoverageReport(self):
        '''Record type fanout.
        I don't think there's anything we can do.
        Is there some way of detecting that the records
        at the other end of the output links are processed?'''
        text = "ok"
        return text

    #########################
    def clearCoverage(self):
        '''Clears all stored coverage information for the record.'''
        self.values = set([])

################################################
# Epics database
class EpicsDatabase(object):
    '''Represents the whole EPICS database'''
    
    #########################
    def __init__(self, suite):
        self.records = {}
        self.suite = suite

    #########################
    def __str__(self):
        result = ""
        for key, record in self.records.iteritems():
            result = result + "\n" + str(record)
        return result

    #########################
    def __len__(self):
        return len(self.records)
    
    #########################
    def createMonitors(self):
        '''Create monitors for all the records in the database.'''
        for key, record in self.records.iteritems():
            record.createMonitors()

    #########################
    def clearCoverage(self):
        '''Clear the coverage information of all the records in the database.'''
        for key, record in self.records.iteritems():
            record.clearCoverage()

    #########################
    def coverageReport(self):
        '''Generate a coverage report for the database'''
        text = ""
        for key, record in self.records.iteritems():
            text += record.coverageReport()
        return text
    
    #########################
    def addRecord(self, identifier, record):
        '''Add a record into the database.'''
        item = EpicsRecord(identifier, record, self.suite)
        self.records[identifier] = item
        return item

    #########################
    def getToken(self):
        '''Returns the next token of the database text.'''
        token = self.lexer.get_token()
        return str(token)

    #########################
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

    #########################
    def parseDatabase(self):
        '''Parse the database file.'''
        token = self.getToken()
        while token == "record" or token == "grecord":
            self.parseRecord()
            token = self.getToken()

    #########################
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

    #########################
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

    #########################
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
    
    #########################
    def __init__(self, suite):
        # Construct the super class
        unittest.TestCase.__init__(self)
        # Initialise things
        self.suite = suite
        self.suite.addTest(self)

    #########################
    def getPv(self, pv):
        '''Gets a value from a PV.  Can only throw fail exceptions
        when the underlying caget fails, no checking of the retrieved
        value is performed.'''
        try:
            d = caget(pv)
        except cothread.cothread.Timedout:
            self.fail("caget of %s timed out" % pv)
        except cothread.cadef.CAException:
            self.fail("caget of %s threw exception" % pv)
        else:
            return d
    
    #########################
    def putPv(self, pv, value):
        '''Sends a value to a PV.  Can throw a fail exceptions
        when the underlying caput fails.'''
        try:
            caput(pv, value)
        except cothread.cothread.Timedout:
            self.fail("caput of %s timed out" % pv)
        except cothread.cadef.CAException:
            self.fail("caput of %s threw exception" % pv)
    
    #########################
    def command(self, devName, text):
        '''Sends a command to a simulation device.'''
        self.suite.command(devName, text)

    #########################
    def simulationDevicePresent(self, devName):
        '''Returns True if the device simulation is present.'''
        return self.suite.simulationDevicePresent(devName)

    #########################
    def verify(self, left, right):
        '''Throws a fail exception if the two values are not identical.'''
        if left != right:
            self.fail("%s != %s" % (left, right))

    #########################
    def verifyInRange(self, value, lower, upper):
        '''Throws a fail exception if the value does not lie within
        the specified range.'''
        if value < lower or value > upper:
            self.fail("%s not in %s..%s" % (value, lower, upper))

    #########################
    def verifyPv(self, pv, value):
        '''Reads the specified PV and checks it has the specified value.
        Throws a fail exception if the caget or the check fails.'''
        d = self.getPv(pv)
        if d != value:
            self.fail("%s[%s] != %s" % (pv, d, value))
    
    #########################
    def verifyPvFloat(self, pv, value, delta):
        '''Reads the specified PV and checks it has the specified value
        within the given error.  Usually used for checking floating point
        values where equality is unreliable.  Throws a fail exception if
        the caget or the check fails.'''
        d = self.getPv(pv)
        if d < (value - delta) or d > (value + delta):
            self.fail("%s[%s] != %s +/-%s" % (pv, d, value, delta))
    
    #########################
    def verifyPvInRange(self, pv, lower, upper):
        '''Reads the specified PV and checks itis within the given range.
        Throws a fail exception if the caget or the check fails.'''
        d = self.getPv(pv)
        if d < lower or d > upper:
            self.fail("%s[%s] not in %s..%s" % (pv, d, lower, upper))
    
    #########################
    def recvResponse(self, devName, rsp, numArgs=-1):
        '''Try to receive a response from the simulation.'''
        return self.suite.recvResponse(devName, rsp, numArgs)

    #########################
    def sleep(self, time):
        '''Sleep for the specified number of seconds.'''
        Sleep(time)

    #########################
    def diagnostic(self, text, level=0):
        '''Write the text as a TAP diagnostic line.'''
        self.suite.diagnostic(text, level)

    #########################
    def param(self, name):
        '''Return a parameter.'''
        return self.suite.param(name)

################################################
# Test suite super class
class TestSuite(unittest.TestSuite):
    '''The automatic test framework test suite super class.  Each test suite should
    provide a class derived from this one that defines the cases to
    run and the targets to use.'''
    
    #########################
    def __init__(self, diagnosticLevel=9):
        # Construct the super class
        unittest.TestSuite.__init__(self)
        # Initialise
        self.epicsDatabase = None
        self.targets = []
        self.diagnosticLevel = diagnosticLevel
        self.doBuild = False
        self.runIoc = False
        self.runGui = False
        self.runSimulation = False
        self.onlyTarget = None
        self.onlyTestCase = None
        self.results = None
        self.serverSocketName = None
        self.resultSocket = None
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

    ######################################
    def processArguments(self):
        """Process the command line arguments.
        """
        result = True
        state = "none"
        for arg in sys.argv:
            if state == "none":
                if arg == "-d":
                    state = "diagnosticLevel"
                elif arg == "-t":
                    state = "target"
                elif arg == "-c":
                    state = "case"
                elif arg == "-r":
                    state = "resultServer"
                elif arg == "-h":
                    print helpText
                    result = False
                elif arg == "-b":
                    self.doBuild = True
                elif arg == "-i":
                    self.runIoc = True
                elif arg == "-g":
                    self.runGui = True
                elif arg == "-e":
                    self.runSimulation = True
            elif state == "diagnosticLevel":
                self.diagnosticLevel = int(arg)
                state = "none"
            elif state == "target":
                self.onlyTarget = arg
                state = "none"
            elif state == "case":
                self.onlyTestCase = arg
                state = "none"
            elif state == "resultServer":
                self.serverSocketName = arg
                state = "none"
        return result
        
    #########################
    def prepare(self, epicsDbFiles, iocDirectory):
        '''Prepare the test suite for running the test cases.'''
        # Read the EPICS database if provided
        self.epicsDatabase = EpicsDatabase(self)
        for name in epicsDbFiles:
            path = "%s/%s" % (iocDirectory, name)
            self.epicsDatabase.readFile(path)
        # Create the monitors for the record coverage
        self.epicsDatabase.createMonitors()
        Sleep(3)
        # Initialise the coverage tracking
        self.epicsDatabase.clearCoverage()

    #########################
    def destroy(self):
        '''Return the test suite to its initial condition.'''
        self.epicsDatabase = None

    #########################
    def addTarget(self, target):
        '''Add a target to the test suite.'''
        self.targets.append(target)

    #########################
    def reportCoverage(self):
        '''Generate the coverage reports from the test run.'''
        # Retrieve the simulation coverage report in simulation mode
        self.diagnostic(self.target.reportSimulationCoverage())
        # Retrieve the coverage report for the EPICS database
        if len(self.epicsDatabase):
            Sleep(1)
            self.diagnostic("==============================")
            self.diagnostic("EPICS database coverage report:")
            self.diagnostic(self.epicsDatabase.coverageReport())
            self.diagnostic("==============================")

    #########################
    def addTest(self, test):
        '''Add a test case to the suite.'''
        className = str(test.__class__)
        className = string.split(className, '.')[1]
        className = string.split(className, "'")[0]
        if self.onlyTestCase is None or self.onlyTestCase == className:
            unittest.TestSuite.addTest(self, test)

    #########################
    def command(self, devName, text):
        '''Send a command to a simulation device.'''
        self.target.command(devName, text)

    #########################
    def simulationDevicePresent(self, devName):
        '''Returns True if the simulation device is present in the current target'''
        return self.target.simulationDevicePresent(devName)

    #########################
    def recvResponse(self, devName, rsp, numArgs=-1):
        '''Try to receive a response from a simulation device.'''
        return self.target.recvResponse(devName, rsp, numArgs)

    #########################
    def runTests(self):
        '''Runs this suite's tests.'''
        for self.target in self.targets:
            if self.onlyTarget is None or self.onlyTarget == self.target.name:
                self.target.prepare(self.doBuild, self.runIoc, self.runGui, 
                    self.diagnosticLevel, self.runSimulation)
                self.prepare(self.target.epicsDbFiles, self.target.iocDirectory)
                self.diagnostic("==============================")
                self.results = TestResult(self.countTestCases(), sys.stdout, self)
                self.run(self.results)
                self.diagnostic("==============================")
                self.results.report()
                self.reportCoverage()
                self.results = None
                self.destroy()
                self.target.destroy()

    #########################
    def diagnostic(self, text, level=0):
        '''Outputs text as a TAP diagnostic line.'''
        if self.results is not None and level <= self.diagnosticLevel:
            lines = string.split(text, '\n')
            for line in lines:
                self.results.diagnostic(line)

    #########################
    def param(self, name):
        '''Return a parameter.'''
        return self.target.param(name)

    #########################
    def sendToResultServer(self, text):
        if self.resultSocket is not None:
            self.resultSocket.send(text)

################################################
# Test results class
class TestResult(unittest.TestResult):
    '''The automatic test framework test result class.  It outputs text that
    conforms to the TAP protocol specification to a given stream.'''
    
    #########################
    def __init__(self, numCases, stream, suite):
        unittest.TestResult.__init__(self)
        self.stream = stream
        self.numCases = numCases
        self.startTime = time.time()
        self.failures = []
        self.suite = suite
        self.outputText("1..%s\n" % self.numCases)

    #########################
    def getDescription(self, test):
        '''Return a description of a test.'''
        return test.shortDescription() or str(test)

    #########################
    def addSuccess(self, test):
        '''Called when a test case has run successfully.'''
        self.outputText("ok %s - %s\n" % (self.testsRun, self.getDescription(test)))

    #########################
    def addError(self, test, err):
        '''Called when a test case fails due to an unexpected exception.'''
        self.addFailure(test, err)
        if err[0] is KeyboardInterrupt:
            self.shouldStop = 1

    #########################
    def addFailure(self, test, err):
        '''Called when a test case fails.'''
        self.failures.append(self.testsRun)
        for text in apply(traceback.format_exception, err):
            for line in string.split(text, "\n"):
                self.outputText("# %s\n" % line)
        self.outputText("not ok %s - %s\n" % (self.testsRun, self.getDescription(test)))

    #########################
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
            first = True
            for i in self.failures:
                if not first:
                    text += ", "
                text += "%s" % i
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

    #########################
    def diagnostic(self, text):
        '''Output the text as a TAP diagnostic line.'''
        self.outputText("# %s\n" % text)

    #########################
    def outputText(self, text):
        self.stream.write(text)
        self.suite.sendToResultServer(text)

################################################
# Target definition class
class Target(object):
    '''Instances of this class define a target that the test suite is to
    be run against.'''
    
    #########################
    def __init__(self, name, suite, iocDirectory="example",
            moduleBuildCmd="make clean uninstall; make",
            iocBuildCmd="make clean uninstall; make",
            iocBootCmd=None, epicsDbFiles="", simDevices=[],
            parameters={}, guiCmds=[], simulationCmds=[]):
        self.suite = suite
        self.name = name
        self.iocDirectory = iocDirectory
        self.iocBuildCmd = iocBuildCmd
        self.moduleBuildCmd = moduleBuildCmd
        self.iocBootCmd = iocBootCmd
        self.targetProcess = None
        self.epicsDbFiles = string.split(epicsDbFiles)
        self.simDevices = {}
        self.parameters = parameters
        self.guiCmds = guiCmds
        self.guiProcesses = []
        self.simulationCmds = simulationCmds
        self.simulationProcesses = []
        for device in simDevices:
            self.simDevices[device.name] = device
        self.suite.addTarget(self)

    #########################
    def __del__(self):
        self.destroy()

    #########################
    def prepare(self, doBuild, runIoc, runGui, diagnosticLevel, runSim):
        '''Prepares the target for execution of the test suite.'''
        if doBuild and self.moduleBuildCmd is not None:
            p = subprocess.Popen(self.moduleBuildCmd, cwd='.', shell=True)
            p.wait()
        if doBuild and self.iocBuildCmd is not None:
            p = subprocess.Popen(self.iocBuildCmd, cwd=self.iocDirectory, shell=True)
            p.wait()
        if runSim:
            for simulationCmd in self.simulationCmds:
                p = subprocess.Popen(simulationCmd, cwd='.', shell=True)
                self.simulationProcesses.append(p)
                Sleep(10)
        if runIoc and self.iocBootCmd is not None:
            self.targetProcess = subprocess.Popen(self.iocBootCmd,
                cwd=self.iocDirectory, shell=True)
            Sleep(10)
        for name, device in self.simDevices.iteritems():
            device.prepare(diagnosticLevel, self.suite)
        if runGui:
            for guiCmd in self.guiCmds:
                p = subprocess.Popen(guiCmd, cwd='.', shell=True)
                self.guiProcesses.append(p)
            Sleep(10)
        
    #########################
    def destroy(self):
        '''Returns the target to it's initial state.'''
        if self.targetProcess is not None:
            self.killProcessAndChildren(self.targetProcess.pid)
            self.targetProcess = None
            p = subprocess.Popen("stty sane", shell=True)
            p.wait()
        for simulationProcess in self.simulationProcesses:
            self.killProcessAndChildren(simulationProcess.pid)
        self.simulationProcesses = []
        for guiProcess in self.guiProcesses:
            self.killProcessAndChildren(guiProcess.pid)
        self.guiProcesses = []

    #########################
    def killProcessAndChildren(self, pid):
        # First, kill off all the children
        str = subprocess.Popen('ps -o pid,ppid ax', shell=True, stdout=subprocess.PIPE).communicate()[0]
        lines = str.split('\n')[1:]
        for line in lines:
            pids = line.strip().split()
            if len(pids) == 2 and int(pids[1]) == pid:
                self.killProcessAndChildren(int(pids[0]))
        # If the parent still exists, kill it too
        str = subprocess.Popen('ps %s' % pid, shell=True, stdout=subprocess.PIPE).communicate()[0]
        lines = str.split('\n')
        if len(lines) > 1 and lines[1].find('<defunct>') == -1:
            p = subprocess.Popen("kill -KILL %d" % pid, shell=True)
            p.wait()

    #########################
    def reportSimulationCoverage(self):
        '''Returns the coverage reports for any simulation devices of the target.'''
        result = ""
        for name, device in self.simDevices.iteritems():
            result += device.reportCoverage()
        return result

    #########################
    def command(self, devName, text):
        '''Send a command to a simulation device.'''
        if devName in self.simDevices:
            self.simDevices[devName].command(text)

    #########################
    def simulationDevicePresent(self, devName):
        '''Returns True if the simulation device is present in the current target'''
        result = False
        if devName in self.simDevices:
            result = self.simDevices[devName].devicePresent()
        return result

    #########################
    def recvResponse(self, devName, rsp, numArgs):
        '''Try to receive a response from a simulation device.'''
        result = None
        if devName in self.simDevices:
            result = self.simDevices[devName].recvResponse(rsp, numArgs)
        return result

    #########################
    def param(self, name):
        '''Return a parameter.'''
        return self.parameters[name]

################################################
# Simulation device definition class
class SimDevice(object):
    '''Instances of this class define the simulation devices available
    with a target.'''
    
    #########################
    def __init__(self, name, simulationPort, pythonShell=True):
        # Initialise
        self.sim = None
        self.simulationPort = simulationPort
        self.name = name
        self.suite = None
        self.pythonShell = pythonShell

    #########################
    def devicePresent(self):
        '''Returns true if the simulation device is present'''
        return self.sim is not None

    #########################
    def prepare(self, diagnosticLevel, suite):
        '''Prepare the simulation device for running the test cases.'''
        self.suite = suite
        try:
            self.sim = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sim.connect(("localhost", self.simulationPort))
            self.sim.settimeout(0.1)
            self.swallowInput()
        except:
            self.sim = None
        # Initialise response processor
        self.response = []
        # Initialise the coverage tracking
        self.command("covclear")
        # Initialise the diagnostic level
        self.command("diaglevel %s" % diagnosticLevel)

    #########################
    def destroy(self):
        '''Return the simulation device to its initial condition.'''
        if self.sim is not None:
            self.sim.close()
        self.sim = None

    #########################
    def reportCoverage(self):
        '''Return the coverage reports for the simulation device.'''
        result = ""
        if self.sim is not None:
            result += "==============================\n"
            result += "Sim device %s coverage report:\n" % self.name
            self.command("covbranches")
            branches = self.recvResponse("covbranches")
            self.command("coverage")
            coverage = self.recvResponse("coverage")
            if branches is not None:
                for item in branches:
                    if coverage is not None and item in coverage:
                        result += "    %s: ok\n" % item
                        coverage.remove(item)
                    else:
                        result += "    %s: not covered\n" % item
            if coverage is not None:
                for item in coverage:
                    result += "    %s: ok but not declared\n" % item
        return result

    #########################
    def command(self, text):
        '''Send a command to the simulation.'''
        if self.sim is not None:
            self.suite.diagnostic("Command[%s]: %s" % (self.name, text), 2)
            if self.pythonShell:
                self.sim.sendall('self.command("%s")\n' % text)
            else:
                self.sim.sendall('%s\n' % text)

    #########################
    def recvResponse(self, rsp, numArgs=-1):
        '''Try to receive a response from the simulation.'''
        result = None
        if self.sim is not None:
            # Get text tokens from the simulation
            try:
                text = self.sim.recv(1024)
                while text:
                    tokens = text.split()
                    self.response = self.response + tokens
                    text = self.sim.recv(1024)
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

    #########################
    def swallowInput(self):
        '''Clears text from the socket connecting to the simulation.'''
        if self.sim is not None:
            try:
                while self.sim.recv(1024):
                    pass
            except socket.timeout:
                pass

################################################
# Updated simulation serial_device class.
class serial_device(dls.serial_sim.serial_device):
    """An improvement to the basic simulation serial-device class that
    changes certain class-scope variables to instance scope.
    """
    #########################
    def __init__(self, protocolBranches=[]):
        # Super-class class scope variables converted to instance scope.
        self.inq = Queue.Queue()
        self.outq = Queue.Queue()
        self.server_type = None
        self.started = False
        # Test framework support
        self.power = False
        self.coverage = set([])
        self.diagLevel = 0
        self.branches = protocolBranches

    #########################
    def isPowerOn(self):
        '''Returns true if the device power is on.'''
        return self.power

    #########################
    def diagnosticLevel(self):
        '''Returns the current diagnostic level.'''
        return self.diagLevel
        
    #########################
    def covered(self, branchName):
        '''Indicates that a branch has been executed.'''
        self.coverage.add(branchName)
        
    #########################
    def command(self, text):
        '''The interface for the test framework.  The text must be a space
        seperated list of arguments.  Results are 'returned' by just
        printing them out.  This super class implementation provides the
        common commands for all simulation devices.  Override to provide
        specific commands but don't forget to call this base class version
        when the override is not applicable.'''
        args = text.split()
        if args[0] == "off":
            self.power = False
        elif args[0] == "on":
            if not self.power:
                self.initialise()
            self.power = True
        elif args[0] == "power":
            self.response("power %d" % self.power)
        elif args[0] == "coverage":
            reply = "coverage"
            for item in self.coverage:
                reply = reply + " " + item
            self.response(reply)
        elif args[0] == "covclear":
            self.coverage = set([])
        elif args[0] == "covbranches":
            reply = "covbranches"
            for item in self.branches:
                reply = reply + " " + item
            self.response(reply)
        elif args[0] == "diaglevel":
            self.diagLevel = int(args[1])

    #########################
    def initialise(self):
        '''Override this function to implement power on initialisation.'''
        pass
        
    #########################
    def response(self, text):
        '''Call the function to return text to the test framework.  The current
        implementation just prints it out on the assumption that the test
        framework is monitoring standard out.  One day, a proper protocol
        may be invented.'''
        print text  

###########################
def main():
    '''Main entry point for the DLS command.'''
    tests = RunTests()
    


            
    
    
