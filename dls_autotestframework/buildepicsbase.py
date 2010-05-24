#!/bin/env dls-python2.4

# do imports
from pkg_resources import require
require("dls_dependency_tree")
from dls_dependency_tree import dependency_tree
import getopt, sys, os, re
from xml.dom.minidom import *
import time

helpText = '''
  Checkout and build EPICS base, applying various modifications beforehand.

  Syntax:
    dls-build-epics-base.py [<options>]
        where <options> is one or more of:
        -h, --help                Print the help text and exit
        --base-ver=<version>      The EPICS base version to build for (eg R3.14.11 or trunk)
        --clean                   Perform checkout and build from clean
        --report-file=<file>      File to store the junit compatible XML report in
        --no-build                Do not build
        --no-checkout             Do not checkout
        --no-base                 Do not checkout or build epics base
        --no-log-files            Do not create log files, just let console output go to the console
        --coverage                Builds with coverage information enabled
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
        self.baseVer = 'trunk'
        self.clean = False
        self.xmlReportFileName = None
        self.noCheckout = False
        self.noBuild = False
        self.noLogFiles = False
        self.checkoutTime = 0.0
        self.buildTime = 0.0
        self.coverage = False
    def processArguments(self):
        '''Process the command line arguments.  Returns False
           if the program is to proceed.'''
        result = True
        try:
            opts, args = getopt.gnu_getopt(sys.argv[1:], 'h',
                ['help', 'base-ver=', 'clean', 'report-file=', 'no-checkout', 
                'no-build', 'no-base', 'no-log-files', 'coverage'])
        except getopt.GetoptError, err:
            fail(str(err))
        moduleNames = []
        extensionNames = []
        for o, a in opts:
            if o in ('-h', '--help'):
                print helpText
                result = False
            elif o == '--base-ver':
                self.baseVer = a
            elif o == '--clean':
                self.clean = True
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
        epicsRelease = "R3.14.11"
        if self.baseVer != 'trunk':
            epicsRelease = self.baseVer
        os.environ['EPICS_BASE'] = os.path.abspath("base")
    def do(self):
        if self.processArguments():
            print 'EPICS test builder, version %s' % self.baseVer
            sys.stdout.flush()
            self.setEnvironment()
            # Clean up first
            print 'Cleaning previous builds...'
            sys.stdout.flush()
            os.system('rm *.log')
            # Build base
            print 'Building base...'
            sys.stdout.flush()
            self.checkout()
            self.fixCoverage()
            self.build()
    def checkout(self):
        '''Check out base from launchpad using bazaar.'''
        if not self.noCheckout:
            startTime = time.time()
            print 'Checking out base %s...' % self.baseVer
            sys.stdout.flush()
            os.system('rm -rf base')
            if self.baseVer != 'trunk':
                os.system('bzr checkout --lightweight -r %s http://bazaar.launchpad.net/~epics-core/epics-base/3.14 base' % self.baseVer)
            else:
                os.system('bzr checkout --lightweight http://bazaar.launchpad.net/~epics-core/epics-base/3.14 base')
            self.checkoutTime = float(time.time() - startTime)
    def fixCoverage(self):
        '''Fix the configuration files to build with code coverage turned on.'''
        if self.coverage:
            inFile = open('base/configure/os/CONFIG.linux-x86.linux-x86', 'r')
            lines = inFile.readlines()
            inFile.close()
            outFile = open('base/configure/os/CONFIG.linux-x86.linux-x86', 'w')
            fullLine = ''
            for line in lines:
                outFile.write(line)
            outFile.write('ARCH_DEP_CFLAGS=-fprofile-arcs -ftest-coverage\n')
            outFile.write('ARCH_DEP_LDFLAGS=-coverage')
            outFile.close()
    def build(self):
        '''Build base.'''
        if not self.noBuild:
            startTime = time.time()
	    os.system('make -C base')
            self.buildTime = float(time.time() - startTime)

def main():
    Worker().do()

if __name__ == "__main__":
    main()

