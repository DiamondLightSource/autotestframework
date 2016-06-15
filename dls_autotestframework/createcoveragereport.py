#!/bin/env dls-python

# do imports
import getopt, sys, os, re
from xml.dom.minidom import *
import subprocess
from webpagehelper import *

helpText = '''
  Creates a coverage report using the *.gdca files it finds in the directory tree
  starting from the current directory. It is assumed that the source file that
  corresponds to a *.gdca file is inthe directory above and is either a *.c or
  a *.cpp file.

  Syntax:
    dls-create-coverage-report.py [<options>]
        where <options> is one or more of:
        -h, --help                Print the help text and exit
        --report-dir=<directory>  Where to drop the HTML report files
        --clean                   Removes all coverage related files
'''

class CoverageReport(object):
    def __init__(self):
        self.reportDir = None
        self.clean = False
    def processArguments(self):
        '''Process the command line arguments.  Returns False
           if the program is to proceed.'''
        result = True
        try:
            opts, args = getopt.gnu_getopt(sys.argv[1:], 'h',
                ['help', 'report-dir=', 'clean'])
        except getopt.GetoptError, err:
            fail(str(err))
        for o, a in opts:
            if o in ('-h', '--help'):
                print helpText
                result = False
            elif o == '--report-dir':
                self.reportDir = a
            elif o == '--clean':
                self.clean = True
        return result
    def do(self):
        if self.processArguments():
            if self.clean:
                self.doClean('.')
            else:
                sheet = StyleSheet('report.css')
                sheet.createDefault()
                webPage = WebPage('Coverage Analysis', 'index', sheet)
                self.doCoverageAnalysis('.', webPage)
                if self.reportDir is not None:
                    webPage.write(self.reportDir)
    def doClean(self, path):
        self.cleanFiles(path)
    def doCoverageAnalysis(self, path, webPage):
        # Start the top level web page
        self.indexPage = webPage
        self.indexTable = self.indexPage.table(self.indexPage.body(),
            ['file', 'coverage'], id='releases', cellSpacing='0')
        # Do the work
        reports = {}
        self.processFiles(path, reports)
        self.reportNoCoverageFiles(path, reports)
    def cleanFiles(self, path):
        '''Delete all *.gcda, and *.gcov files.
           Recursively call this function for subdirectories.'''
        # The file list
        files = os.listdir(path)
        # Recursively call for each sub-directory
        for file in files:
            filePath = os.path.join(path, file)
            if os.path.isdir(filePath):
                self.cleanFiles(filePath)
        # Delete in this directory
        for file in files:
            (fileRoot, fileExt) = os.path.splitext(file)
            if fileExt in ['.gcda', '.gcov']:
                os.remove(os.path.join(path, file))
    def findSourceFile(self, path, targetRoot):
        '''Looks for the source file (either .c, .cc or .cpp) in the
           directory 'path' or any of its subdirectories.  The full pathname of
           the file is returned or None if none found.'''
        result = None
        files = os.listdir(path)
        for file in files:
            (fileRoot, fileExt) = os.path.splitext(file)
            if os.path.isdir(os.path.join(path, file)):
                # Don't look in directories that look like other OS specific
                if file in ['cygwin32', 'Darwin', 'RTEMS', 'solaris', 'vxWorks',
                        'WIN32', 'freebsd', 'AIX', 'osf']:
                    pass
                else:
                    result = self.findSourceFile(os.path.join(path, file), targetRoot)
            elif fileRoot == targetRoot and fileExt in ['.c', '.cc', '.cpp']:
                result = os.path.normpath(os.path.join(path, file))
            if result is not None:
                break
        return result
    def processFiles(self, path, reports):
        '''For each *.gcda file in the given path, invoke the gcov command.
           For each subdirectory, recursively call processFiles.'''
        # The file list
        files = os.listdir(path)
        # Process all the gcda files in this directory
        for file in files:
            (fileRoot, fileExt) = os.path.splitext(file)
            if fileExt == '.gcda':
                # Work out the name of the source file
                sourcePath = self.findSourceFile(os.path.join(path, '..'), fileRoot)
                if sourcePath is not None:
                    # Now execute gcov on it
                    (sourceDir, sourceFile) = os.path.split(sourcePath)
                    coverageString = subprocess.Popen('gcov %s' % sourceFile, cwd=path,
                        shell=True, stdout=subprocess.PIPE).communicate()[0]
                    # Now create the report
                    self.createReport(sourcePath, path)
                    reports[sourcePath] = True
                else:
                    print 'No source file found for %s' % os.path.join(path, file)
        # Recursively call for each sub-directory
        for file in files:
            filePath = os.path.join(path, file)
            if os.path.isdir(filePath):
                self.processFiles(filePath, reports)
    def reportNoCoverageFiles(self, path, reports={}):
        '''For each *.c, *.cc, *.cpp file in the given path not in reports, report
           no coverage information.
           For each subdirectory, recursively call reportNoCoverageFiles.'''
        # The file list
        files = os.listdir(path)
        # Recursively call for each sub-directory
        for file in files:
            filePath = os.path.join(path, file)
            if os.path.isdir(filePath):
                self.reportNoCoverageFiles(filePath, reports)
        # Report on any files with no coverage
        for file in files:
            (fileRoot, fileExt) = os.path.splitext(file)
            if fileExt in ['.c', '.cc', '.cpp']:
                filePath = os.path.normpath(os.path.join(path, file))
                if filePath not in reports:
                    # Plant an entry in the top level web page
                    className = None
                    if (self.indexTable.childNodes.length & 1) == 0:
                        className = 'alt'
                    row = self.indexPage.tableRow(self.indexTable)
                    self.indexPage.tableColumn(row, filePath, className=className)
                    self.indexPage.tableColumn(row, 'No coverage information', className=className)
    def createReport(self, sourcePath, gcovDirectory):
        # Create the report for a source file
        (directory, file) = os.path.split(sourcePath)
        (fileRoot, fileExt) = os.path.splitext(file)
        gcovPath = os.path.join(gcovDirectory, file+'.gcov')
        if os.path.isfile(gcovPath):
            # Create the coverage listing page
            webPageFileName = os.path.join(directory,fileRoot).replace('/','-').\
                lstrip('.').lstrip('-')
            page = WebPage(sourcePath, webPageFileName,
                    styleSheet = self.indexPage.styleSheet)
            sourceText = open(gcovPath, 'r')
            significantLines = 0.0
            coveredLines = 0.0
            pageBody = page.preformatted(page.body())
            for line in sourceText:
                parts = line.split(':',2)
                if len(parts) == 3:
                    covered = True
                    if parts[0].endswith('#'):
                        covered = False
                        significantLines += 1.0
                    elif parts[0].endswith('-'):
                        pass
                    else:
                        coveredLines += 1.0
                        significantLines += 1.0
                    if parts[1].strip() == '0':
                        pass
                    else:
                        if covered:
                            page.text(pageBody, parts[0] + ':' +
                                parts[1] + ':' + parts[2])
                        else:
                            page.emphasize(pageBody, parts[0] + ':' +
                                parts[1] + ':' + parts[2], className="active")
            # Plant an entry in the top level web page
            className = None
            if (self.indexTable.childNodes.length & 1) == 0:
                className = 'alt'
            row = self.indexPage.tableRow(self.indexTable)
            self.indexPage.hrefPage(self.indexPage.tableColumn(row, className=className),
                page, sourcePath)
            if significantLines > 0:
                self.indexPage.tableColumn(row,
                    '%.2f%% covered' % (coveredLines/significantLines*100.0), className=className)
            else:
                self.indexPage.tableColumn(row, '100% covered', className=className)
        else:
            # Plant an entry in the top level web page
            className = None
            if (self.indexTable.childNodes.length & 1) == 0:
                className = 'alt'
            row = self.indexPage.tableRow(self.indexTable)
            self.indexPage.tableColumn(row, sourcePath, className=className)
            self.indexPage.tableColumn(row, 'No coverage information', className=className)

def main():
    CoverageReport().do()

if __name__ == "__main__":
    main()

