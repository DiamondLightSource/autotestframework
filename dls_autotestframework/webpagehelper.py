
# Web page helper library.  Uses the standard Python xml.dom.minidom
# library to provide a set of easy to use HTML classes.


# do imports
import sys, os
from xml.dom.minidom import *

class WebPage(object):
    '''Represents the web page you are creating.'''

    forControlsWebSite = False
    
    def __init__(self, title, name, styleSheet=None):
        '''Initialises a web page, creating all the necessary header stuff'''
        self.name = name
        self.children = []
        self.written = False
        self.styleSheet = styleSheet
        self.doc = getDOMImplementation().createDocument(None, "html", None)
        self.topElement = self.doc.documentElement
        h = self.doc.createElement('head')
        self.topElement.appendChild(h)
        if self.styleSheet is not None:
            l = self.doc.createElement('link')
            h.appendChild(l)
            l.setAttribute('rel', 'stylesheet')
            l.setAttribute('type', 'text/css')
            l.setAttribute('href', self.styleSheet.name)
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
        '''Creates a hot link to an external resource.'''
        a = self.doc.createElement('a')
        parent.appendChild(a)
        a.setAttribute('href', tag)
        a.appendChild(self.doc.createTextNode(descr))

    def hrefPage(self, parent, page, descr):
        '''Creates a hot link to a child web page.'''
        self.children.append(page)
        a = self.doc.createElement('a')
        parent.appendChild(a)
        if WebPage.forControlsWebSite:
            a.setAttribute('href', page.name+'.php')
        else:
            a.setAttribute('href', page.name+'.html')
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
        
    phpText = '<?php\n'\
              '$top = "../../..";\n'\
              '$module = "EPICS Base test results";\n'\
              'include("../header.html");\n'\
              'include("./%s.html");\n'\
              'include($top . "/footer.html");\n'\
              '?>\n'

    def write(self, directory):
        '''Writes out the HTML file.'''
        if not self.written:
            # Make sure the results directory exists
            if not os.path.exists(directory):
                os.makedirs(directory)
            if not os.path.isdir(directory):
                print 'Report path exists but is not a directory: %s' % directory
            else:
                htmlFileName = self.name
                if WebPage.forControlsWebSite and htmlFileName == 'index':
                    htmlFileName = 'index_incl'
                if WebPage.forControlsWebSite:
                    # Write the PHP file
                    wFile = open(os.path.join(directory, self.name + '.php'), "w+")
                    wFile.write(self.phpText % htmlFileName)
                    wFile.close()
                    # Write this page
                    wFile = open(os.path.join(directory, htmlFileName + '.html'), "w+")
                    self.body().writexml(wFile, indent="", addindent="", newl="")
                    self.written = True
                else:
                    # Write the style sheet
                    if self.styleSheet is not None:
                        self.styleSheet.write(directory)
                    # Write this page
                    wFile = open(os.path.join(directory, htmlFileName + '.html'), "w+")
                    self.doc.writexml(wFile, indent="", addindent="", newl="")
                    self.written = True
                # Write out children sheets
                for child in self.children:
                    child.write(directory)
        
    def table(self, parent, colHeadings=None, id=None, headingRowId=None, headingColId=None, cellSpacing=None):
        '''Returns a table with optional column headings.'''
        table = self.doc.createElement("table")
        if id is not None:
            table.setAttribute('id', id)
        if cellSpacing is not None:
            table.setAttribute('cellspacing', cellSpacing)
        parent.appendChild(table)
        if colHeadings is not None:
            row = self.doc.createElement("tr")
            if headingRowId is not None:
                row.setAttribute('id', headingRowId)
            table.appendChild(row)
            for colHeading in colHeadings:
                col = self.doc.createElement("th")
                if headingColId is not None:
                    col.setAttribute('id', headingColId)
                row.appendChild(col)
                col.appendChild(self.doc.createTextNode(str(colHeading)))
        return table
                
    def tableRow(self, table, columns=None, id=None, colId=None, colClassName=None):
        '''Returns a table row, optionally with columns already created.'''
        row = self.doc.createElement("tr")
        if id is not None:
            row.setAttribute('id', id)
        table.appendChild(row)
        if columns is not None:
            for column in columns:
                col = self.doc.createElement("td")
                if colId is not None:
                    col.setAttribute('id', colId)
                if colClassName is not None:
                    col.setAttribute('class', colClassName)
                row.appendChild(col)
                col.appendChild(self.doc.createTextNode(str(column)))
        return row
                
    def tableColumn(self, tableRow, text=None, id=None, className=None):
        '''Returns a table column, optionally containing the text.'''
        col = self.doc.createElement("td")
        if id is not None:
            col.setAttribute('id', id)
        if className is not None:
            col.setAttribute('class', className)
        tableRow.appendChild(col)
        if text is not None:
            if hasattr(text, "appendChild"):
                # this is a node
                col.appendChild(text)
            else:
                col.appendChild(self.doc.createTextNode(str(text)))
        return col
            
    def emphasize(self, parent, text=None, className=None):
        '''Returns an emphasis object, optionally containing the text.'''
        result = self.doc.createElement('em')
        if className is not None:
            result.setAttribute('class', className)
        parent.appendChild(result)
        if text is not None:
            result.appendChild(self.doc.createTextNode(str(text)))
        return result

class StyleSheet(object):
    '''Represents a style sheet.  Attach one of these to a WebPage.'''
    
    def __init__(self, name):
        '''Initialise a style sheet.'''
        self.styles = []
        self.name = name
        self.written = False
        
    def write(self, directory):
        '''Write out the style sheet.'''
        if not self.written:
            wFile = open(os.path.join(directory, self.name), 'w+')
            for style in self.styles:
                wFile.write('%s\n' % style)
            self.written = True
            
    def createDefault(self):
        '''Creates the default style used in auto tests.'''
        self.styles = [
            'p{text-align:left; color:black; font-family:arial}',
            'h1{text-align:center; color:green}',
            'table{border-collapse:collapse}',
            'table, th, td{border:1px solid black}',
            'th, td{padding:5px; vertical-align:top}',
            'th{background-color:#EAf2D3; color:black}',
            'em{color:red; font-style:normal; font-weight:bold}',
            '#code{font-family:courier}' ]
        
