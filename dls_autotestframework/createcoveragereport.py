#!/bin/env dls-python2.4

# do imports
import getopt, sys, os, re
from xml.dom.minidom import *
import subprocess

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

class Worker(object):
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
                self.doClean()
            else:
                self.doCoverageAnalysis()
    def doClean(self):
        self.cleanFiles('.')
    def doCoverageAnalysis(self):
        # Make sure the results directory exists
        if self.reportDir is not None:
            if not os.path.exists(self.reportDir):
                os.makedirs(self.reportDir)
            elif not os.path.isdir(self.reportDir):
                print 'Report path exists but is not a directory: %s' % self.reportDir
                self.reportDir = None
        # Drop a style sheet
        if self.reportDir is not None:
            wFile = open(os.path.join(self.reportDir, 'report.css'), 'w+')
            wFile.write('''
                p{text-align:left; color:black; font-family:arial}
                h1{text-align:center; color:green}
                table{border-collapse:collapse}
                table, th, td{border:1px solid black}
                th, td{padding:5px; vertical-align:top}
                th{background-color:#EAf2D3; color:black}
                em{color:red; font-style:normal; font-weight:bold}
                code{font-family:courier}
                ''')
        # Start the top level web page
        if self.reportDir is not None:
            self.indexPage = WebPage('Coverage Analysis', 
                os.path.join(self.reportDir, 'index.html'),
                styleSheet='report.css')
            self.indexTable = self.indexPage.table(self.indexPage.body(), ['file', 'coverage'])
        # Do the work
        self.processFiles('.')
        # Finish the top level web page
        if self.reportDir is not None:
            self.indexPage.write()
    def cleanFiles(self, path):
        '''Delete all *.gcda, *.gcno and *.gcov files.
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
    def processFiles(self, path):
        '''For each *.gcda file in the given path, invoke the gcov command.
           For each subdirectory, recursively call processFiles.'''
        # The file list
        files = os.listdir(path)
        # Process all the gcda file in this directory
        for file in files:
            (fileRoot, fileExt) = os.path.splitext(file)
            if fileExt == '.gcda':
                # Work out the name of the source file
                sourceFile = None
                sourcePath = os.path.normpath(os.path.join(path, '..'))
                if os.path.exists(os.path.join(sourcePath, fileRoot+'.c')):
                    sourceFile = fileRoot+'.c'
                elif os.path.exists(os.path.join(sourcePath, fileRoot+'.cpp')):
                    sourceFile = fileRoot+'.cpp'
                # Now execute gcov on it
                if sourceFile is not None:
                    coverageString = subprocess.Popen('gcov %s' % sourceFile, cwd=path,
                        shell=True, stdout=subprocess.PIPE).communicate()[0]
                    print 'Gcov executed for %s' % os.path.join(path, file)
                else:
                    print 'No source file found for %s' % os.path.join(path, file)
        # Recursively call for each sub-directory
        for file in files:
            filePath = os.path.join(path, file)
            if os.path.isdir(filePath):
                self.processFiles(filePath)
        # Create the report for the source files
        if self.reportDir is not None:
            for file in files:
                (fileRoot, fileExt) = os.path.splitext(file)
                if fileExt == '.c' or fileExt == '.cpp':
                    print 'Writing report for %s' % file
                    webPageName = os.path.join(path,fileRoot+'.html').replace('/','-').lstrip('.').lstrip('-')
                    gcovFile = os.path.join(path,'O.linux-x86',file+'.gcov')
                    if os.path.isfile(gcovFile):
                        # Create the coverage listing page
                        page = WebPage(os.path.join(path,file),
                                os.path.join(self.reportDir, webPageName),
                                styleSheet='report.css')
                        sourceText = open(gcovFile, 'r')
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
                                        page.text(pageBody, parts[0] + ':' + parts[1] + ':' + parts[2])
                                    else:
                                        page.emphasize(pageBody, parts[0] + ':' + parts[1] + ':' + parts[2])
                        page.write()
                        # Plant an entry in the top level web page
                        row = self.indexPage.tableRow(self.indexTable)
                        self.indexPage.href(self.indexPage.tableColumn(row),
                            webPageName, os.path.join(path,file))
                        if significantLines > 0:
                            self.indexPage.tableColumn(row, 
                                '%.2f%% covered' % (coveredLines/significantLines*100.0))
                        else:
                            self.indexPage.tableColumn(row, '100% covered')
                    else:
                        # Plant an entry in the top level web page
                        row = self.indexPage.tableRow(self.indexTable)
                        self.indexPage.tableColumn(row, os.path.join(path,file))
                        self.indexPage.tableColumn(row, 'No coverage information')

class WebPage(object):
    def __init__(self, title, fileName, styleSheet=None):
        '''Initialises a web page, creating all the necessary header stuff'''
        self.fileName = fileName
        self.doc = getDOMImplementation().createDocument(None, "html", None)
        self.topElement = self.doc.documentElement
        h = self.doc.createElement('head')
        self.topElement.appendChild(h)
        if styleSheet is not None:
            l = self.doc.createElement('link')
            h.appendChild(l)
            l.setAttribute('rel', 'stylesheet')
            l.setAttribute('type', 'text/css')
            l.setAttribute('href', styleSheet)
        t = self.doc.createElement('title')
        self.topElement.appendChild(t)
        t.appendChild(self.doc.createTextNode(str(title)))
        self.theBody = self.doc.createElement('body')
        self.topElement.appendChild(self.theBody)
        h = self.doc.createElement('h1')
        self.theBody.appendChild(h)
        h.appendChild(self.doc.createTextNode(str(title)))
    def body(self):
        return self.theBody
    def href(self, parent, tag, descr):
        '''Creates a hot link.'''
        a = self.doc.createElement('a')
        parent.appendChild(a)
        a.setAttribute('href', tag)
        a.appendChild(self.doc.createTextNode(descr))
    def lineBreak(self, parent):
        '''Creates a line break.'''
        parent.appendChild(self.doc.createElement('br'))
    def doc_node(self, text, desc):
        anode = self.doc.createElement('a')
        anode.setAttribute('class','body_con')
        anode.setAttribute('title',desc)
        self.text(anode,text)
        return anode
    def text(self, parent, t):
        '''Creates text.'''
        parent.appendChild(self.doc.createTextNode(str(t)))
    def paragraph(self, parent, text=None, id=None):
        '''Creates a paragraph optionally containing text'''
        para = self.doc.createElement("p")
        if id is not None:
            para.setAttribute('id', id)
        if text is not None:
            para.appendChild(self.doc.createTextNode(str(text)))
        parent.appendChild(para)
        return para
    def preformatted(self, parent, text=None, id=None):
        '''Creates a preformatted block optionally containing text'''
        para = self.doc.createElement("pre")
        if id is not None:
            para.setAttribute('id', id)
        if text is not None:
            para.appendChild(self.doc.createTextNode(str(text)))
        parent.appendChild(para)
        return para
    def write(self):
        '''Writes out the HTML file.'''
        print 'Writing html file %s' % self.fileName
        wFile = open(self.fileName, "w+")
        self.doc.writexml(wFile, indent="", addindent="", newl="")
    def table(self, parent, colHeadings=None, id=None):
        '''Returns a table with optional column headings.'''
        table = self.doc.createElement("table")
        if id is not None:
            table.setAttribute('id', id)
        parent.appendChild(table)
        if colHeadings is not None:
            row = self.doc.createElement("tr")
            if id is not None:
                row.setAttribute('id', id)
            table.appendChild(row)
            for colHeading in colHeadings:
                col = self.doc.createElement("th")
                if id is not None:
                    col.setAttribute('id', id)
                row.appendChild(col)
                col.appendChild(self.doc.createTextNode(str(colHeading)))
        return table
    def tableRow(self, table, columns=None, id=None):
        '''Returns a table row, optionally with columns already created.'''
        row = self.doc.createElement("tr")
        if id is not None:
            row.setAttribute('id', id)
        table.appendChild(row)
        if columns is not None:
            for column in columns:
                col = self.doc.createElement("td")
                if id is not None:
                    col.setAttribute('id', id)
                row.appendChild(col)
                col.appendChild(self.doc.createTextNode(str(column)))
        return row
    def tableColumn(self, tableRow, text=None, id=None):
        '''Returns a table column, optionally containing the text.'''
        col = self.doc.createElement("td")
        if id is not None:
            col.setAttribute('id', id)
        tableRow.appendChild(col)
        if text is not None:
            if hasattr(text, "appendChild"):
                # this is a node
                col.appendChild(text)
            else:
                col.appendChild(self.doc.createTextNode(str(text)))
        return col
    def emphasize(self, parent, text=None):
        '''Returns an emphasis object, optionally containing the text.'''
        result = self.doc.createElement('em')
        parent.appendChild(result)
        if text is not None:
            result.appendChild(self.doc.createTextNode(str(text)))
        return result

def main():
    Worker().do()

if __name__ == "__main__":
    main()

