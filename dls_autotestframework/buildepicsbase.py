#!/bin/env python2.6

# do imports
import getopt, sys, os, re
from autotestframework import *
from webpagehelper import *
from createcoveragereport import CoverageReport
import time
from xml.dom.minidom import *

helpText = '''
  Checkout and build EPICS base, applying various modifications beforehand.
  Files are checked out and reports created in the current directory.  Any
  existing check outs and reports are deleted first.

  Syntax:
    dls-build-epics-base.py [<options>]
        where <options> is one or more of:
        -h, --help                Print the help text and exit
        --base-project=<name>     The launchpad project name for base, defaults to 'epics-base'
        --base-branch=<name>      The bazaar branch for base, defaults to 'trunk'
        --base-revision=<name>    Checkout a particular revision of base
        --checkout-base           Checkout base
        --build-base              Build base
        --tests-project=<name>    The launchpad project name for the tests, defaults to 'epics-base-testing'
        --tests-branch=<name>     The bazaar branch for the tests, defaults to 'trunk'
        --tests-revision=<name>   Checkout a particular revision of the tests
        --checkout-tests          Checkout tests
        --build-tests             Build tests
        --report-file=<file>      File to store the junit compatible XML report in
        --coverage                Builds with coverage information enabled
        --run-vx-tests            Run the test suite from base on the vxWorks hardware regression rig
        --run-rtems-tests         Run the test suite from base on the RTEMS hardware regression rig
        --run-tests               Run the test suite from base on the host
        --run-soft-tests          Run the soft tests from the tests project on the host
        --html-dir=<path>         Directory to write the HTML report into, defaults to none
'''

def fail(text):
    print text
    sys.exit(1)

def extractFromLog(logFileName, xmlDoc, xmlParent):
    '''Extracts the error messages from the log file,
       including appropriate context lines too.'''
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
        self.baseBranch = 'trunk'
        self.baseProject = 'epics-base'
        self.baseRevision = None
        self.testsBranch = 'trunk'
        self.testsProject = 'epics-base-testing'
        self.testsRevision = None
        self.xmlReportFileName = None
        self.checkoutBase = False
        self.buildBase = False
        self.checkoutTests = False
        self.buildTests = False
        self.coverage = False
        self.runVxTests = False
        self.runRtemsTests = False
        self.runTests = False
        self.runSoftTests = False
        self.htmlDir = None
        self.indexPage = None
        self.indexTable = None

    def processArguments(self):
        '''Process the command line arguments.  Returns False
           if the program is to proceed.'''
        result = True
        try:
            opts, args = getopt.gnu_getopt(sys.argv[1:], 'h',
                ['help', 'base-branch=', 'report-file=', 'checkout-base',
                'build-base', 'coverage', 'html-dir=',
                'run-vx-tests', 'base-revision=', 'run-tests', 'base-project=',
                'tests-branch=', 'checkout-tests', 'build-tests',
                'tests-revision=', 'tests-project=', 'run-soft-tests',
                'run-rtems-tests'])
        except getopt.GetoptError, err:
            fail(str(err))
        moduleNames = []
        extensionNames = []
        for o, a in opts:
            if o in ('-h', '--help'):
                print helpText
                result = False
            elif o == '--base-branch':
                self.baseBranch = a
            elif o == '--base-revision':
                self.baseRevision = a
            elif o == '--tests-branch':
                self.testsBranch = a
            elif o == '--tests-revision':
                self.testsRevision = a
            elif o == '--run-vx-tests':
                self.runVxTests = True
            elif o == '--run-rtems-tests':
                self.runRtemsTests = True
            elif o == '--run-tests':
                self.runTests = True
            elif o == '--report-file':
                self.xmlReportFileName = a
            elif o == '--checkout-base':
                self.checkoutBase = True
            elif o == '--build-base':
                self.buildBase = True
            elif o == '--checkout-tests':
                self.checkoutTests = True
            elif o == '--build-tests':
                self.buildTests = True
            elif o == '--coverage':
                self.coverage = True
            elif o == '--base-project':
                self.baseProject = a
            elif o == '--tests-project':
                self.testsProject = a
            elif o == '--html-dir':
                self.htmlDir = a
            elif o == '--run-soft-tests':
                self.runSoftTests = True
        return result
            
    def setEnvironment(self):
        os.environ['https_proxy'] = 'http://wwwcache2.rl.ac.uk:8080'
        os.environ['http_proxy'] = 'http://wwwcache2.rl.ac.uk:8080'
        
    def do(self):
        if self.processArguments():
            self.startHtmlReport()
            self.setEnvironment()
            self.cleanUp()
            self.doCheckoutBase()
            self.fixCoverage()
            self.fixToolsLocation()
            self.fixConfigSite()
            self.doBuildBase()
            self.doCheckoutTests()
            self.fixRelease()
            self.doBuildTests()
            self.doVxTests()
            self.doRtemsTests()
            self.initCoverage()
            self.doHostTests()
            self.doSoftTests()
            self.readCoverage()
            self.finishHtmlReport()

    def initCoverage(self):
        if self.coverage:
            cov = CoverageReport()
            cov.doClean('.')

    def readCoverage(self):
        if self.coverage:
            startTime = time.time()
            cov = CoverageReport()
            webPage = WebPage('Coverage Analysis', 'coverageanalysis',
                self.indexPage.styleSheet)
            cov.doCoverageAnalysis('.', webPage)
            self.addHtmlReport('Coverage analysis', webPage,
                time='%.1f' % (time.time() - startTime))

    def startHtmlReport(self):
        if self.htmlDir is not None:
            sheet = StyleSheet('report.css')
            sheet.createDefault()
            self.indexPage = WebPage('EPICS Base Test Report', 'index', sheet)
            WebPage.forControlsWebSite = True
            args = ''
            for arg in sys.argv:
                if len(args) > 0:
                    args += ' '
                args += arg
            self.indexPage.paragraph(self.indexPage.body(),
                'Job run on %s' % time.strftime("%a, %d %b %Y %H:%M:%S"))
            self.indexPage.paragraph(self.indexPage.body(),
                'Job command issued: %s'% repr(args))
            self.indexTable = self.indexPage.table(self.indexPage.body(),
                ['task', 'result', 'time'], id='releases', cellSpacing='0')

    def finishHtmlReport(self):
        if self.indexPage is not None:
            self.indexPage.write(self.htmlDir)

    def addHtmlReport(self, text, subPage=None, time='', result=''):
        if self.indexPage is not None:
            className = None
            if (self.indexTable.childNodes.length & 1) == 0:
                className = 'alt'
            row = self.indexPage.tableRow(self.indexTable)
            if subPage is None:
                self.indexPage.tableColumn(row, text, className=className)
            else:
                col = self.indexPage.tableColumn(row, className=className)
                self.indexPage.hrefPage(col, subPage, text)
            self.indexPage.tableColumn(row, result, className=className)
            self.indexPage.tableColumn(row, time, className=className)
            
    def cleanUp(self):
        os.system('rm vxTestHarness.boot || true')
        os.system('rm vxTestLog.txt || true')
        os.system('rm vxTestLog.xml || true')
        os.system('rm hostTestLog.txt || true')
        os.system('rm hostTestLog.xml || true')
        os.system('rm softTestLog.txt || true')
        if self.checkoutBase:
            os.system('rm -rf base || true')
        if self.checkoutTests:
            os.system('rm -rf tests || true')
            
    def doCheckoutBase(self):
        '''Check out base from launchpad using bazaar.'''
        if self.checkoutBase:
            startTime = time.time()
            print 'Checking out base...'
            sys.stdout.flush()
            if self.baseRevision is not None:
                cmdLine = 'bzr checkout --lightweight -r %s ' \
                    'http://bazaar.launchpad.net/~%s/epics-base/%s base' % \
                    (self.baseRevision, self.baseProject, self.baseBranch)
            else:
                cmdLine = 'bzr checkout --lightweight ' \
                    'http://bazaar.launchpad.net/~%s/epics-base/%s base' % \
                    (self.baseProject, self.baseBranch)
            os.system(cmdLine)
            self.addHtmlReport('Base checked out using %s.' % repr(cmdLine),
                time='%.1f' % (time.time() - startTime))
            
    def doCheckoutTests(self):
        '''Check out tests from launchpad using bazaar.'''
        if self.checkoutTests:
            startTime = time.time()
            print 'Checking out tests...'
            sys.stdout.flush()
            if self.testsRevision is not None:
                cmdLine = 'bzr checkout --lightweight -r %s ' \
                    'http://bazaar.launchpad.net/~%s/epics-base-tests/%s tests' % \
                    (self.testsRevision, self.testsProject, self.testsBranch)
            else:
                cmdLine = 'bzr checkout --lightweight ' \
                    'http://bazaar.launchpad.net/~%s/epics-base-tests/%s tests' % \
                    (self.testsProject, self.testsBranch)
            os.system(cmdLine)
            self.addHtmlReport('Soft tests checked out using %s.' % repr(cmdLine),
                time='%.1f' % (time.time() - startTime))
            
    def fixCoverage(self):
        '''Fix the configuration files to build with code coverage turned on.'''
        if self.coverage:
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
            #self.addHtmlReport('Make files fixed to enable coverage.')
            
    def fixToolsLocation(self):
        '''Fixes cross compiler tool location for the Diamond site.'''
        if self.checkoutBase:
            # vxWorks tools
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
            # RTEMS tools
            inFile = open('base/configure/os/CONFIG_SITE.Common.RTEMS', 'r')
            lines = inFile.readlines()
            inFile.close()
            outFile = open('base/configure/os/CONFIG_SITE.Common.RTEMS', 'w')
            for line in lines:
                if line.startswith('RTEMS_BASE'):
                    outFile.write('RTEMS_BASE = /dls_sw/targetOS/rtems/4.9.2\n')
                else:
                    outFile.write(line)
            outFile.close()
            # Report
            #self.addHtmlReport('Make files fixed for Diamond tool location.')
        
    def fixConfigSite(self):
        '''Fixes the CONFIG_SITE file to build required cross compiler targets.'''
        if self.checkoutBase:
            inFile = open('base/configure/CONFIG_SITE', 'r')
            lines = inFile.readlines()
            inFile.close()
            outFile = open('base/configure/CONFIG_SITE', 'w')
            for line in lines:
                if line.startswith('CROSS_COMPILER_TARGET_ARCHS'):
                    outFile.write('CROSS_COMPILER_TARGET_ARCHS = vxWorks-ppc604_long RTEMS-pc386 RTEMS-mvme167 RTEMS-mvme5500\n')
                else:
                    outFile.write(line)
            outFile.close()
            #self.addHtmlReport('Make files fixed to enable vxWorks and RTEMS builds.')
        
    def fixRelease(self):
        '''Fixes the RELEASE file to refer to the local base.'''
        if self.checkoutTests:
            inFile = open('tests/configure/RELEASE', 'r')
            lines = inFile.readlines()
            inFile.close()
            outFile = open('tests/configure/RELEASE', 'w')
            for line in lines:
                if line.startswith('EPICS_BASE'):
                    outFile.write('EPICS_BASE = %s\n' % os.path.abspath('base'))
                else:
                    outFile.write(line)
            outFile.close()
            #self.addHtmlReport('Soft tests configure/RELEASE fixed to reference local base.')
    
    def doBuildBase(self):
        '''Build base.'''
        if self.buildBase:
            startTime = time.time()
            os.system('make -C base clean uninstall')
            os.system('make -C base >temp.log 2>&1')
            baseBuildPage = WebPage('Base Build Log', 'baseBuildLog',
                self.indexPage.styleSheet)
            self.buildLogToWebPage('temp.log', baseBuildPage)
            self.addHtmlReport('Base built.', subPage=baseBuildPage,
                time='%.1f' % (time.time() - startTime))
            os.system('rm temp.log || true')
            
    def doBuildTests(self):
        '''Build tests.'''
        if self.buildTests:
            startTime = time.time()
            os.system('make -C tests clean uninstall')
            os.system('make -C tests >temp.log 2>&1')
            testsBuildPage = WebPage('Soft Tests Build Log', 'testsBuildLog',
                self.indexPage.styleSheet)
            self.buildLogToWebPage('temp.log', testsBuildPage) 
            self.addHtmlReport('Soft tests built.', subPage=testsBuildPage,
                time='%.1f' % (time.time() - startTime))
            os.system('rm temp.log || true')

    def buildLogToWebPage(self, logFileName, webPage):
        file = open(logFileName, 'r')
        para = webPage.paragraph(webPage.body(), id='code')
        for line in file:
            webPage.text(para, line)
            webPage.lineBreak(para)

    def doVxTests(self):
        '''Run the vxWorks test suite on a remote target.'''
        if self.runVxTests:
            startTime = time.time()
            # Get the test specs
            specs = self.getTestSpecs()
            if len(specs) > 0:
                for spec in specs:
                    info = self.parseTestSpec(spec)
                    if 'Target-arch' in info and info['Target-arch'] == 'vxWorks-ppc604_long':
                        # Get info
                        munchFiles = []
                        runCmds = []
                        if 'Harness' in info:
                            parts = info['Harness'].split(';')
                            if len(parts) >= 1:
                                munchFiles = parts[0].strip().split()
                            if len(parts) >= 2:
                                runCmds = parts[1].strip().split()
                        pathRoot = os.path.dirname(spec)
                        # Create a boot script
                        bootFault = False
                        bootFile = open('vxTestHarness.boot', 'w')
                        for munchFile in munchFiles:
                            if os.path.exists(os.path.abspath(os.path.join(pathRoot, munchFile))):
                                bootFile.write('ld <%s\n' % \
                                    os.path.abspath(os.path.join(pathRoot, munchFile)))
                            else:
                                print '***Munch file %s does not exist' % \
                                    os.path.abspath(os.path.join(pathRoot, munchFile))
                                bootFault = True
                        bootFile.write('cd "%s"\n' % os.getcwd())
                        for runCmd in runCmds:
                            bootFile.write('%s\n' % runCmd)
                        bootFile.close()
                        # Start up the IOC using the boot script
                        if not bootFault and len(munchFiles)>0 and len(runCmds)>0:
                            ioc = IocEntity('ioc336', directory='.',
                                bootCmd='vxTestHarness.boot', vxWorks=True,
                                telnetAddress='172.23.241.1', telnetPort='7031',
                                telnetLogFile='vxTestLog.txt',
                                powerControlAddress='172.23.243.206', powerControlChan='0')
                                #crateMonitorAddress='172.23.241.1', crateMonitorPort='7032')
                            ioc.start(noStartupScriptWait=True)
                            # Wait for the tests to complete
                            print 'Waiting for tests to complete...'
                            ioc.telnetConnection.waitFor('EPICS Test Harness Results', 20*60)
                # Process the log file
                print 'Processing log file...'
                self.tapToJunit('vxTestLog.txt', 'vxTestLog.xml', 'vxWorks')
                if self.indexPage is not None:
                    vxPage = WebPage('Base Tests, vxWorks Target, Results', 'vxworks',
                        self.indexPage.styleSheet)
                    vxLogPage = WebPage('Base Tests, vxWorks Target, Console Output', 'vxworks-log',
                        self.indexPage.styleSheet)
                    vxPage.hrefPage(vxPage.body(), vxLogPage, 'Console Output')
                    (tests, passes, fails, crashed) = self.tapToHtml('vxTestLog.txt', vxPage, vxLogPage)
                    result = ''
                    if crashed:
                        result = 'Crash detected. '
                    result += 'Tests=%s, Passes=%s, Fails=%s' % (tests, passes, fails)
                    self.addHtmlReport('Base run tests on vxWorks target.', subPage=vxPage,
                        time='%.1fs' % (time.time() - startTime),
                        result=result)
            else:
                self.addHtmlReport('Base run tests on vxWorks target: no tests found.')
                print 'No tests found!'

    def doRtemsTests(self):
        '''Run the RTEMS test suite on a remote target.'''
        if self.runRtemsTests:
            startTime = time.time()
            # Get the test specs
            specs = self.getTestSpecs()
            if len(specs) > 0:
                for spec in specs:
                    info = self.parseTestSpec(spec)
                    if 'Target-arch' in info and info['Target-arch'] == 'RTEMS-mvme5500':
                        # Get info
                        bootFile = None
                        if 'Harness' in info:
                            parts = info['Harness'].split(';')
                            bootFile = parts[0].strip()
                        pathRoot = os.path.dirname(spec)
                        # Start up the IOC
                        if bootFile is not None:
                            ioc = IocEntity('ioc336', directory=pathRoot,
                                bootCmd=bootFile, rtems=True,
                                telnetAddress='172.23.241.1', telnetPort='7028',
                                telnetLogFile='rtemsTestLog.txt',
                                powerControlAddress='172.23.243.206', powerControlChan='0')
                                #crateMonitorAddress='172.23.241.1', crateMonitorPort='7032')
                            ioc.start(noStartupScriptWait=True)
                            # Wait for the tests to complete
                            print 'Waiting for tests to complete...'
                            ioc.telnetConnection.waitFor(
                                ['RTEMS terminated','unrecoverable exception!!!'], 20*60)
                            Sleep(5)
                # Process the log file
                print 'Processing log file...'
                self.tapToJunit('rtemsTestLog.txt', 'rtemsTestLog.xml', 'RTEMS')
                if self.indexPage is not None:
                    rtemsPage = WebPage('Base Tests, RTEMS Target, Results', 'rtems',
                        self.indexPage.styleSheet)
                    rtemsLogPage = WebPage('Base Tests, RTEMS Target, Console Output', 'rtems-log',
                        self.indexPage.styleSheet)
                    rtemsPage.hrefPage(rtemsPage.body(), rtemsLogPage, 'Console Output')
                    (tests, passes, fails, crashed) = self.tapToHtml('rtemsTestLog.txt', rtemsPage, rtemsLogPage)
                    result = ''
                    if crashed:
                        result = 'Crash detected. '
                    result += 'Tests=%s, Passes=%s, Fails=%s' % (tests, passes, fails)
                    self.addHtmlReport('Base run tests on RTEMS target.', subPage=rtemsPage,
                        time='%.1fs' % (time.time() - startTime),
                        result=result)
            else:
                self.addHtmlReport('Base run tests on RTEMS target: no tests found.')
                print 'No tests found!'

    def doHostTests(self):
        '''Run the tests on the host.'''
        if self.runTests:
            startTime = time.time()
            # Get the test specs
            specs = self.getTestSpecs()
            if len(specs) > 0:
                print '\nRunning host tests\n%s\n' % specs
                for spec in specs:
                    info = self.parseTestSpec(spec)
                    if 'Target-arch' in info and info['Target-arch'] == 'linux-x86':
                        # Get info
                        tests = []
                        if 'Tests' in info:
                            tests = info['Tests'].split()
                        # Run each test
                        logPath = os.path.abspath('hostTestLog.txt')
                        for test in tests:
                            if os.path.splitext(test)[1] == '.t':
                                print 'Running test %s' % os.path.join(os.path.dirname(spec), test)
                                # It's a perl test script
                                subprocess.call('echo "***** %s *****" >> hostTestLog.txt' %
                                    os.path.splitext(test)[0], shell=True)
                                subprocess.call('perl %s >> %s' % (test, logPath),
                                    cwd=os.path.dirname(spec), shell=True)
                            else:
                                print '***Unknown test type %s' % \
                                    os.path.join(os.path.dirname(spec), test)
                # Process the log file
                print 'Processing log file...'
                self.tapToJunit('hostTestLog.txt', 'hostTestLog.xml', 'host')
                if self.indexPage is not None:
                    hostPage = WebPage('Base Tests, Host, Results', 'host',
                        self.indexPage.styleSheet)
                    hostLogPage = WebPage('Base Tests, Host, Console Output', 'host-log',
                        self.indexPage.styleSheet)
                    hostPage.hrefPage(hostPage.body(), hostLogPage, 'Console Output')
                    (tests, passes, fails, crashed) = self.tapToHtml('hostTestLog.txt', hostPage, hostLogPage)
                    result = ''
                    if crashed:
                        result = 'Crash detected. '
                    result += 'Tests=%s, Passes=%s, Fails=%s' % (tests, passes, fails)
                    self.addHtmlReport('Base run tests on host.', subPage=hostPage,
                        time='%.1fs' % (time.time() - startTime),
                        result=result)
            else:
                self.addHtmlReport('Base run tests on host: no tests found.')
                print 'No tests found!'

    def doSoftTests(self):
        if self.runSoftTests:
            startTime = time.time()
            # Run the tests
            subprocess.call('dls-run-tests -x -i > softTestLog.txt', shell=True)
            # Process the results
            if self.indexPage is not None:
                softPage = WebPage('Soft Tests, Host, Results', 'soft',
                    self.indexPage.styleSheet)
                # Create the console output page
                softLogPage = WebPage('Soft Tests, Host, Console Output', 'soft-log',
                    self.indexPage.styleSheet)
                softPage.hrefPage(softPage.body(), softLogPage, 'Console Output')
                logFile = open('softTestLog.txt', 'r')
                logBody = softLogPage.preformatted(softLogPage.body())
                for line in logFile:
                    softLogPage.text(logBody, line)
                # Process the log files
                softTable = softPage.table(softPage.body(),
                    ['name', 'tests', 'passes', 'fails'], id='releases', cellSpacing='0')
                files = os.listdir('./tests/etc/test')
                totalCases = 0
                totalPasses = 0
                totalFails = 0
                for file in files:
                    (rootName, extName) = os.path.splitext(file)
                    if extName == '.xml':
                        # Column class name
                        className = None
                        if (softTable.childNodes.length & 1) == 0:
                            className = 'alt'
                        # Create suite page
                        suiteName = 'soft_%s' % rootName
                        suitePage = WebPage(rootName, suiteName,
                            softPage.styleSheet)
                        suiteRow = softPage.tableRow(softTable)
                        col = softPage.tableColumn(suiteRow, className=className)
                        softPage.hrefPage(col, suitePage, rootName)
                        suiteTable = suitePage.table(suitePage.body(),
                            ['#', 'result', 'description'], id='releases', cellSpacing='0')
                        dom = xml.dom.minidom.parse(os.path.join(
                            './tests/etc/test', file))
                        cases = dom.getElementsByTagName('testcase')
                        numCases = 0
                        numPasses = 0
                        numFails = 0
                        for case in cases:
                            numCases += 1
                            # Column class name
                            caseClassName = None
                            if (suiteTable.childNodes.length & 1) == 0:
                                caseClassName = 'alt'
                            if case.getElementsByTagName('error'):
                                suitePage.tableRow(suiteTable, ['%s'%numCases,
                                    'fail', case.getAttribute('name')], colClassName=caseClassName)
                                numFails += 1
                            else:
                                suitePage.tableRow(suiteTable, ['%s'%numCases,
                                    'pass', case.getAttribute('name')], colClassName=caseClassName)
                                numPasses += 1
                        softPage.tableColumn(suiteRow, '%d' % numCases, className=className)
                        softPage.tableColumn(suiteRow, '%d' % numPasses, className=className)
                        softPage.tableColumn(suiteRow, '%d' % numFails, className=className)
                        totalCases += numCases
                        totalPasses += numPasses
                        totalFails += numFails
                self.addHtmlReport('Soft tests on host.', subPage=softPage,
                    time='%.1f' % (time.time() - startTime),
                    result='Tests=%s, Passes=%s, Fails=%s' % (totalCases, totalPasses, totalFails))
            
    def tapToJunit(self, tapFileName, junitFileName, suite):
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
            m = re.match('#?\\*\\*\\*\\*\\*\\s*(\\w*)\\s*\\*\\*\\*\\*\\*', line)
            if m:
                suiteName = suite + '_' + m.group(1)
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
            # RTEMS crash
            m = re.match('.unrecoverable exception', line)
            if m:
                numFails += 1
                element = self.createCaseXmlElement(xmlDoc, xmlTop, suiteName, 'Crashed')
                errorElement = xmlDoc.createElement("error")
                element.appendChild(errorElement)
                errorElement.setAttribute("message", 'Crash')
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
    
    def getTestSpecs(self, dir='.'):
        '''Return a list of test specification files in the current directory.
           Recursively calls itself for sub-directories.'''
        result = []
        files = os.listdir(dir)
        for file in files:
            p = os.path.join(dir, file)
            if os.path.isdir(p):
                result += self.getTestSpecs(p)
            elif file == 'testspec':
                result.append(p)
        return result
            
    def parseTestSpec(self, fileName):
        '''Parses a test spec file returning a dictionary of key word/value pairs.  The
           file syntax is:
              <keyWord> : <value> '''
        result = {}
        file = open(fileName, 'r')
        for line in file:
            parts = line.split(':', 1)
            if len(parts) == 2:
                result[parts[0].strip()] = parts[1].strip()
        return result

    def tapToHtml(self, tapFileName, topPage, logPage=None):
        '''Fills the WebPage object (topPage) with information from the TAP file.
           Returns a tuple consisting of (totalTests, totalPasses, totalFails).'''
        tapFile = open(tapFileName, 'r')
        suiteName = None
        totalTests = 0
        totalFails = 0
        totalPasses = 0
        numTests = 0
        numFails = 0
        numPasses = 0
        crashed = False
        suitePage = None
        suiteTable = None
        topTable = topPage.table(topPage.body(),
            ['name', 'tests', 'passes', 'fails'], id='releases', cellSpacing='0')
        suiteRow = None
        topPageClassName = None
        if logPage is not None:
            logBody = logPage.preformatted(logPage.body())
        for line in tapFile:
            # Fill log page
            if logPage is not None:
                logPage.text(logBody, line)
            # Suite name (not TAP but consistently used in the output)
            m = re.match('#?\\*\\*\\*\\*\\*\\s*(\\w*)\\s*\\*\\*\\*\\*\\*', line)
            if m:
                if suiteName is not None:
                    topPage.tableColumn(suiteRow, '%s' % numTests, className=topPageClassName)
                    topPage.tableColumn(suiteRow, '%s' % numPasses, className=topPageClassName)
                    topPage.tableColumn(suiteRow, '%s' % numFails, className=topPageClassName)
                    totalTests += numTests
                    totalPasses += numPasses
                    totalFails += numFails
                    numTests = 0
                    numPasses = 0
                    numFails = 0
                suiteName = topPage.name + '_' + m.group(1)
                suitePage = WebPage(m.group(1), suiteName, topPage.styleSheet)
                suiteRow = topPage.tableRow(topTable)
                # Column class name
                topPageClassName = None
                if (topTable.childNodes.length & 1) == 0:
                    topPageClassName = 'alt'
                col = topPage.tableColumn(suiteRow, className=topPageClassName)
                topPage.hrefPage(col, suitePage, m.group(1))
                suiteTable = suitePage.table(suitePage.body(), ['#', 'result', 'description'],
                    id='releases', cellSpacing='0')
            # Suite size
            m = re.match('(\\d*)\\.\\.(\\d*)', line)
            if m:
                numTests = int(m.group(2))
            # Column class name
            className = None
            if suitePage is not None and (suiteTable.childNodes.length & 1) == 0:
                className = 'alt'
            # Passing test case
            m = re.match('ok\\s*(\\d*)\\s*[-#]\\s*(.*)', line)
            if m:
                numPasses += 1
                if suitePage is not None:
                    suitePage.tableRow(suiteTable, [m.group(1), 'pass', m.group(2)], colClassName=className)
            else:
                # Passing test case, no description
                m = re.match('ok\\s*(\\d*)', line)
                if m:
                    numPasses += 1
                    if suitePage is not None:
                        suitePage.tableRow(suiteTable, [m.group(1), 'pass', ''], colClassName=className)
            # Failing test case
            m = re.match('not ok\\s*(\\d*)\\s*[-#]\\s*(.*)', line)
            if m:
                numFails += 1
                if suitePage is not None:
                    suitePage.tableRow(suiteTable, [m.group(1), 'fail', m.group(2)], colClassName=className)
            else:
                # Failing test case, no description
                m = re.match('not ok\\s*(\\d*)', line)
                if m:
                    numFails += 1
                    if suitePage is not None:
                        suitePage.tableRow(suiteTable, [m.group(1), 'fail', ''], colClassName=className)
            # RTEMS crash
            m = re.match('.unrecoverable exception', line)
            if m:
                print 'Crash detected.'
                crashed = True
                if suitePage is not None:
                    suitePage.tableRow(suiteTable, ['', 'fail', 'Unrecoverable Exception'], colClassName=className)
            # Stop now if crash detected
            if crashed:
                break
        if suiteName is not None:
            topPage.tableColumn(suiteRow, '%s' % numTests)
            topPage.tableColumn(suiteRow, '%s' % numPasses)
            if crashed:
                topPage.tableColumn(suiteRow, '%s, suite crashed' % numFails)
            else:
                topPage.tableColumn(suiteRow, '%s' % numFails)
        tapFile.close()
        totalTests += numTests
        totalPasses += numPasses
        totalFails += numFails
        return (totalTests, totalPasses, totalFails, crashed)
        
def main():
    Worker().do()

if __name__ == "__main__":
    main()

