#!/bin/env python2.6

# do imports
from autotestframework import *
import getopt, sys, os, re
from xml.dom.minidom import *
import time

helpText = '''
  Checkout and build EPICS base, applying various modifications beforehand.

  Syntax:
    dls-build-epics-base.py [<options>]
        where <options> is one or more of:
        -h, --help                Print the help text and exit
        --branch=<name>           The bazaar branch, defaults to 'trunk'
        --revision=<name>         Checkout a particular revision
        --clean                   Perform checkout and build from clean
        --report-file=<file>      File to store the junit compatible XML report in
        --no-build                Do not build
        --no-checkout             Do not checkout
        --no-base                 Do not checkout or build epics base
        --no-log-files            Do not create log files, just let console output go to the console
        --coverage                Builds with coverage information enabled
        --run-vx-tests            Run the test suite on the vxWorks hardware regression rig
'''

def fail(text):
    print text
    sys.exit(1)

def extractFromLog(logFileName, xmlDoc, xmlParent):
    '''Extracts the error messages from the log file, including appropriate context lines too.'''
    if os.path.exists(logFileName):
        log = open(logFileName)
        context = []
        needsEllipsis = False
        for line in log:
            line = line.strip()
            fixedLine = ''
            for ch in line:
                if ord(ch) >= 127 or ord(ch) < 32:
                    fixedLine += '\\x%02x' % ord(ch)
                else:
                    fixedLine += ch
            context.append(fixedLine)
            if len(context) > 5:
                context[0:1] = []
                if needsEllipsis:
                    textNode = xmlDoc.createTextNode('...')
                    xmlParent.appendChild(textNode)
                    needsEllipsis = False
            if line.find('error:') != -1 or \
                    line.find('warning:') != -1 or \
                    re.match('make\\[\\d*\\]: \\*\\*\\*', line) is not None:
                for c in context:
                    textNode = xmlDoc.createTextNode(c.strip())
                    xmlParent.appendChild(textNode)
                context = []
                needsEllipsis = True

class Worker(object):
    def __init__(self):
        self.branch = 'trunk'
        self.revision = None
        self.clean = False
        self.xmlReportFileName = None
        self.noCheckout = False
        self.noBuild = False
        self.noLogFiles = False
        self.checkoutTime = 0.0
        self.buildTime = 0.0
        self.coverage = False
        self.runVxTests = False

    def processArguments(self):
        '''Process the command line arguments.  Returns False
           if the program is to proceed.'''
        result = True
        try:
            opts, args = getopt.gnu_getopt(sys.argv[1:], 'h',
                ['help', 'branch=', 'clean', 'report-file=', 'no-checkout', 
                'no-build', 'no-base', 'no-log-files', 'coverage',
                'run-vx-tests', 'revision='])
        except getopt.GetoptError, err:
            fail(str(err))
        moduleNames = []
        extensionNames = []
        for o, a in opts:
            if o in ('-h', '--help'):
                print helpText
                result = False
            elif o == '--branch':
                self.branch = a
            elif o == '--revision':
                self.revision = a
            elif o == '--clean':
                self.clean = True
            elif o == '--run-vx-tests':
                self.runVxTests = True
            elif o == '--report-file':
                self.xmlReportFileName = a
            elif o == '--no-checkout':
                self.noCheckout = True
            elif o == '--no-build':
                self.noBuild = True
            elif o == '--no-base':
                self.noBase = True
            elif o == '--no-log-files':
                self.noLogFiles = True
            elif o == '--coverage':
                self.coverage = True
        return result
    def setEnvironment(self):
        os.environ['https_proxy'] = 'http://wwwcache3.rl.ac.uk:8080'
        os.environ['http_proxy'] = 'http://wwwcache3.rl.ac.uk:8080'
    def do(self):
        if self.processArguments():
            self.setEnvironment()
            self.cleanUp()
            self.checkout()
            self.fixCoverage()
            self.fixToolsLocation()
            self.fixConfigSite()
            self.build()
            self.doVxTests()
    def cleanUp(self):
        os.system('rm vxTestHarness.boot || true')
        os.system('rm vxTestLog.txt || true')
        os.system('rm vxTestLog.xml || true')
    def checkout(self):
        '''Check out base from launchpad using bazaar.'''
        if not self.noCheckout:
            startTime = time.time()
            print 'Checking out base...'
            sys.stdout.flush()
            os.system('rm -rf base')
            if self.revision is not None:
                os.system('bzr checkout --lightweight -r %s http://bazaar.launchpad.net/~epics-core/epics-base/%s base' % (self.revision, self.branch))
            else:
                os.system('bzr checkout --lightweight http://bazaar.launchpad.net/~epics-core/epics-base/%s base' % self.branch)
            self.checkoutTime = float(time.time() - startTime)
    def fixCoverage(self):
        '''Fix the configuration files to build with code coverage turned on.'''
        inFile = open('base/configure/os/CONFIG.linux-x86.linux-x86', 'r')
        lines = inFile.readlines()
        inFile.close()
        outFile = open('base/configure/os/CONFIG.linux-x86.linux-x86', 'w')
        for line in lines:
            if line.find('-ftest-coverage') == -1 and line.find('-coverage') == -1:
                outFile.write(line)
        if self.coverage:
            outFile.write('ARCH_DEP_CFLAGS=-fprofile-arcs -ftest-coverage\n')
            outFile.write('ARCH_DEP_LDFLAGS=-coverage\n')
        outFile.close()
    def fixToolsLocation(self):
        '''Fixes cross compiler tool location for the Diamond site.'''
        inFile = open('base/configure/os/CONFIG_SITE.Common.vxWorksCommon', 'r')
        lines = inFile.readlines()
        inFile.close()
        outFile = open('base/configure/os/CONFIG_SITE.Common.vxWorksCommon', 'w')
        for line in lines:
            if line.startswith('VXWORKS_VERSION'):
                outFile.write('VXWORKS_VERSION = 5.5\n')
            elif line.startswith('WIND_BASE'):
                outFile.write('WIND_BASE = /dls_sw/targetOS/vxWorks/Tornado-2.2\n')
            else:
                outFile.write(line)
        outFile.close()
    def fixConfigSite(self):
        '''Fixes the CONFIG_SITE file to build required cross compiler targets.'''
        inFile = open('base/configure/CONFIG_SITE', 'r')
        lines = inFile.readlines()
        inFile.close()
        outFile = open('base/configure/CONFIG_SITE', 'w')
        for line in lines:
            if line.startswith('CROSS_COMPILER_TARGET_ARCHS'):
                outFile.write('CROSS_COMPILER_TARGET_ARCHS = vxWorks-ppc604_long\n')
            else:
                outFile.write(line)
        outFile.close()
    def build(self):
        '''Build base.'''
        if not self.noBuild:
            startTime = time.time()
	    os.system('make -C base clean uninstall')
	    os.system('make -C base')
            self.buildTime = float(time.time() - startTime)
    def doVxTests(self):
        '''Run the vxWorks test suite on a remote target.'''
        if self.runVxTests:
            # Create a boot script
            bootFile = open('vxTestHarness.boot', 'w')
            bootFile.write('ld <%s\n' % os.path.abspath('base/bin/vxWorks-ppc604_long/vxTestHarness.munch'))
            bootFile.write('cd "%s"\n' % os.getcwd())
            bootFile.write('epicsRunLibComTests\n')
            bootFile.close()
            # Start up the IOC using the boot script
            ioc = IocEntity('ioc336', directory='.', bootCmd='vxTestHarness.boot', vxWorks=True,
                telnetAddress='172.23.241.1', telnetPort='7031', telnetLogFile='vxTestLog.txt', 
                crateMonitorAddress='172.23.241.1', crateMonitorPort='7032')
            ioc.start(noStartupScriptWait=True)
            # Wait for the tests to complete
            print 'Waiting for tests to complete...'
            ioc.telnetConnection.waitFor('EPICS Test Harness Results', 20*60)
            # Process the log file
            print 'Processing log file...'
            self.tapToJunit('vxTestLog.txt', 'vxTestLog.xml')
    def tapToJunit(self, tapFileName, junitFileName):
        '''Converts TAP output into a JUNIT report.'''
        tapFile = open(tapFileName, 'r')
        xmlDoc = getDOMImplementation().createDocument(None, "testsuite", None)
        xmlTop = xmlDoc.documentElement
        suiteName = ''
        numTests = 0
        numFails = 0
        numPasses = 0
        caseName = ''
        for line in tapFile:
            # Suite name (not TAP but consistently used in the output)
            m = re.match('\\*\\*\\*\\*\\*\\s*(\\w*)\\s*\\*\\*\\*\\*\\*', line)
            if m:
                suiteName = m.group(1)
            # Suite size
            m = re.match('(\\d*)\\.\\.(\\d*)', line)
            if m:
                numTests = int(m.group(2))
            # Passing test case
            m = re.match('ok\\s*(\\d*\\s*-\\s*.*)', line)
            if m:
                numPasses += 1
                caseName = m.group(1).strip()
                self.createCaseXmlElement(xmlDoc, xmlTop, suiteName, caseName)
            # Failing test case
            m = re.match('not ok\\s*(\\d*\\s*-\\s*.*)', line)
            if m:
                numFails += 1
                caseName = m.group(1).strip()
                element = self.createCaseXmlElement(xmlDoc, xmlTop, suiteName, caseName)
                errorElement = xmlDoc.createElement("error")
                element.appendChild(errorElement)
                errorElement.setAttribute("message", 'failure')
        tapFile.close()
        xmlTop.setAttribute("failures", str(numFails))
        xmlTop.setAttribute("tests", str(numPasses+numFails))
        junitFile = open(junitFileName, "w")
        xmlDoc.writexml(junitFile, indent="", addindent="  ", newl="\n")
        junitFile.close()
        print 'Tests=%s, Passes=%s, Fails=%s' % (numFails+numPasses, numPasses, numFails)
    def createCaseXmlElement(self, xmlDoc, xmlTop, suiteName, caseName):
        element = xmlDoc.createElement("testcase")
        xmlTop.appendChild(element)
        element.setAttribute("classname", suiteName)
        element.setAttribute("name", caseName)
        return element



def main():
    Worker().do()

if __name__ == "__main__":
    main()

